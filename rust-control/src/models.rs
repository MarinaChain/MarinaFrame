//! The OpenCode Go models the controller may call, their request settings, and
//! the rate-limit fallback between them.
//!
//! Only models in [`GO_MODELS`] go through OpenCode Go. Claude and GPT models
//! are never allowed here: those go through their own subscriptions.
//! Request settings that differ by model live in the one table below; callers
//! build every chat request through [`payload`].
use crate::provider::Receipt;
use crate::types::MAX_OUTPUT_TOKENS_PER_REQUEST;
use crate::util::Result;
use serde_json::{json, Map, Value};

pub const DEEPSEEK_V4_1_FLASH: &str = "deepseek-v4.1-flash";
pub const CROUTON_ALPHA_FREE: &str = "crouton-alpha-free";

/// How a model is told whether to reason before it answers.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Reasoning {
    /// `"thinking": {"type": "enabled" | "disabled"}` (DeepSeek).
    ThinkingObject,
    /// `"reasoning_effort": <level>`; the `thinking` object is refused with
    /// HTTP 400 (Crouton). The model always reasons internally.
    Effort {
        disabled: &'static str,
        enabled: &'static str,
    },
}

/// The request settings of one allowed model.
#[derive(Clone, Copy, Debug)]
pub struct GoModel {
    pub id: &'static str,
    pub reasoning: Reasoning,
    /// Added to the caller's `max_tokens` (capped at the request limit). A
    /// model whose hidden reasoning shares `max_tokens` needs room for it.
    pub extra_output_tokens: u64,
}

/// The allow-list of OpenCode Go models, with their request settings.
///
/// Crouton (probe 2026-11-09): `thinking` is refused (HTTP 400);
/// `reasoning_effort` accepts minimal..max but not `none`; `response_format`
/// json_object, temperature 0 and `max_tokens` 32,768 are accepted. Without
/// `reasoning_effort`, a 200-token budget ended `length` with no content, so
/// its hidden reasoning shares `max_tokens`. Images: about 2,048 px per side
/// at most (the controller caps images at 2,048 px / 1 Mpx).
pub const GO_MODELS: [GoModel; 2] = [
    GoModel {
        id: DEEPSEEK_V4_1_FLASH,
        reasoning: Reasoning::ThinkingObject,
        extra_output_tokens: 0,
    },
    GoModel {
        id: CROUTON_ALPHA_FREE,
        reasoning: Reasoning::Effort {
            disabled: "low",
            enabled: "high",
        },
        extra_output_tokens: 4096,
    },
];

/// The settings of an allowed model, or `model_not_allowed`.
pub fn settings(id: &str) -> Result<&'static GoModel> {
    GO_MODELS
        .iter()
        .find(|m| m.id == id)
        .ok_or_else(|| "model_not_allowed".into())
}

/// An ordered model list: not empty, allowed models only, no repeats.
pub fn check_list(models: &[&str]) -> Result<()> {
    if models.is_empty() {
        return Err("model_list_empty".into());
    }
    for (index, model) in models.iter().enumerate() {
        settings(model)?;
        if models[..index].contains(model) {
            return Err("model_list_repeats".into());
        }
    }
    Ok(())
}

/// Parse a comma-separated ordered model list (the `--model` option).
pub fn parse_list(text: &str) -> Result<Vec<String>> {
    let models: Vec<String> = text.split(',').map(|m| m.trim().to_string()).collect();
    check_list(&models.iter().map(String::as_str).collect::<Vec<_>>())?;
    Ok(models)
}

/// One chat-completions request body for `model`. `thinking` asks for
/// reasoning before the answer; each model gets it in the form it accepts.
pub fn payload(
    model: &str,
    max_tokens: u64,
    thinking: bool,
    temperature: f64,
    messages: Value,
) -> Result<Value> {
    let settings = settings(model)?;
    let mut body = Map::new();
    body.insert("model".into(), json!(model));
    let max_tokens = (max_tokens + settings.extra_output_tokens).min(MAX_OUTPUT_TOKENS_PER_REQUEST);
    body.insert("max_tokens".into(), json!(max_tokens));
    body.insert("stream".into(), json!(false));
    match settings.reasoning {
        Reasoning::ThinkingObject => {
            let kind = if thinking { "enabled" } else { "disabled" };
            body.insert("thinking".into(), json!({ "type": kind }));
        }
        Reasoning::Effort { disabled, enabled } => {
            let level = if thinking { enabled } else { disabled };
            body.insert("reasoning_effort".into(), json!(level));
        }
    }
    body.insert("temperature".into(), json!(temperature));
    body.insert("response_format".into(), json!({"type": "json_object"}));
    body.insert("messages".into(), messages);
    Ok(Value::Object(body))
}

/// Check that a request body uses an allowed model in that model's form.
pub fn check_payload(body: &Value) -> Result<&'static GoModel> {
    let settings = settings(body["model"].as_str().unwrap_or(""))?;
    let form_ok = match settings.reasoning {
        Reasoning::ThinkingObject => body.get("reasoning_effort").is_none(),
        Reasoning::Effort { .. } => {
            body.get("thinking").is_none() && body["reasoning_effort"].is_string()
        }
    };
    if !form_ok {
        return Err("provider_request_model_settings".into());
    }
    Ok(settings)
}

/// True when OpenCode Go refused the request because the model (or the
/// account's usage window) is rate limited or exhausted. Only these answers
/// move a run to the next model in its list; other failures do not.
pub fn rate_limited(receipt: &Receipt) -> bool {
    receipt.http_status == Some(429)
        || matches!(
            receipt.error_code.as_deref(),
            Some("provider_rate_limited" | "provider_all_credentials_unavailable")
        )
}

/// True when a non-429 error body says the request hit a rate or usage limit
/// (OpenCode Go passes some upstream limits through as other statuses).
pub fn rate_limit_text(body: &[u8]) -> bool {
    let text = String::from_utf8_lossy(body).to_lowercase();
    [
        "rate limit",
        "rate_limit",
        "ratelimit",
        "too many requests",
        "quota",
        "usage limit",
    ]
    .iter()
    .any(|phrase| text.contains(phrase))
}

/// The model after `current` in `models`, if any.
pub fn next<'a>(models: &[&'a str], current: &str) -> Option<&'a str> {
    let index = models.iter().position(|m| *m == current)?;
    models.get(index + 1).copied()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allow_list_has_only_go_drafting_models() {
        assert!(settings(DEEPSEEK_V4_1_FLASH).is_ok());
        assert!(settings(CROUTON_ALPHA_FREE).is_ok());
        for refused in [
            "claude-haiku-5-5",
            "claude-opus-5-5",
            "gpt-6.1-sol",
            "gpt-6-astra",
            "",
        ] {
            assert_eq!(settings(refused).unwrap_err(), "model_not_allowed");
        }
    }

    #[test]
    fn model_lists_are_ordered_allowed_and_without_repeats() {
        assert_eq!(
            parse_list("crouton-alpha-free, deepseek-v4.1-flash").unwrap(),
            [CROUTON_ALPHA_FREE, DEEPSEEK_V4_1_FLASH]
        );
        assert_eq!(
            parse_list("deepseek-v4.1-flash,deepseek-v4.1-flash").unwrap_err(),
            "model_list_repeats"
        );
        assert_eq!(
            parse_list("crouton-alpha-free,claude-haiku-5-5").unwrap_err(),
            "model_not_allowed"
        );
        assert_eq!(check_list(&[]).unwrap_err(), "model_list_empty");
        let list = [CROUTON_ALPHA_FREE, DEEPSEEK_V4_1_FLASH];
        assert_eq!(next(&list, CROUTON_ALPHA_FREE), Some(DEEPSEEK_V4_1_FLASH));
        assert_eq!(next(&list, DEEPSEEK_V4_1_FLASH), None);
    }

    #[test]
    fn each_model_gets_its_reasoning_form() {
        let deepseek = payload(DEEPSEEK_V4_1_FLASH, 1024, false, 0., json!([])).unwrap();
        assert_eq!(deepseek["thinking"], json!({"type":"disabled"}));
        assert!(deepseek.get("reasoning_effort").is_none());
        assert_eq!(deepseek["max_tokens"], 1024);
        let crouton = payload(CROUTON_ALPHA_FREE, 1024, true, 0., json!([])).unwrap();
        assert!(crouton.get("thinking").is_none());
        assert_eq!(crouton["reasoning_effort"], "high");
        assert_eq!(crouton["max_tokens"], 5120);
        let capped = payload(CROUTON_ALPHA_FREE, 32_000, false, 0., json!([])).unwrap();
        assert_eq!(capped["reasoning_effort"], "low");
        assert_eq!(capped["max_tokens"], MAX_OUTPUT_TOKENS_PER_REQUEST);
        assert!(check_payload(&deepseek).is_ok() && check_payload(&crouton).is_ok());
        let mut wrong = crouton.clone();
        wrong["thinking"] = json!({"type":"disabled"});
        assert_eq!(
            check_payload(&wrong).unwrap_err(),
            "provider_request_model_settings"
        );
        wrong["model"] = json!("gpt-6.1-sol");
        assert_eq!(check_payload(&wrong).unwrap_err(), "model_not_allowed");
    }

    #[test]
    fn rate_limit_text_matches_limits_only() {
        assert!(rate_limit_text(
            br#"{"error":{"message":"Rate limit exceeded"}}"#
        ));
        assert!(rate_limit_text(b"monthly usage limit reached"));
        assert!(!rate_limit_text(
            br#"{"error":{"message":"thinking: cannot be represented"}}"#
        ));
    }
}
