//! The boot-button state machine from the reference `Application::HandleToggleChatEvent`.
//!
//! One press from idle opens the channel and listens in auto mode. A press while
//! connected (listening or speaking) hangs up and returns the duck's own voice.

use serde_json::Value;

use crate::expression::{parse_emotion, Emotion};
use crate::keywords::{match_keyword, KeywordRule};
use crate::protocol::{self, ServerHello};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    Idle,
    Connecting,
    Listening,
    Speaking,
}

impl Phase {
    /// Compact code for `/system.bobo.phase` telemetry (0..=3).
    pub fn code(self) -> u8 {
        match self {
            Self::Idle => 0,
            Self::Connecting => 1,
            Self::Listening => 2,
            Self::Speaking => 3,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Idle => "idle",
            Self::Connecting => "connecting",
            Self::Listening => "listening",
            Self::Speaking => "speaking",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Effect {
    Send(String),
    /// Microphone uplink. Off while the server is speaking, so the duck does not talk over itself.
    Capture(bool),
    /// Speaker. On for the TTS sentence, off when it ends or the call drops.
    Playback(bool),
    /// STT matched a configured keyword; robotd decides whether the body may run it.
    Keyword(String),
}

pub struct Machine {
    phase: Phase,
    session_id: String,
    server_rate: u32,
    /// After `tts start`, keep the mic open until the first Opus frame. Empty
    /// start/stop pairs (no sentence, no audio) are common late in a call and
    /// must not tear down arecord / Hard-reprobe AHUB.
    mic_open_during_tts: bool,
    /// True until the first downlink packet — session then Capture(false).
    mute_capture_pending: bool,
    /// Last `llm.emotion` from the server; drives sparse head motion while speaking.
    emotion: Emotion,
    /// Set on `tts.sentence_start` so robotd can re-seed one pose per sentence.
    sentence_bump: bool,
    /// STT → action rules. Empty disables keyword hits.
    keywords: Vec<KeywordRule>,
}

impl Machine {
    pub fn new() -> Self {
        Self::with_keywords(Vec::new())
    }

    pub fn with_keywords(keywords: Vec<KeywordRule>) -> Self {
        Self {
            phase: Phase::Idle,
            session_id: String::new(),
            server_rate: protocol::DEFAULT_DOWNLINK_RATE,
            mic_open_during_tts: false,
            mute_capture_pending: false,
            emotion: Emotion::Neutral,
            sentence_bump: false,
            keywords,
        }
    }

    pub fn set_keywords(&mut self, keywords: Vec<KeywordRule>) {
        self.keywords = keywords;
    }

    pub fn phase(&self) -> Phase {
        self.phase
    }

    pub fn emotion(&self) -> Emotion {
        self.emotion
    }

    /// Consume the sentence-start edge (if any).
    pub fn take_sentence_bump(&mut self) -> bool {
        let bump = self.sentence_bump;
        self.sentence_bump = false;
        bump
    }

    pub fn server_rate(&self) -> u32 {
        self.server_rate
    }

    pub fn uplink(&self) -> bool {
        self.phase == Phase::Listening
            || (self.phase == Phase::Speaking && self.mic_open_during_tts)
    }

    /// First TTS Opus frame: mute the mic (exclusive card) before aplay.
    pub fn take_mute_capture_for_tts(&mut self) -> bool {
        if !self.mute_capture_pending {
            return false;
        }
        self.mute_capture_pending = false;
        self.mic_open_during_tts = false;
        true
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
            // Listening or speaking: one press ends the call (web R3 is a latch).
            // Aborting a sentence without hanging up left the latch green while the
            // duck still held the speaker — a second click felt broken.
            Phase::Connecting | Phase::Listening | Phase::Speaking => {
                self.phase = Phase::Idle;
                Press::HangUp
            }
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
                    if let Some(hit) = match_keyword(text, &self.keywords) {
                        tracing::info!(keyword = %hit.needle, action = %hit.action, "关键词命中");
                        return vec![Effect::Keyword(hit.action.clone())];
                    }
                }
                Vec::new()
            }
            Some("llm") => {
                if let Some(raw) = protocol::emotion_field(value) {
                    self.emotion = parse_emotion(raw);
                    tracing::info!(emotion = self.emotion.as_str(), raw, "表情");
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
                // Defer Capture(false) until audio arrives — empty TTS must not
                // stop arecord (board: ASR then Hard probe, no 回答, call dies).
                self.mic_open_during_tts = true;
                self.mute_capture_pending = true;
                vec![Effect::Playback(true)]
            }
            Some("stop") if self.phase == Phase::Speaking => {
                let had_audio = !self.mic_open_during_tts;
                self.phase = Phase::Listening;
                self.mic_open_during_tts = false;
                self.mute_capture_pending = false;
                let mut effects = vec![Effect::Playback(false)];
                effects.push(Effect::Send(protocol::listen_start(&self.session_id)));
                // Only reopen capture if we actually muted it for real TTS.
                if had_audio {
                    effects.push(Effect::Capture(true));
                }
                effects
            }
            Some("sentence_start") => {
                self.sentence_bump = true;
                if let Some(text) = protocol::text_field(value) {
                    tracing::info!(%text, "回答");
                }
                Vec::new()
            }
            _ => Vec::new()
        }
    }

    pub fn on_disconnected(&mut self) -> Vec<Effect> {
        self.phase = Phase::Idle;
        self.session_id.clear();
        self.mic_open_during_tts = false;
        self.mute_capture_pending = false;
        self.emotion = Emotion::Neutral;
        self.sentence_bump = false;
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
        assert!(matches!(&effects[0], Effect::Send(text) if text.contains("\"mode\":\"realtime\"")));
        assert_eq!(effects[1], Effect::Capture(true));

        assert_eq!(machine.on_press(), Press::HangUp);
        assert_eq!(machine.phase(), Phase::Idle);
        assert!(!machine.uplink());
    }

    #[test]
    fn speaking_press_hangs_up_the_call() {
        let mut machine = Machine::new();
        machine.on_press();
        machine.on_server_hello(hello());
        let start = machine.on_json(&json!({"type": "tts", "state": "start"}));
        assert_eq!(machine.phase(), Phase::Speaking);
        // Mic stays up until the first Opus frame.
        assert!(machine.uplink());
        assert_eq!(start, vec![Effect::Playback(true)]);
        assert!(machine.take_mute_capture_for_tts());
        assert!(!machine.uplink());
        assert_eq!(machine.on_press(), Press::HangUp);
        assert_eq!(machine.phase(), Phase::Idle);
    }

    #[test]
    fn empty_tts_does_not_restart_capture() {
        let mut machine = Machine::new();
        machine.on_press();
        machine.on_server_hello(hello());
        machine.on_json(&json!({"type": "tts", "state": "start"}));
        let stop = machine.on_json(&json!({"type": "tts", "state": "stop"}));
        assert_eq!(machine.phase(), Phase::Listening);
        assert_eq!(stop[0], Effect::Playback(false));
        assert!(matches!(&stop[1], Effect::Send(_)));
        assert_eq!(stop.len(), 2, "empty TTS must not Capture(true)");
        assert!(machine.uplink());
    }

    #[test]
    fn tts_with_audio_returns_to_listening_and_reopens_capture() {
        let mut machine = Machine::new();
        machine.on_press();
        machine.on_server_hello(hello());
        machine.on_json(&json!({"type": "tts", "state": "start"}));
        assert!(machine.take_mute_capture_for_tts());
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

    #[test]
    fn llm_emotion_and_sentence_start_drive_expression() {
        let mut machine = Machine::new();
        machine.on_press();
        machine.on_server_hello(hello());
        machine.on_json(&json!({"type": "llm", "emotion": "happy"}));
        assert_eq!(machine.emotion(), Emotion::Happy);
        machine.on_json(&json!({"type": "tts", "state": "sentence_start", "text": "你好"}));
        assert!(machine.take_sentence_bump());
        assert!(!machine.take_sentence_bump());
        machine.on_disconnected();
        assert_eq!(machine.emotion(), Emotion::Neutral);
    }

    #[test]
    fn stt_keyword_emits_action() {
        let mut machine = Machine::with_keywords(vec![
            crate::keywords::KeywordRule::new("点头", "preset:nod"),
        ]);
        machine.on_press();
        machine.on_server_hello(hello());
        let effects = machine.on_json(&json!({"type": "stt", "text": "请点头"}));
        assert_eq!(effects, vec![Effect::Keyword("preset:nod".into())]);
        let miss = machine.on_json(&json!({"type": "stt", "text": "今天天气怎么样"}));
        assert!(miss.is_empty());
    }
}
