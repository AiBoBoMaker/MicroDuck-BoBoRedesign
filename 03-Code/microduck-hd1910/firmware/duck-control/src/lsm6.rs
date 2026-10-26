//! LSM6DSV16X over I²C — the chip inside a WDS601M module.
//!
//! The `imu_to_dxl` board is this same part, speaking Dynamixel. Here the host talks to the
//! chip directly and hands [`crate::imu::SflpDecoder`] the block that board used to build:
//! gyro counts at ±500 dps (17.5 mdps/LSB) and the SFLP game-rotation quaternion as three
//! IEEE half-precision components. The sensitivity and the quaternion layout are the
//! decoder's contract (`imu.rs`); changing either here silently tilts the policy's horizon.
//!
//! SFLP results are only available from the FIFO (AN5763). Gyro is read from the output
//! registers, which is what the old board put in the first six bytes. Register numbers and
//! bit positions are the datasheet's (DS13476) and match ST's `lsm6dsv16x_reg` driver.

use crate::imu::IMU_BLOCK_LEN;

/// `WHO_AM_I` for LSM6DSV16X / LSM6DSV16XTR.
const WHO_AM_I_VAL: u8 = 0x70;

/// SDO/SA0 low, then high. A module that straps the pin the other way answers the second.
const ADDR_LOW: u8 = 0x6A;
const ADDR_HIGH: u8 = 0x6B;

const WHO_AM_I: u8 = 0x0F;
const FUNC_CFG_ACCESS: u8 = 0x01;
/// `FUNC_CFG_ACCESS.emb_func_reg_access`, bit 7. Selects the embedded-function register bank.
const EMB_FUNC_BANK: u8 = 0x80;

const FIFO_CTRL1: u8 = 0x07;
const FIFO_CTRL4: u8 = 0x0A;
const CTRL1: u8 = 0x10;
const CTRL2: u8 = 0x11;
const CTRL3: u8 = 0x12;
const CTRL6: u8 = 0x15;
const CTRL8: u8 = 0x17;
const FIFO_STATUS1: u8 = 0x1B;
const OUTX_L_G: u8 = 0x22;
const FIFO_DATA_OUT_TAG: u8 = 0x78;

/// Embedded-function bank (only visible while [`EMB_FUNC_BANK`] is set).
const EMB_FUNC_EN_A: u8 = 0x04;
const EMB_FUNC_FIFO_EN_A: u8 = 0x44;
const SFLP_ODR: u8 = 0x5E;

/// `EMB_FUNC_EN_A.sflp_game_en` and `EMB_FUNC_FIFO_EN_A.sflp_game_fifo_en` are both bit 1.
const SFLP_GAME_BIT: u8 = 1 << 1;

/// `SFLP_ODR.sflp_game_odr` is bits 5:3. `0x03` is 120 Hz, which matches the sensor ODR below
/// and stays above the 50 Hz control loop.
const SFLP_ODR_120HZ: u8 = 0x03 << 3;
const SFLP_ODR_MASK: u8 = 0x07 << 3;

/// CTRL1/CTRL2 low nibble. `0x06` is 120 Hz, high-performance mode (the mode bits stay 0).
const ODR_120HZ: u8 = 0x06;

/// `CTRL3`: bit 6 `BDU`, bit 2 `IF_INC` (auto-increment, so a block read stays in order),
/// bit 0 `SW_RESET`.
const CTRL3_BDU: u8 = 1 << 6;
const CTRL3_IF_INC: u8 = 1 << 2;
const CTRL3_SW_RESET: u8 = 1 << 0;

/// `CTRL6.FS_G` is bits 3:0. `0x02` is ±500 dps, 17.5 mdps/LSB — the scale [`crate::imu`]
/// multiplies by. Any other full scale reports a rate the policy was not trained on.
const FS_G_MASK: u8 = 0x0F;
const FS_G_500DPS: u8 = 0x02;

/// `CTRL8.FS_XL` is bits 1:0. `0x01` is ±4 g, which is what ST's SFLP example runs.
const FS_XL_MASK: u8 = 0x03;
const FS_XL_4G: u8 = 0x01;

/// `FIFO_CTRL4.FIFO_MODE` is bits 2:0. `6` is continuous (stream): a full FIFO overwrites
/// the oldest word instead of stopping.
const FIFO_MODE_MASK: u8 = 0x07;
const FIFO_MODE_BYPASS: u8 = 0x00;
const FIFO_MODE_STREAM: u8 = 0x06;

/// `FIFO_DATA_OUT_TAG.TAG_SENSOR` is bits 7:3. `0x13` is the SFLP game-rotation vector:
/// three little-endian binary16 components, x then y then z.
const TAG_SHIFT: u8 = 3;
const TAG_GAME_ROTATION: u8 = 0x13;

/// How many FIFO words one tick will walk. At 120 Hz against a 50 Hz loop the steady state
/// is two or three; past this the backlog is stale and is discarded rather than read, because
/// each word is its own I²C transaction and a deep FIFO would eat the tick.
const FIFO_DRAIN_MAX: u16 = 16;

/// The sensor tag in a FIFO word. `TAG_CNT` occupies the low bits and must not be part of
/// the comparison — a counter that happens to match `0x13` would be read as a quaternion.
pub fn fifo_sensor_tag(tag_byte: u8) -> u8 {
    tag_byte >> TAG_SHIFT
}

/// Gyro counts then quaternion, the layout [`crate::imu::SflpDecoder::decode`] reads.
pub fn pack_block(gyro_le: &[u8; 6], quat_le: &[u8; 6]) -> [u8; IMU_BLOCK_LEN] {
    let mut block = [0u8; IMU_BLOCK_LEN];
    block[..6].copy_from_slice(gyro_le);
    block[6..].copy_from_slice(quat_le);
    block
}

#[cfg(target_os = "linux")]
use i2cdev::core::I2CDevice;

/// A configured LSM6DSV16X. Linux only: the bus is `/dev/i2c-*`.
#[cfg(target_os = "linux")]
pub struct Lsm6 {
    dev: i2cdev::linux::LinuxI2CDevice,
    addr: u8,
    /// Ticks that produced gyro but no live quaternion. One warning, not one per tick.
    quat_misses: u32,
    warned_quat: bool,
}

#[cfg(target_os = "linux")]
impl Lsm6 {
    /// Open `path`, confirm `WHO_AM_I`, and start SFLP.
    ///
    /// `addr == 0` probes [`ADDR_LOW`] then [`ADDR_HIGH`]. A non-zero address is used as
    /// given and a wrong chip is an error rather than a silent probe of the other one —
    /// somebody who set the address meant that device.
    pub fn open(path: &str, addr: u8) -> Result<Self, String> {
        let (dev, addr) = if addr == 0 {
            match try_open(path, ADDR_LOW) {
                Ok(dev) => (dev, ADDR_LOW),
                Err(low) => match try_open(path, ADDR_HIGH) {
                    Ok(dev) => (dev, ADDR_HIGH),
                    Err(high) => {
                        return Err(format!(
                            "no LSM6DSV16X on {path} at 0x{ADDR_LOW:02x} ({low}) or 0x{ADDR_HIGH:02x} ({high})"
                        ));
                    }
                },
            }
        } else {
            let dev = try_open(path, addr)?;
            (dev, addr)
        };

        let mut chip = Self {
            dev,
            addr,
            quat_misses: 0,
            warned_quat: false,
        };
        chip.configure()?;
        tracing::info!(
            path,
            addr,
            "body IMU is LSM6DSV16X on I2C, SFLP game rotation at 120 Hz"
        );
        Ok(chip)
    }

    /// One sample in the decoder's 12-byte layout. Gyro is always current; the quaternion
    /// is the newest game-rotation word in the FIFO, or zeros when SFLP has not written one
    /// yet — which the decoder already treats as "hold the last orientation".
    pub fn read_block(&mut self) -> Result<[u8; IMU_BLOCK_LEN], String> {
        let gyro = self.read_bytes(OUTX_L_G, 6)?;
        let mut gyro_le = [0u8; 6];
        gyro_le.copy_from_slice(&gyro);

        let mut quat_le = [0u8; 6];
        let level = self.fifo_level()?;
        if level > FIFO_DRAIN_MAX {
            // Stream mode keeps the oldest word at the front. Draining a deep backlog would
            // spend the tick on samples the loop has already missed, so drop them and let the
            // next ticks read fresh ones. The decoder holds its last quaternion across the gap.
            self.set_fifo_mode(FIFO_MODE_BYPASS)?;
            self.set_fifo_mode(FIFO_MODE_STREAM)?;
            self.note_quat(false);
        } else {
            let mut saw_tag = false;
            for _ in 0..level {
                let word = self.read_bytes(FIFO_DATA_OUT_TAG, 7)?;
                if fifo_sensor_tag(word[0]) == TAG_GAME_ROTATION {
                    quat_le.copy_from_slice(&word[1..7]);
                    saw_tag = true;
                }
            }
            // A word of zeros is legal: it is how SFLP says it has not settled, and it is
            // also a perfectly upright quaternion. Either way the decoder holds its last
            // good orientation. What is not legal is a FIFO that never carries the tag.
            self.note_quat(saw_tag);
        }

        Ok(pack_block(&gyro_le, &quat_le))
    }

    fn note_quat(&mut self, live: bool) {
        if live {
            self.quat_misses = 0;
            return;
        }
        self.quat_misses = self.quat_misses.saturating_add(1);
        // Two seconds at 50 Hz. SFLP's own startup is about a quarter of a second; past this
        // the chip is up and the FIFO is simply not carrying a quaternion.
        if self.quat_misses == 100 && !self.warned_quat {
            self.warned_quat = true;
            tracing::warn!(
                addr = self.addr,
                "LSM6DSV16X has not produced an SFLP quaternion — orientation is still the default"
            );
        }
    }

    fn configure(&mut self) -> Result<(), String> {
        self.write_u8(CTRL3, CTRL3_SW_RESET)?;
        let mut reset_done = false;
        for _ in 0..20 {
            std::thread::sleep(std::time::Duration::from_millis(1));
            if self.read_u8(CTRL3)? & CTRL3_SW_RESET == 0 {
                reset_done = true;
                break;
            }
        }
        if !reset_done {
            return Err("LSM6DSV16X software reset did not finish".to_owned());
        }

        self.rmw(CTRL3, 0, CTRL3_BDU | CTRL3_IF_INC)?;
        self.rmw(CTRL6, FS_G_MASK, FS_G_500DPS)?;
        self.rmw(CTRL8, FS_XL_MASK, FS_XL_4G)?;

        // Watermark is in words. 1 makes the status flag track "anything is waiting"; the
        // tick reads the level directly and does not wait on the flag.
        self.write_u8(FIFO_CTRL1, 1)?;

        // ST's SFLP example order: batch the quaternion into the FIFO, start the FIFO,
        // start the sensors, then set the fusion rate and enable it. The rate has to be
        // at or below the sensor ODR, which is why the sensors are already at 120 Hz.
        self.with_embedded(|chip| chip.rmw(EMB_FUNC_FIFO_EN_A, 0, SFLP_GAME_BIT))?;
        self.set_fifo_mode(FIFO_MODE_STREAM)?;
        self.write_u8(CTRL1, ODR_120HZ)?;
        self.write_u8(CTRL2, ODR_120HZ)?;
        self.with_embedded(|chip| {
            chip.rmw(SFLP_ODR, SFLP_ODR_MASK, SFLP_ODR_120HZ)?;
            chip.rmw(EMB_FUNC_EN_A, 0, SFLP_GAME_BIT)?;
            Ok(())
        })?;
        Ok(())
    }

    fn set_fifo_mode(&mut self, mode: u8) -> Result<(), String> {
        self.rmw(FIFO_CTRL4, FIFO_MODE_MASK, mode & FIFO_MODE_MASK)
    }

    /// `FIFO_STATUS` DIFF_FIFO is 9 bits: the low 8 in STATUS1, bit 0 of STATUS2.
    fn fifo_level(&mut self) -> Result<u16, String> {
        let status = self.read_bytes(FIFO_STATUS1, 2)?;
        Ok(u16::from(status[0]) | (u16::from(status[1] & 0x01) << 8))
    }

    fn with_embedded<T>(
        &mut self,
        f: impl FnOnce(&mut Self) -> Result<T, String>,
    ) -> Result<T, String> {
        self.write_u8(FUNC_CFG_ACCESS, EMB_FUNC_BANK)?;
        let result = f(self);
        // Back to the main bank even when `f` failed. A gyro read left on the embedded page
        // returns bytes that look like a sample and are not one.
        let restored = self.write_u8(FUNC_CFG_ACCESS, 0);
        match (result, restored) {
            (Ok(value), Ok(())) => Ok(value),
            (Err(err), _) => Err(err),
            (Ok(_), Err(err)) => Err(err),
        }
    }

    /// Clear `mask`, then set `bits`. `mask == 0` only sets.
    fn rmw(&mut self, reg: u8, mask: u8, bits: u8) -> Result<(), String> {
        let current = self.read_u8(reg)?;
        self.write_u8(reg, (current & !mask) | bits)
    }

    fn read_u8(&mut self, reg: u8) -> Result<u8, String> {
        self.dev
            .smbus_read_byte_data(reg)
            .map_err(|err| format!("read 0x{reg:02x}: {err}"))
    }

    fn write_u8(&mut self, reg: u8, value: u8) -> Result<(), String> {
        self.dev
            .smbus_write_byte_data(reg, value)
            .map_err(|err| format!("write 0x{reg:02x}: {err}"))
    }

    fn read_bytes(&mut self, reg: u8, len: u8) -> Result<Vec<u8>, String> {
        let data = self
            .dev
            .smbus_read_i2c_block_data(reg, len)
            .map_err(|err| format!("read {len} bytes at 0x{reg:02x}: {err}"))?;
        if data.len() != len as usize {
            return Err(format!(
                "read at 0x{reg:02x}: expected {len} bytes, got {}",
                data.len()
            ));
        }
        Ok(data)
    }
}

#[cfg(target_os = "linux")]
fn try_open(path: &str, addr: u8) -> Result<i2cdev::linux::LinuxI2CDevice, String> {
    let mut dev = i2cdev::linux::LinuxI2CDevice::new(path, u16::from(addr))
        .map_err(|err| format!("open {path} address 0x{addr:02x}: {err}"))?;
    let id = dev
        .smbus_read_byte_data(WHO_AM_I)
        .map_err(|err| format!("WHO_AM_I at 0x{addr:02x}: {err}"))?;
    if id != WHO_AM_I_VAL {
        return Err(format!(
            "address 0x{addr:02x} answered WHO_AM_I 0x{id:02x}, not 0x{WHO_AM_I_VAL:02x}"
        ));
    }
    Ok(dev)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_fifo_tag_ignores_the_counter_bits() {
        assert_eq!(
            fifo_sensor_tag(TAG_GAME_ROTATION << TAG_SHIFT),
            TAG_GAME_ROTATION
        );
        // TAG_CNT in bits 2:1 must not change which sensor this word is.
        assert_eq!(
            fifo_sensor_tag((TAG_GAME_ROTATION << TAG_SHIFT) | 0x06),
            TAG_GAME_ROTATION
        );
        assert_ne!(fifo_sensor_tag(0x13), TAG_GAME_ROTATION);
    }

    /// The bytes the chip puts on the wire are the bytes the decoder consumes, in order.
    /// A swap of gyro and quaternion, or a big-endian store, is a robot that walks sideways.
    #[test]
    fn the_packed_block_is_gyro_then_half_precision_quaternion() {
        let mut gyro = [0u8; 6];
        gyro[0..2].copy_from_slice(&100i16.to_le_bytes());
        gyro[4..6].copy_from_slice(&(-100i16).to_le_bytes());
        let mut quat = [0u8; 6];
        quat[0..2].copy_from_slice(&0x3000u16.to_le_bytes());

        let block = pack_block(&gyro, &quat);
        assert_eq!(&block[..6], &gyro);
        assert_eq!(&block[6..], &quat);

        let mut decoder = crate::imu::SflpDecoder::new(crate::imu::SflpDecoder::NATIVE_MOUNT);
        let sample = decoder.decode(&block);
        assert_ne!(sample.quat, [1.0, 0.0, 0.0, 0.0]);
        assert!(sample.gyro.iter().any(|axis| axis.abs() > 0.0));
    }
}
