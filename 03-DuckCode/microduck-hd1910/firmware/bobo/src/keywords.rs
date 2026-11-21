//! STT keyword → action mapping for BoBo voice.
//!
//! The server returns `{"type":"stt","text":"..."}`. When the transcript contains a
//! configured keyword, the duck may run a preset head gesture or a model skill — gated
//! by robotd so only idle sit/stand responds.

use std::path::Path;
use std::time::Duration;

/// One mapping: substring match → action id.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KeywordRule {
    pub needle: String,
    pub action: String,
}

impl KeywordRule {
    pub fn new(needle: impl Into<String>, action: impl Into<String>) -> Self {
        Self {
            needle: needle.into(),
            action: action.into(),
        }
    }
}

/// Fixed head presets offered in the console dropdown.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PresetGesture {
    /// 摇头晃脑 — soft yaw/roll sway.
    Sway,
    /// 点头 — pitch nod.
    Nod,
    /// 使劲摇头 — bigger, faster yaw shake.
    ShakeHard,
    /// 哈哈大笑 — happy tilt + bob.
    Laugh,
}

impl PresetGesture {
    pub const ALL: [Self; 4] = [Self::Sway, Self::Nod, Self::ShakeHard, Self::Laugh];

    pub fn id(self) -> &'static str {
        match self {
            Self::Sway => "preset:sway",
            Self::Nod => "preset:nod",
            Self::ShakeHard => "preset:shake_hard",
            Self::Laugh => "preset:laugh",
        }
    }

    pub fn label_zh(self) -> &'static str {
        match self {
            Self::Sway => "摇头晃脑",
            Self::Nod => "点头",
            Self::ShakeHard => "使劲摇头",
            Self::Laugh => "哈哈大笑",
        }
    }

    pub fn parse(action: &str) -> Option<Self> {
        match action.trim() {
            "preset:sway" => Some(Self::Sway),
            "preset:nod" => Some(Self::Nod),
            "preset:shake_hard" => Some(Self::ShakeHard),
            "preset:laugh" => Some(Self::Laugh),
            _ => None,
        }
    }

    pub fn duration(self) -> Duration {
        match self {
            Self::Sway => Duration::from_millis(1400),
            Self::Nod => Duration::from_millis(900),
            Self::ShakeHard => Duration::from_millis(1100),
            Self::Laugh => Duration::from_millis(1300),
        }
    }
}

/// First rule whose needle is a non-empty substring of `text` wins.
pub fn match_keyword<'a>(text: &str, rules: &'a [KeywordRule]) -> Option<&'a KeywordRule> {
    let hay = text.trim();
    if hay.is_empty() {
        return None;
    }
    rules.iter().find(|rule| {
        let needle = rule.needle.trim();
        !needle.is_empty() && hay.contains(needle)
    })
}

/// Hard per-axis offset (rad) for keyword presets. Same family as emotion expression.
pub const PRESET_OFFSET_LIMIT: f64 = 0.22;

/// Head offsets for a timed preset clip: `[neck_pitch, head_pitch, head_yaw, head_roll]`.
///
/// `amp` uses the same scale as emotion expression (`1.0` = designed); each axis is then
/// clamped to [`PRESET_OFFSET_LIMIT`].
pub fn preset_offsets(gesture: PresetGesture, elapsed: Duration, amp: f64) -> [f64; 4] {
    let amp = crate::expression::clamp_expression_amp(amp);
    if amp <= 0.0 {
        return [0.0; 4];
    }
    let t = elapsed.as_secs_f64();
    let dur = gesture.duration().as_secs_f64().max(0.01);
    if t >= dur {
        return [0.0; 4];
    }
    // Fade in/out so the clip does not jerk.
    let fade = (t / 0.12).min(1.0).min(((dur - t) / 0.15).max(0.0));
    let pose = match gesture {
        PresetGesture::Sway => {
            let yaw = 0.12 * (t * std::f64::consts::TAU * 1.4).sin();
            let roll = 0.08 * (t * std::f64::consts::TAU * 1.1 + 0.4).sin();
            [0.0, -0.02, yaw, roll]
        }
        PresetGesture::Nod => {
            // Two soft nods.
            let phase = (t * std::f64::consts::PI * 2.2).sin();
            [0.0, 0.10 * phase, 0.0, 0.0]
        }
        PresetGesture::ShakeHard => {
            let yaw = 0.18 * (t * std::f64::consts::TAU * 3.2).sin();
            [0.0, 0.02, yaw, 0.04 * (t * 10.0).sin()]
        }
        PresetGesture::Laugh => {
            let bob = 0.06 * (t * std::f64::consts::TAU * 2.5).sin().abs();
            let roll = 0.10 * (t * std::f64::consts::TAU * 1.6).sin();
            [-0.02, -0.05 - bob * 0.3, 0.03 * (t * 4.0).sin(), roll]
        }
    };
    let mut out = [0.0; 4];
    for i in 0..4 {
        out[i] = (pose[i] * fade * amp).clamp(-PRESET_OFFSET_LIMIT, PRESET_OFFSET_LIMIT);
    }
    out
}

/// Load rules from a JSON sidecar (`{"keywords":[{"match":"...","action":"..."}]}`).
///
/// Also accepts a bare array, and heals the double-encoded JSON string an older
/// console once wrote (a JSON string whose contents are the real object).
pub fn load_json_file(path: &Path) -> Result<Vec<KeywordRule>, String> {
    let raw = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let (rules, healed) = parse_json_healed(&raw)?;
    if healed {
        let canonical = rules_to_json(&rules);
        let tmp = path.with_extension("tmp");
        if std::fs::write(&tmp, format!("{canonical}\n")).is_ok() {
            let _ = std::fs::rename(&tmp, path);
        }
    }
    Ok(rules)
}

pub fn parse_json(raw: &str) -> Result<Vec<KeywordRule>, String> {
    parse_json_healed(raw).map(|(rules, _)| rules)
}

fn parse_json_healed(raw: &str) -> Result<(Vec<KeywordRule>, bool), String> {
    let mut value: serde_json::Value =
        serde_json::from_str(raw).map_err(|e| format!("bobo keywords JSON: {e}"))?;
    let mut healed = false;
    // Older console double-encoded: file was `"{\"keywords\":[...]}"` (a JSON string).
    for _ in 0..2 {
        let Some(nested) = value.as_str() else {
            break;
        };
        value = serde_json::from_str(nested)
            .map_err(|e| format!("bobo keywords JSON (nested): {e}"))?;
        healed = true;
    }
    let list = if let Some(arr) = value.as_array() {
        healed = true; // bare array → rewrite as {"keywords":[...]}
        arr.clone()
    } else if let Some(arr) = value.get("keywords").and_then(|v| v.as_array()) {
        arr.clone()
    } else {
        return Err("bobo keywords JSON needs a keywords array".to_owned());
    };
    let mut rules = Vec::with_capacity(list.len());
    for (i, item) in list.iter().enumerate() {
        let needle = item
            .get("match")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        let action = item
            .get("action")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        if needle.is_empty() || action.is_empty() {
            return Err(format!("keywords[{i}] needs non-empty match and action"));
        }
        rules.push(KeywordRule::new(needle, action));
    }
    Ok((rules, healed))
}

pub fn rules_to_json(rules: &[KeywordRule]) -> String {
    let keywords: Vec<_> = rules
        .iter()
        .map(|r| {
            serde_json::json!({
                "match": r.needle,
                "action": r.action,
            })
        })
        .collect();
    serde_json::to_string_pretty(&serde_json::json!({ "keywords": keywords }))
        .unwrap_or_else(|_| "{\"keywords\":[]}".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn first_substring_wins() {
        let rules = [
            KeywordRule::new("点头", "preset:nod"),
            KeywordRule::new("摇头", "preset:sway"),
        ];
        assert_eq!(
            match_keyword("请点头一下", &rules).map(|r| r.action.as_str()),
            Some("preset:nod")
        );
        assert!(match_keyword("你好", &rules).is_none());
    }

    #[test]
    fn preset_ids_round_trip() {
        for g in PresetGesture::ALL {
            assert_eq!(PresetGesture::parse(g.id()), Some(g));
            assert!(!g.label_zh().is_empty());
        }
    }

    #[test]
    fn json_round_trip() {
        let rules = vec![KeywordRule::new("大笑", "preset:laugh")];
        let parsed = parse_json(&rules_to_json(&rules)).unwrap();
        assert_eq!(parsed, rules);
    }

    #[test]
    fn accepts_double_encoded_and_bare_array() {
        let inner = r#"{"keywords":[{"match":"点头","action":"preset:nod"}]}"#;
        let wrapped = serde_json::to_string(inner).unwrap();
        let (rules, healed) = parse_json_healed(&wrapped).unwrap();
        assert!(healed);
        assert_eq!(rules[0].needle, "点头");
        let bare = r#"[{"match":"摇头","action":"preset:sway"}]"#;
        let (rules, healed) = parse_json_healed(bare).unwrap();
        assert!(healed);
        assert_eq!(rules[0].action, "preset:sway");
    }

    #[test]
    fn nod_moves_pitch_mid_clip() {
        let mid = preset_offsets(PresetGesture::Nod, Duration::from_millis(200), 1.0);
        assert!(mid[1].abs() > 0.02, "nod should move head_pitch: {mid:?}");
    }
}
