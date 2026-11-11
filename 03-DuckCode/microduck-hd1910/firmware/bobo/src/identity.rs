//! `Device-Id` is the MAC, `Client-Id` is a UUID that survives reboots.
//!
//! The reference firmware stores the UUID in NVS and the MAC from the wifi interface.
//! A duck has neither NVS nor a single fixed interface name, so the MAC is the first
//! real one (wifi preferred) and the UUID is a file.

use std::path::Path;

/// Pick a MAC the way a person would: wifi, then ethernet, then anything that is not
/// loopback. Addresses are already lowercase colon-separated on Linux.
pub fn choose_mac<'a>(ifaces: impl IntoIterator<Item = (&'a str, &'a str)>) -> String {
    let mut best: Option<(u8, String)> = None;
    for (name, address) in ifaces {
        let address = address.trim().to_ascii_lowercase();
        if name == "lo" || address.is_empty() || address == "00:00:00:00:00:00" {
            continue;
        }
        let rank = if name.starts_with("wl") || name.starts_with("wlan") {
            0
        } else if name.starts_with("en") || name.starts_with("eth") {
            1
        } else {
            2
        };
        if best.as_ref().is_none_or(|current| rank < current.0) {
            best = Some((rank, address));
        }
    }
    best.map(|(_, address)| address)
        .unwrap_or_else(|| "00:00:00:00:00:00".to_owned())
}

pub fn device_id() -> String {
    let root = Path::new("/sys/class/net");
    let mut found = Vec::new();
    if let Ok(entries) = std::fs::read_dir(root) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            let address = std::fs::read_to_string(entry.path().join("address")).unwrap_or_default();
            found.push((name, address));
        }
    }
    choose_mac(found.iter().map(|(name, address)| (name.as_str(), address.as_str())))
}

pub fn client_id(path: &Path) -> String {
    if let Ok(existing) = std::fs::read_to_string(path) {
        let existing = existing.trim();
        if !existing.is_empty() {
            return existing.to_owned();
        }
    }
    let id = uuid::Uuid::new_v4().to_string();
    if let Some(parent) = path.parent()
        && !parent.as_os_str().is_empty()
    {
        let _ = std::fs::create_dir_all(parent);
    }
    if let Err(error) = std::fs::write(path, &id) {
        tracing::warn!(%error, path = %path.display(), "cannot store the bobo client id");
    }
    id
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wifi_beats_ethernet_and_loopback_is_ignored() {
        let mac = choose_mac([
            ("lo", "00:00:00:00:00:00"),
            ("eth0", "AA:BB:CC:DD:EE:01"),
            ("wlan0", "aa:bb:cc:dd:ee:02\n"),
        ]);
        assert_eq!(mac, "aa:bb:cc:dd:ee:02");
    }

    #[test]
    fn a_missing_radio_still_produces_a_header() {
        assert_eq!(choose_mac([]), "00:00:00:00:00:00");
    }

    #[test]
    fn the_client_id_is_stable_across_reads() {
        let dir = std::env::temp_dir().join(format!("bobo-id-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let path = dir.join("client-id");
        let first = client_id(&path);
        let second = client_id(&path);
        assert_eq!(first, second);
        assert_eq!(uuid::Uuid::parse_str(&first).is_ok(), true);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
