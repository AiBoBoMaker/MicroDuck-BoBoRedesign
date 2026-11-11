//! The JSON messages for a Bobo voice call, protocol version 1.
//!
//! Binary frames are raw Opus. Version 2 and 3 wrap that payload; this client speaks
//! version 1, which is what the reference firmware sends unless a setting says otherwise.

use serde_json::{json, Value};

pub const PROTOCOL_VERSION: u32 = 1;
pub const FRAME_MS: u32 = 60;
pub const UPLINK_RATE: u32 = 16_000;
/// Downlink rate until the server's hello names another one. The reference plays 24 kHz TTS.
pub const DEFAULT_DOWNLINK_RATE: u32 = 24_000;

pub fn hello_message() -> String {
    json!({
        "type": "hello",
        "version": PROTOCOL_VERSION,
        "transport": "websocket",
        "audio_params": {
            "format": "opus",
            "sample_rate": UPLINK_RATE,
            "channels": 1,
            "frame_duration": FRAME_MS
        }
    })
    .to_string()
}

pub fn listen_start(session_id: &str) -> String {
    json!({
        "session_id": session_id,
        "type": "listen",
        "state": "start",
        "mode": "auto"
    })
    .to_string()
}

pub fn abort(session_id: &str) -> String {
    json!({
        "session_id": session_id,
        "type": "abort"
    })
    .to_string()
}

/// `Authorization` header value. Empty stays absent. A token that already carries a
/// scheme (`"Bearer …"`) is sent unchanged, matching the reference firmware.
pub fn authorization_value(token: &str) -> Option<String> {
    let token = token.trim();
    if token.is_empty() {
        None
    } else if token.contains(' ') {
        Some(token.to_owned())
    } else {
        Some(format!("Bearer {token}"))
    }
}

pub fn message_type(value: &Value) -> Option<&str> {
    value.get("type").and_then(Value::as_str)
}

/// Server hello. `None` when the transport is not websocket — the reference treats that
/// as "not our server" and keeps waiting.
pub fn parse_server_hello(value: &Value) -> Option<ServerHello> {
    if message_type(value) != Some("hello") {
        return None;
    }
    let transport = value.get("transport").and_then(Value::as_str).unwrap_or("");
    if transport != "websocket" {
        return None;
    }
    let session_id = value
        .get("session_id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned();
    let audio = value.get("audio_params");
    let sample_rate = audio
        .and_then(|p| p.get("sample_rate"))
        .and_then(Value::as_u64)
        .unwrap_or(DEFAULT_DOWNLINK_RATE as u64) as u32;
    let frame_ms = audio
        .and_then(|p| p.get("frame_duration"))
        .and_then(Value::as_u64)
        .unwrap_or(FRAME_MS as u64) as u32;
    Some(ServerHello {
        session_id,
        sample_rate,
        frame_ms,
    })
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ServerHello {
    pub session_id: String,
    pub sample_rate: u32,
    pub frame_ms: u32,
}

pub fn text_field(value: &Value) -> Option<&str> {
    value.get("text").and_then(Value::as_str)
}

pub fn state_field(value: &Value) -> Option<&str> {
    value.get("state").and_then(Value::as_str)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hello_matches_the_reference_shape() {
        let value: Value = serde_json::from_str(&hello_message()).unwrap();
        assert_eq!(value["type"], "hello");
        assert_eq!(value["version"], 1);
        assert_eq!(value["transport"], "websocket");
        assert_eq!(value["audio_params"]["format"], "opus");
        assert_eq!(value["audio_params"]["sample_rate"], 16000);
        assert_eq!(value["audio_params"]["channels"], 1);
        assert_eq!(value["audio_params"]["frame_duration"], 60);
        assert!(value.get("features").is_none());
    }

    #[test]
    fn listen_and_abort_carry_the_session() {
        let listen: Value = serde_json::from_str(&listen_start("abc")).unwrap();
        assert_eq!(listen["type"], "listen");
        assert_eq!(listen["state"], "start");
        assert_eq!(listen["mode"], "auto");
        assert_eq!(listen["session_id"], "abc");
        let abort: Value = serde_json::from_str(&abort("abc")).unwrap();
        assert_eq!(abort["type"], "abort");
        assert!(abort.get("reason").is_none());
    }

    #[test]
    fn authorization_matches_the_firmware_rule() {
        assert_eq!(authorization_value("  "), None);
        assert_eq!(
            authorization_value("token"),
            Some("Bearer token".to_owned())
        );
        assert_eq!(
            authorization_value("Bearer already"),
            Some("Bearer already".to_owned())
        );
    }

    #[test]
    fn server_hello_requires_websocket_and_keeps_audio_defaults() {
        let ok = json!({
            "type": "hello",
            "transport": "websocket",
            "session_id": "s1"
        });
        let parsed = parse_server_hello(&ok).unwrap();
        assert_eq!(parsed.session_id, "s1");
        assert_eq!(parsed.sample_rate, DEFAULT_DOWNLINK_RATE);
        assert_eq!(parsed.frame_ms, FRAME_MS);

        let mqtt = json!({"type": "hello", "transport": "mqtt"});
        assert!(parse_server_hello(&mqtt).is_none());
    }
}
