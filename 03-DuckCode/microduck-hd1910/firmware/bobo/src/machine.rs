//! The boot-button state machine from the reference `Application::HandleToggleChatEvent`.
//!
//! One press from idle opens the channel and listens in auto mode. A press while the
//! server is speaking aborts that sentence. A press while listening hangs up.

use serde_json::Value;

use crate::protocol::{self, ServerHello};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    Idle,
    Connecting,
    Listening,
    Speaking,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Effect {
    Send(String),
    /// Microphone uplink. Off while the server is speaking, so the duck does not talk over itself.
    Capture(bool),
    /// Speaker. On for the TTS sentence, off when it ends or the call drops.
    Playback(bool),
}

pub struct Machine {
    phase: Phase,
    session_id: String,
    server_rate: u32,
}

impl Machine {
    pub fn new() -> Self {
        Self {
            phase: Phase::Idle,
            session_id: String::new(),
            server_rate: protocol::DEFAULT_DOWNLINK_RATE,
        }
    }

    pub fn phase(&self) -> Phase {
        self.phase
    }

    pub fn server_rate(&self) -> u32 {
        self.server_rate
    }

    pub fn uplink(&self) -> bool {
        self.phase == Phase::Listening
    }

    /// What a button press does in the current phase. `None` only while idle, and the
    /// caller is the one that opens the socket — this returns the effects *after* the
    /// decision, and idle's decision is "caller should connect".
    pub fn on_press(&mut self) -> Press {
        match self.phase {
            Phase::Idle => {
                self.phase = Phase::Connecting;
                Press::Connect
            }
            Phase::Connecting | Phase::Listening => {
                self.phase = Phase::Idle;
                Press::HangUp
            }
            Phase::Speaking => Press::Abort(vec![Effect::Send(protocol::abort(&self.session_id))]),
        }
    }

    /// Server hello accepted. Moves to listening and asks the server to start.
    pub fn on_server_hello(&mut self, hello: ServerHello) -> Vec<Effect> {
        self.session_id = hello.session_id;
        if hello.sample_rate > 0 {
            self.server_rate = hello.sample_rate;
        }
        self.phase = Phase::Listening;
        vec![
            Effect::Send(protocol::listen_start(&self.session_id)),
            Effect::Capture(true),
        ]
    }

    pub fn on_json(&mut self, value: &Value) -> Vec<Effect> {
        match protocol::message_type(value) {
            Some("tts") => self.on_tts(value),
            Some("stt") => {
                if let Some(text) = protocol::text_field(value) {
                    tracing::info!(%text, "语音识别");
                }
                Vec::new()
            }
            Some("llm") => {
                if let Some(text) = protocol::text_field(value) {
                    tracing::info!(%text, "表情");
                }
                Vec::new()
            }
            Some("hello") => Vec::new(),
            Some(other) => {
                tracing::debug!(kind = other, "ignored server message");
                Vec::new()
            }
            None => {
                tracing::warn!(payload = %value, "server message has no type");
                Vec::new()
            }
        }
    }

    fn on_tts(&mut self, value: &Value) -> Vec<Effect> {
        match protocol::state_field(value) {
            Some("start") => {
                self.phase = Phase::Speaking;
                vec![Effect::Capture(false), Effect::Playback(true)]
            }
            Some("stop") if self.phase == Phase::Speaking => {
                self.phase = Phase::Listening;
                vec![
                    Effect::Playback(false),
                    Effect::Send(protocol::listen_start(&self.session_id)),
                    Effect::Capture(true),
                ]
            }
            Some("sentence_start") => {
                if let Some(text) = protocol::text_field(value) {
                    tracing::info!(%text, "回答");
                }
                Vec::new()
            }
            _ => Vec::new(),
        }
    }

    pub fn on_disconnected(&mut self) -> Vec<Effect> {
        self.phase = Phase::Idle;
        self.session_id.clear();
        vec![Effect::Capture(false), Effect::Playback(false)]
    }
}

impl Default for Machine {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Press {
    Connect,
    HangUp,
    Abort(Vec<Effect>),
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn hello() -> ServerHello {
        ServerHello {
            session_id: "s".into(),
            sample_rate: 24000,
            frame_ms: 60,
        }
    }

    #[test]
    fn a_press_connects_then_listens_then_hangs_up() {
        let mut machine = Machine::new();
        assert_eq!(machine.on_press(), Press::Connect);
        assert_eq!(machine.phase(), Phase::Connecting);
        let effects = machine.on_server_hello(hello());
        assert_eq!(machine.phase(), Phase::Listening);
        assert!(machine.uplink());
        assert_eq!(machine.server_rate(), 24000);
        assert!(matches!(&effects[0], Effect::Send(text) if text.contains("\"mode\":\"auto\"")));
        assert_eq!(effects[1], Effect::Capture(true));

        assert_eq!(machine.on_press(), Press::HangUp);
        assert_eq!(machine.phase(), Phase::Idle);
        assert!(!machine.uplink());
    }

    #[test]
    fn speaking_is_aborted_and_then_listens_again_in_auto_mode() {
        let mut machine = Machine::new();
        machine.on_press();
        machine.on_server_hello(hello());
        let start = machine.on_json(&json!({"type": "tts", "state": "start"}));
        assert_eq!(machine.phase(), Phase::Speaking);
        assert!(!machine.uplink());
        assert_eq!(
            start,
            vec![Effect::Capture(false), Effect::Playback(true)]
        );
        assert!(matches!(machine.on_press(), Press::Abort(_)));
        assert_eq!(machine.phase(), Phase::Speaking);

        let stop = machine.on_json(&json!({"type": "tts", "state": "stop"}));
        assert_eq!(machine.phase(), Phase::Listening);
        assert_eq!(stop[0], Effect::Playback(false));
        assert!(matches!(&stop[1], Effect::Send(_)));
        assert_eq!(stop[2], Effect::Capture(true));
    }

    #[test]
    fn a_press_during_connect_cancels() {
        let mut machine = Machine::new();
        machine.on_press();
        assert_eq!(machine.on_press(), Press::HangUp);
        assert_eq!(machine.phase(), Phase::Idle);
    }

    #[test]
    fn a_dropped_socket_returns_to_idle() {
        let mut machine = Machine::new();
        machine.on_press();
        machine.on_server_hello(hello());
        let effects = machine.on_disconnected();
        assert_eq!(machine.phase(), Phase::Idle);
        assert_eq!(
            effects,
            vec![Effect::Capture(false), Effect::Playback(false)]
        );
    }
}
