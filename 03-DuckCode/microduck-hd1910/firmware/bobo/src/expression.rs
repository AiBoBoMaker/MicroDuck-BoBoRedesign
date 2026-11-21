//! Sparse head expression while the duck is speaking.
//!
//! The server sends `{"type":"llm","emotion":"happy"}`. One sentence keeps one pose seed;
//! dynamic gestures (nods, tilts) are rate-limited so the head does not chatter.
//!
//! Per-axis offsets are hard-clamped to [`EXPRESSION_OFFSET_LIMIT`] so a high user amp
//! cannot push past the designed servo-safe range.

use std::time::Duration;

/// Hard per-axis head offset (rad) for emotion expression. Console amp cannot exceed this.
pub const EXPRESSION_OFFSET_LIMIT: f64 = 0.18;

/// Max `expression_amp` scale (`1.0` = designed amplitudes). Higher only saturates the limit sooner.
pub const EXPRESSION_AMP_MAX: f64 = 2.0;

/// Clamp a user/config amp into the supported range.
pub fn clamp_expression_amp(amp: f64) -> f64 {
    if amp.is_finite() {
        amp.clamp(0.0, EXPRESSION_AMP_MAX)
    } else {
        1.0
    }
}

/// Compact code shared with robotd / console telemetry (`0..=5`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum Emotion {
    Neutral = 0,
    Happy = 1,
    Angry = 2,
    Sad = 3,
    Surprised = 4,
    Thinking = 5,
}

impl Emotion {
    pub fn code(self) -> u8 {
        self as u8
    }

    pub fn from_code(code: u8) -> Self {
        match code {
            1 => Self::Happy,
            2 => Self::Angry,
            3 => Self::Sad,
            4 => Self::Surprised,
            5 => Self::Thinking,
            _ => Self::Neutral,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Neutral => "neutral",
            Self::Happy => "happy",
            Self::Angry => "angry",
            Self::Sad => "sad",
            Self::Surprised => "surprised",
            Self::Thinking => "thinking",
        }
    }
}

/// Map a server emotion name (or emoji-ish alias) to a compact code.
pub fn parse_emotion(raw: &str) -> Emotion {
    let s = raw.trim();
    if s.is_empty() {
        return Emotion::Neutral;
    }
    let lower = s.to_ascii_lowercase();
    match lower.as_str() {
        "happy" | "joy" | "laughing" | "laugh" | "smile" | "☺️" | "😊" | "😄" | "😆" | "🙂" => {
            Emotion::Happy
        }
        "angry" | "mad" | "annoyed" | "confused" | "anger" | "😠" | "😡" | "😤" | "🤬" => {
            Emotion::Angry
        }
        "sad" | "crying" | "cry" | "sorrow" | "unhappy" | "😢" | "😭" | "☹️" | "🙁" => Emotion::Sad,
        "surprised" | "shock" | "shocked" | "wow" | "😮" | "😲" | "😯" => Emotion::Surprised,
        "thinking" | "think" | "curious" | "neutral" | "calm" | "relaxed" | "😶" | "🤔" | "😐" => {
            Emotion::Thinking
        }
        _ => Emotion::Neutral,
    }
}

/// Head offsets in radians: `[neck_pitch, head_pitch, head_yaw, head_roll]`.
///
/// Pitch sign matches chorale / `robot.look`: **negative is up**. `amp` scales the whole
/// family (`1.0` = designed; each axis is then clamped to [`EXPRESSION_OFFSET_LIMIT`]).
pub fn head_offsets(emotion: Emotion, seed: u32, elapsed: Duration, amp: f64) -> [f64; 4] {
    let amp = clamp_expression_amp(amp);
    if amp <= 0.0 {
        return [0.0; 4];
    }
    let t = elapsed.as_secs_f64();
    let tilt_yaw = 0.055 * amp * signed(seed, 1);
    let tilt_roll = 0.075 * amp * signed(seed, 2);

    let mut pose = match emotion {
        Emotion::Happy => [
            0.0,
            -0.045 * amp, // slight look-up
            tilt_yaw,
            tilt_roll, // random neck lean
        ],
        Emotion::Angry => [
            0.02 * amp,
            0.035 * amp, // slight lean-in
            0.02 * amp * signed(seed, 3),
            0.0,
        ],
        Emotion::Sad => [
            0.04 * amp,
            0.10 * amp, // look down
            0.02 * amp * signed(seed, 4),
            0.0,
        ],
        Emotion::Surprised => [
            -0.02 * amp,
            -0.09 * amp, // look up
            0.0,
            0.0,
        ],
        Emotion::Thinking | Emotion::Neutral => {
            // Slow, tiny yaw drift — almost still.
            let drift = 0.025 * amp * (t * 0.35 + seed as f64 * 0.01).sin();
            [0.0, 0.01 * amp, drift, 0.0]
        }
    };

    // Sparse dynamic gestures (at most ~one every cooldown).
    const COOLDOWN_S: f64 = 2.0;
    let slot = (t / COOLDOWN_S).floor() as u32;
    let local = t - slot as f64 * COOLDOWN_S;
    let allow = unit(seed, slot.wrapping_add(11)) > 0.45; // ~55% of windows skip
    if allow {
        match emotion {
            Emotion::Angry if local < 0.22 => {
                // Quick nod pulse.
                let envelope = (local * std::f64::consts::PI / 0.22).sin();
                pose[1] += 0.09 * amp * envelope;
            }
            Emotion::Happy if local < 0.35 => {
                // Soft side sway once.
                let envelope = (local * std::f64::consts::PI / 0.35).sin();
                pose[3] += 0.04 * amp * envelope * signed(seed, 5).signum().max(0.3);
            }
            Emotion::Sad if local < 0.4 => {
                // Almost nothing — a tiny extra dip.
                let envelope = (local * std::f64::consts::PI / 0.4).sin();
                pose[1] += 0.02 * amp * envelope;
            }
            Emotion::Surprised if slot == 0 && local < 0.25 => {
                let envelope = (local * std::f64::consts::PI / 0.25).sin();
                pose[1] += -0.03 * amp * envelope;
            }
            _ => {}
        }
    }

    for v in &mut pose {
        *v = v.clamp(-EXPRESSION_OFFSET_LIMIT, EXPRESSION_OFFSET_LIMIT);
    }
    pose
}

fn unit(seed: u32, lane: u32) -> f64 {
    let mut x = seed
        .wrapping_mul(0x9E37_79B9)
        .wrapping_add(lane.wrapping_mul(0x85EB_CA6B));
    x ^= x >> 16;
    x = x.wrapping_mul(0x7FEB_352D);
    x ^= x >> 15;
    (x as f64) / (u32::MAX as f64)
}

fn signed(seed: u32, lane: u32) -> f64 {
    unit(seed, lane) * 2.0 - 1.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_common_names_and_aliases() {
        assert_eq!(parse_emotion("happy"), Emotion::Happy);
        assert_eq!(parse_emotion("CRYING"), Emotion::Sad);
        assert_eq!(parse_emotion("😠"), Emotion::Angry);
        assert_eq!(parse_emotion("unknown-xyz"), Emotion::Neutral);
    }

    #[test]
    fn codes_round_trip() {
        for code in 0..=5 {
            assert_eq!(Emotion::from_code(code).code(), code);
        }
    }

    #[test]
    fn sad_looks_down_happy_tilts() {
        let sad = head_offsets(Emotion::Sad, 7, Duration::from_millis(100), 1.0);
        assert!(sad[1] > 0.05, "sad head_pitch should be down (+): {sad:?}");
        let happy = head_offsets(Emotion::Happy, 3, Duration::from_millis(100), 1.0);
        assert!(happy[1] < 0.0, "happy looks up (−): {happy:?}");
        assert!(
            happy[2].abs() > 0.02 || happy[3].abs() > 0.02,
            "happy tilts yaw/roll: {happy:?}"
        );
    }

    #[test]
    fn amp_zero_is_still() {
        assert_eq!(
            head_offsets(Emotion::Angry, 1, Duration::from_secs(1), 0.0),
            [0.0; 4]
        );
    }

    #[test]
    fn angry_nod_is_sparse_not_continuous() {
        let a = head_offsets(Emotion::Angry, 42, Duration::from_millis(50), 1.0);
        let b = head_offsets(Emotion::Angry, 42, Duration::from_millis(800), 1.0);
        // Mid-cooldown window often has no pulse; values must stay bounded either way.
        for p in [a, b] {
            for v in p {
                assert!(v.abs() <= EXPRESSION_OFFSET_LIMIT);
            }
        }
    }

    #[test]
    fn amp_above_max_still_respects_servo_limit() {
        let pose = head_offsets(Emotion::Sad, 7, Duration::from_millis(100), 99.0);
        for v in pose {
            assert!(v.abs() <= EXPRESSION_OFFSET_LIMIT + 1e-9);
        }
        assert_eq!(clamp_expression_amp(99.0), EXPRESSION_AMP_MAX);
    }
}
