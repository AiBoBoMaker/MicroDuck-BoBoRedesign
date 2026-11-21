//! Bobo, the duck's voice call.
//!
//! The reference device opens a socket, says hello, then streams 60 ms Opus frames while
//! it listens and plays the server's Opus while it speaks. This crate is that client.
//! The gamepad only decides *when* — see `padd`, which raises `robot.voice` on the two
//! buttons nothing else uses.

mod audio;
mod expression;
mod identity;
mod keywords;
mod machine;
mod ota;
mod protocol;
mod session;

pub use expression::{
    clamp_expression_amp, head_offsets, parse_emotion, Emotion, EXPRESSION_AMP_MAX,
    EXPRESSION_OFFSET_LIMIT,
};
pub use identity::device_id;
pub use keywords::{
    load_json_file, match_keyword, parse_json, preset_offsets, rules_to_json, KeywordRule,
    PresetGesture, PRESET_OFFSET_LIMIT,
};
pub use machine::Phase;
pub use session::{phase_code, run, SessionConfig};
