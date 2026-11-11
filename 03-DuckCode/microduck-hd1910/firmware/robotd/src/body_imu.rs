//! Startup choice of the body IMU wire.
//!
//! `dxl` and `i2c` stay explicit. `auto` probes the LSM6DSV16X once and, if that
//! chip does not answer, requires ID 200 on the servo bus. The caller locks the
//! winner for the process: a later read failure does not switch wires, and an
//! I²C hit never pings ID 200.

use crate::params::{BodyImu, Bus, ImuMount};

/// The wire the control loop will keep using. `auto` never appears here.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Wire {
    I2c,
    Dxl,
}

impl Wire {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::I2c => "i2c",
            Self::Dxl => "dxl",
        }
    }
}

/// What the I²C probe found. `Skipped` is an explicit bus-board config: the
/// chip is not opened.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Probe {
    Hit,
    Miss,
    Skipped,
}

/// Pure selection. Explicit `i2c` fails closed when the probe misses. `auto`
/// falls through to the bus board. `dxl` ignores a chip that happens to be present.
pub fn decide(mode: BodyImu, probe: Probe) -> Result<Wire, ()> {
    match (mode, probe) {
        (BodyImu::Dxl, _) => Ok(Wire::Dxl),
        (BodyImu::I2c, Probe::Hit) => Ok(Wire::I2c),
        (BodyImu::I2c, _) => Err(()),
        (BodyImu::Auto, Probe::Hit) => Ok(Wire::I2c),
        (BodyImu::Auto, _) => Ok(Wire::Dxl),
    }
}

/// Sensor-to-trunk rotation for the locked wire.
///
/// The bus board always uses the calibration quaternion. `native` is identity
/// and applies only after the process has locked to I²C.
pub fn mount_quat(wire: Wire, native_mount: bool, calibration: [f64; 4]) -> [f64; 4] {
    if wire == Wire::I2c && native_mount {
        duck_control::imu::SflpDecoder::NATIVE_MOUNT
    } else {
        calibration
    }
}

/// Config the three Feetech entry points share.
pub struct Request<'a> {
    pub mode: BodyImu,
    pub i2c_path: &'a str,
    pub i2c_addr: u8,
    pub native_mount: bool,
}

impl<'a> Request<'a> {
    pub fn from_bus(bus: &'a Bus) -> Self {
        Self {
            mode: bus.imu,
            i2c_path: &bus.i2c,
            i2c_addr: bus.i2c_addr,
            native_mount: bus.imu_mount == ImuMount::Native,
        }
    }
}

/// Result of one startup probe. `note` is set only when `auto` missed I²C and
/// the caller still has to find ID 200.
pub struct Opened {
    pub wire: Wire,
    pub note: Option<String>,
    #[cfg(target_os = "linux")]
    pub chip: Option<duck_control::lsm6::Lsm6>,
}

/// Append the I²C miss, when there was one, to a later bus-board failure.
pub fn annotate(opened: &Opened, error: String) -> String {
    match &opened.note {
        Some(note) => format!("{error} ({note})"),
        None => error,
    }
}

pub fn log_locked(configured: BodyImu, opened: &Opened) {
    tracing::info!(
        configured = configured.as_str(),
        locked = opened.wire.as_str(),
        i2c_probe = opened.note.as_deref(),
        "body IMU source locked for this process"
    );
}

/// Probe I²C before the caller touches ID 200. Explicit `dxl` does not open the chip.
pub fn open(request: &Request<'_>) -> Result<Opened, String> {
    if request.mode == BodyImu::Dxl {
        return Ok(Opened {
            wire: Wire::Dxl,
            note: None,
            #[cfg(target_os = "linux")]
            chip: None,
        });
    }

    #[cfg(target_os = "linux")]
    {
        return match duck_control::lsm6::Lsm6::open(request.i2c_path, request.i2c_addr) {
            Ok(chip) => Ok(Opened {
                wire: decide(request.mode, Probe::Hit).expect("a hit locks to i2c"),
                note: None,
                chip: Some(chip),
            }),
            Err(error) => match decide(request.mode, Probe::Miss) {
                Ok(wire) => Ok(Opened {
                    wire,
                    note: Some(error),
                    chip: None,
                }),
                Err(()) => Err(error),
            },
        };
    }

    #[cfg(not(target_os = "linux"))]
    {
        let _ = (request.i2c_path, request.i2c_addr);
        if request.mode == BodyImu::Auto {
            Ok(Opened {
                wire: Wire::Dxl,
                note: Some("I2C IMU is only available on Linux".into()),
            })
        } else {
            Err("I2C IMU is only available on Linux".into())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explicit_modes_do_not_fall_through() {
        assert_eq!(decide(BodyImu::Dxl, Probe::Hit).unwrap(), Wire::Dxl);
        assert_eq!(decide(BodyImu::Dxl, Probe::Skipped).unwrap(), Wire::Dxl);
        assert_eq!(decide(BodyImu::I2c, Probe::Hit).unwrap(), Wire::I2c);
        assert!(decide(BodyImu::I2c, Probe::Miss).is_err());
        assert!(decide(BodyImu::I2c, Probe::Skipped).is_err());
    }

    #[test]
    fn auto_prefers_i2c_and_otherwise_uses_the_bus_board() {
        assert_eq!(decide(BodyImu::Auto, Probe::Hit).unwrap(), Wire::I2c);
        assert_eq!(decide(BodyImu::Auto, Probe::Miss).unwrap(), Wire::Dxl);
        assert_eq!(decide(BodyImu::Auto, Probe::Skipped).unwrap(), Wire::Dxl);
    }

    #[test]
    fn native_mount_applies_only_to_the_i2c_wire() {
        let board = duck_control::imu::SflpDecoder::DEFAULT_MOUNT;
        assert_eq!(
            mount_quat(Wire::I2c, true, board),
            duck_control::imu::SflpDecoder::NATIVE_MOUNT
        );
        assert_eq!(mount_quat(Wire::I2c, false, board), board);
        assert_eq!(mount_quat(Wire::Dxl, true, board), board);
        assert_eq!(mount_quat(Wire::Dxl, false, board), board);
    }

    #[test]
    fn annotate_keeps_an_auto_miss_next_to_the_bus_error() {
        let opened = Opened {
            wire: Wire::Dxl,
            note: Some("no LSM6DSV16X".into()),
            #[cfg(target_os = "linux")]
            chip: None,
        };
        assert_eq!(
            annotate(&opened, "IMU200 missing".into()),
            "IMU200 missing (no LSM6DSV16X)"
        );
        let explicit = Opened {
            wire: Wire::Dxl,
            note: None,
            #[cfg(target_os = "linux")]
            chip: None,
        };
        assert_eq!(annotate(&explicit, "IMU200 missing".into()), "IMU200 missing");
    }
}
