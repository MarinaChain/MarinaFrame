//! The models the controller may call, how each is reached (its transport),
//! their request settings, and the rate-limit fallback between them.
//!
//! Two transports exist. OpenCode Go carries the open models (DeepSeek,
//! Crouton). Claude models go through the Claude subscription: the provider
//! worker runs the `claude` CLI in print mode (see `provider::claude_cli`).
//! Claude and GPT models never go through OpenCode Go and never use an API
//! key (founder decision 2026-11-09). Request settings that differ by model
//! live in the one table below; callers build every request through
//! [`payload`].
use crate::provider::Receipt;
use crate::types::{GO_ENDPOINT, MAX_OUTPUT_TOKENS_PER_REQUEST};
use crate::util::Result;
use serde_json::{json, Map, Value};

pub const DEEPSEEK_V4_1_FLASH: &str = "deepseek-v4.1-flash";
pub const CROUTON_ALPHA_FREE: &str = "crouton-alpha-free";
pub const CLAUDE_SONNET_5_5: &str = "claude-sonnet-5-5";

/// The default ordered model list of the app and of development rounds:
/// Claude Sonnet 5.5 drafts; only a subscription rate-limit or usage-limit
/// answer moves a run to Crouton, then DeepSeek (founder decision 2026-11-09).
pub const DEFAULT_MODELS: [&str; 3] = [CLAUDE_SONNET_5_5, CROUTON_ALPHA_FREE, DEEPSEEK_V4_1_FLASH];

/// The receipt endpoint of the Claude subscription transport. It names the
/// route, not a URL: the `claude` CLI holds the subscription login.
pub const CLAUDE_CLI_ENDPOINT: &str = "claude-cli:print:subscription";

/// How a request reaches its model.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Transport {
    /// HTTPS chat completions at [`GO_ENDPOINT`] with an OpenCode Go key.
    OpencodeGo,
    /// The `claude` CLI in print mode, logged in on the Claude subscription.
    ClaudeSubscription,
}
impl Transport {
    /// The endpoint every receipt of this transport records.
    pub fn endpoint(self) -> &'static str {
        match self {
            Transport::OpencodeGo => GO_ENDPOINT,
            Transport::ClaudeSubscription => CLAUDE_CLI_ENDPOINT,
        }
    }
}

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
    /// `"effort": <level>`, passed to the `claude` CLI as `--effort`.
    CliEffort {
        disabled: &'static str,
        enabled: &'static str,
    },
}

/// The request settings of one allowed model.
#[derive(Clone, Copy, Debug)]
pub struct ModelSettings {
    pub id: &'static str,
    pub transport: Transport,
    pub reasoning: Reasoning,
    /// Added to the caller's `max_tokens` (capped at the request limit). A
    /// model whose hidden reasoning shares `max_tokens` needs room for it.
    pub extra_output_tokens: u64,
    /// The longest image side sent to this model, in pixels.
    pub max_image_side_px: u32,
    /// The most pixels of one image sent to this model.
    pub max_image_pixels: u64,
    /// The request carries a sampling temperature.
    pub temperature: bool,
}

/// The harness cap of every image (`provider::check_png`): 2,048 px per side
/// and 1 Mpx. No model gets more than this.
pub const HARNESS_IMAGE_SIDE_PX: u32 = 2048;
pub const HARNESS_IMAGE_PIXELS: u64 = 1_048_576;

/// The allow-list of models, with their transport and request settings.
///
/// Crouton (probe 2026-11-09): `thinking` is refused (HTTP 400);
/// `reasoning_effort` accepts minimal..max but not `none`; `response_format`
/// json_object, temperature 0 and `max_tokens` 32,768 are accepted. Without
/// `reasoning_effort`, a 200-token budget ended `length` with no content, so
/// its hidden reasoning shares `max_tokens`. Images: about 2,048 px per side
/// at most. DeepSeek (work/vision-probe): images above 2,048 px are
/// downscaled.
///
/// Claude Sonnet 5.5 (probe 2026-11-09, work/claude-vision-probe): image
/// tokens grow with the area up to about 3.75 Mpx (2,048 x 512 costs 1,342
/// tokens, 1,568^2 costs 3,139, 2,048^2 and 2,576^2 both cost 4,809), so it
/// does not downsample at 1,568 px, and 9 px text on a 2,048 px sheet stayed
/// readable. Every image the harness sends (at most 2,048 px and 1 Mpx)
/// reaches it at full size. The CLI has no temperature option.
pub const MODELS: [ModelSettings; 3] = [
    ModelSettings {
        id: DEEPSEEK_V4_1_FLASH,
        transport: Transport::OpencodeGo,
        reasoning: Reasoning::ThinkingObject,
        extra_output_tokens: 0,
        max_image_side_px: HARNESS_IMAGE_SIDE_PX,
        max_image_pixels: HARNESS_IMAGE_PIXELS,
        temperature: true,
    },
    ModelSettings {
        id: CROUTON_ALPHA_FREE,
        transport: Transport::OpencodeGo,
        reasoning: Reasoning::Effort {
            disabled: "low",
            enabled: "high",
        },
        extra_output_tokens: 4096,
        max_image_side_px: HARNESS_IMAGE_SIDE_PX,
        max_image_pixels: HARNESS_IMAGE_PIXELS,
        temperature: true,
    },
    ModelSettings {
        id: CLAUDE_SONNET_5_5,
        transport: Transport::ClaudeSubscription,
        reasoning: Reasoning::CliEffort {
            disabled: "low",
            enabled: "high",
        },
        extra_output_tokens: 0,
        max_image_side_px: HARNESS_IMAGE_SIDE_PX,
        max_image_pixels: HARNESS_IMAGE_PIXELS,
        temperature: false,
    },
];

/// True for a Claude or GPT model id. These go through their subscriptions,
/// never through OpenCode Go.
pub fn subscription_family(id: &str) -> bool {
    id.starts_with("claude-") || id.starts_with("gpt-")
}

/// The settings of an allowed model, or `model_not_allowed`. A Claude or GPT
/// model on the OpenCode Go transport is never allowed.
pub fn settings(id: &str) -> Result<&'static ModelSettings> {
    MODELS
        .iter()
        .find(|m| m.id == id)
        .filter(|m| !(subscription_family(m.id) && m.transport == Transport::OpencodeGo))
        .ok_or_else(|| "model_not_allowed".into())
}

/// The receipt endpoint of an allowed model's transport.
pub fn endpoint(id: &str) -> Result<&'static str> {
    Ok(settings(id)?.transport.endpoint())
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

/// One request body for `model`, in chat-completions form. `thinking` asks
/// for reasoning before the answer; each model gets it in the form it
/// accepts. The Claude subscription transport turns this body into `claude`
/// CLI arguments and one stream-json user message (`provider::claude_cli`).
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
        Reasoning::CliEffort { disabled, enabled } => {
            let level = if thinking { enabled } else { disabled };
            body.insert("effort".into(), json!(level));
        }
    }
    if settings.temperature {
        body.insert("temperature".into(), json!(temperature));
    }
    if settings.transport == Transport::OpencodeGo {
        body.insert("response_format".into(), json!({"type": "json_object"}));
    }
    body.insert("messages".into(), messages);
    Ok(Value::Object(body))
}

/// Check that a request body uses an allowed model in that model's form.
pub fn check_payload(body: &Value) -> Result<&'static ModelSettings> {
    let settings = settings(body["model"].as_str().unwrap_or(""))?;
    let form_ok = match settings.reasoning {
        Reasoning::ThinkingObject => {
            body.get("reasoning_effort").is_none() && body.get("effort").is_none()
        }
        Reasoning::Effort { .. } => {
            body.get("thinking").is_none()
                && body.get("effort").is_none()
                && body["reasoning_effort"].is_string()
        }
        Reasoning::CliEffort { disabled, enabled } => {
            let effort = body["effort"].as_str().unwrap_or("");
            body.get("thinking").is_none()
                && body.get("reasoning_effort").is_none()
                && body.get("response_format").is_none()
                && body.get("temperature").is_none()
                && (effort == disabled || effort == enabled)
        }
    };
    if !form_ok {
        return Err("provider_request_model_settings".into());
    }
    Ok(settings)
}

/// True when the transport refused the request because the model (or the
/// account's or subscription's usage window) is rate limited or exhausted.
/// Only these answers move a run to the next model in its list; other
/// failures do not.
pub fn rate_limited(receipt: &Receipt) -> bool {
    receipt.http_status == Some(429)
        || matches!(
            receipt.error_code.as_deref(),
            Some("provider_rate_limited" | "provider_all_credentials_unavailable")
        )
}

/// True when an error body says the request hit a rate or usage limit
/// (OpenCode Go passes some upstream limits through as other statuses; the
/// `claude` CLI reports a subscription limit as an error result text).
pub fn rate_limit_text(body: &[u8]) -> bool {
    let text = String::from_utf8_lossy(body).to_lowercase();
    [
        "rate limit",
        "rate_limit",
        "ratelimit",
        "too many requests",
        "quota",
        "usage limit",
        "hit your limit",
        "limit reached",
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
    fn allow_list_has_only_drafting_models() {
        assert!(settings(DEEPSEEK_V4_1_FLASH).is_ok());
        assert!(settings(CROUTON_ALPHA_FREE).is_ok());
        assert_eq!(
            settings(CLAUDE_SONNET_5_5).unwrap().transport,
            Transport::ClaudeSubscription
        );
        assert_eq!(endpoint(CLAUDE_SONNET_5_5).unwrap(), CLAUDE_CLI_ENDPOINT);
        assert_eq!(endpoint(DEEPSEEK_V4_1_FLASH).unwrap(), GO_ENDPOINT);
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
    fn claude_and_gpt_never_go_through_opencode_go() {
        for model in MODELS {
            if subscription_family(model.id) {
                assert_ne!(model.transport, Transport::OpencodeGo, "{}", model.id);
            }
            assert!(model.max_image_side_px <= HARNESS_IMAGE_SIDE_PX);
            assert!(model.max_image_pixels <= HARNESS_IMAGE_PIXELS);
        }
        assert!(check_list(&DEFAULT_MODELS).is_ok());
        assert_eq!(DEFAULT_MODELS[0], CLAUDE_SONNET_5_5);
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
        assert_eq!(
            next(&DEFAULT_MODELS, CLAUDE_SONNET_5_5),
            Some(CROUTON_ALPHA_FREE)
        );
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
    fn claude_payload_uses_cli_effort_without_go_fields() {
        let sonnet = payload(CLAUDE_SONNET_5_5, 2048, false, 0.4, json!([])).unwrap();
        assert_eq!(sonnet["effort"], "low");
        assert_eq!(sonnet["max_tokens"], 2048);
        for absent in [
            "thinking",
            "reasoning_effort",
            "temperature",
            "response_format",
        ] {
            assert!(sonnet.get(absent).is_none(), "{absent}");
        }
        assert!(check_payload(&sonnet).is_ok());
        let thinking = payload(CLAUDE_SONNET_5_5, 2048, true, 0., json!([])).unwrap();
        assert_eq!(thinking["effort"], "high");
        let mut wrong = sonnet.clone();
        wrong["response_format"] = json!({"type":"json_object"});
        assert_eq!(
            check_payload(&wrong).unwrap_err(),
            "provider_request_model_settings"
        );
        let mut wrong = sonnet;
        wrong["effort"] = json!("max");
        assert!(check_payload(&wrong).is_err());
    }

    #[test]
    fn rate_limit_text_matches_limits_only() {
        assert!(rate_limit_text(
            br#"{"error":{"message":"Rate limit exceeded"}}"#
        ));
        assert!(rate_limit_text(b"monthly usage limit reached"));
        assert!(rate_limit_text(
            "You\u{2019}ve hit your limit \u{b7} resets 3pm".as_bytes()
        ));
        assert!(!rate_limit_text(
            br#"{"error":{"message":"thinking: cannot be represented"}}"#
        ));
    }
}
