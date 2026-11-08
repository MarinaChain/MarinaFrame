//! OpenCode Go usage meters per configured key slot, for the Settings page.
//!
//! The provider worker picks, before each model request, the key whose highest
//! meter (rolling, weekly, monthly) is lowest (`credentials::select` in
//! rust-control). This module reads the same meters with the same request
//! (`GET /zen/go/v1/usage`, bearer key, same User-Agent, bounded answer that must
//! not echo the key) and applies the same rule, so Settings can say which slot
//! the next run will use. It runs only when the person asks; there is no timer.
//!
//! No key leaves this module: results carry the slot number only.
use crate::model_keys::{self, KeySource};
use marinaframe_control::provider::credentials::{self, USAGE_ENDPOINT};
use serde::Serialize;
use serde_json::Value;
use std::io::Read;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

/// The meters OpenCode Go reports, in the order the page shows them.
const WINDOWS: [&str; 3] = ["rolling", "weekly", "monthly"];
/// Same value as the provider worker's usage request (rust-control provider.rs).
const USER_AGENT: &str = "MarinaFrame/0.4 Rust control plane";
/// Same bound as the provider worker.
const MAX_USAGE_RESPONSE_BYTES: usize = 65_536;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(15);
/// A meter at or above this percent is "near its limit" (the page shows it in amber).
pub const NEAR_LIMIT_PERCENT: f64 = 90.0;

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct UsageMeter {
    /// rolling, weekly or monthly.
    pub window: String,
    pub percent: Option<f64>,
    /// The provider's status word; "ok" when the meter can be used.
    pub status: Option<String>,
    /// When the meter resets, as the provider gave it (an ISO time or a number).
    pub resets_at: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct KeyUsage {
    /// 1-based key slot. Never the key.
    pub slot: u8,
    pub meters: Vec<UsageMeter>,
    /// The highest meter when every meter is ok and below 100 %; None otherwise.
    pub highest_percent: Option<f64>,
    /// True when the worker's rule would accept this key now.
    pub usable: bool,
    /// Why the meters could not be read, in plain words.
    pub error: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct ModelUsage {
    /// environment or key_file; None when no key is configured.
    pub key_source: Option<String>,
    pub slots: Vec<KeyUsage>,
    /// The slot the next model request would use, by the worker's rule.
    pub next_slot: Option<u8>,
    /// A plain warning when every key is near or at a limit, or none could be checked.
    pub warning: Option<String>,
    pub checked_ms: u64,
}

/// Read every configured key's meters now.
pub fn check_usage() -> ModelUsage {
    let (source, keys) = model_keys::configured_keys();
    let client = reqwest::blocking::Client::builder()
        .timeout(REQUEST_TIMEOUT)
        .build();
    let slots = keys
        .iter()
        .map(|(slot, key)| {
            let body = match &client {
                Ok(client) => read_usage(client, key),
                Err(_) => Err(UsageError::Transport),
            };
            key_usage(*slot, body)
        })
        .collect();
    summarize(source, slots, now_ms())
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_millis() as u64)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum UsageError {
    Transport,
    Refused(u16),
    Rejected,
}

impl UsageError {
    fn message(self) -> String {
        match self {
            Self::Transport => "Could not reach OpenCode. Check the network and try again.".into(),
            Self::Refused(401 | 403) => "OpenCode refused this key.".into(),
            Self::Refused(status) => format!("OpenCode did not give the usage (HTTP {status})."),
            Self::Rejected => "The usage answer could not be read.".into(),
        }
    }
}

/// One usage GET, as the provider worker makes it.
fn read_usage(client: &reqwest::blocking::Client, key: &str) -> Result<Value, UsageError> {
    let response = client
        .get(USAGE_ENDPOINT)
        .bearer_auth(key)
        .header("Accept", "application/json")
        .header("User-Agent", USER_AGENT)
        .send()
        .map_err(|_| UsageError::Transport)?;
    let status = response.status().as_u16();
    if status != 200 {
        return Err(UsageError::Refused(status));
    }
    let mut bytes = vec![];
    response
        .take(MAX_USAGE_RESPONSE_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| UsageError::Transport)?;
    if bytes.len() > MAX_USAGE_RESPONSE_BYTES || contains(&bytes, key.as_bytes()) {
        return Err(UsageError::Rejected);
    }
    marinaframe_control::util::strict_value(&bytes, MAX_USAGE_RESPONSE_BYTES)
        .map_err(|_| UsageError::Rejected)
}

fn contains(haystack: &[u8], needle: &[u8]) -> bool {
    !needle.is_empty() && haystack.windows(needle.len()).any(|w| w == needle)
}

fn meters(body: &Value) -> Vec<UsageMeter> {
    WINDOWS
        .iter()
        .map(|window| {
            let meter = &body["usage"][*window];
            let resets_at = match &meter["resetsAt"] {
                Value::String(text) => Some(text.chars().take(64).collect()),
                Value::Number(number) => Some(number.to_string()),
                _ => None,
            };
            UsageMeter {
                window: (*window).to_string(),
                percent: meter["percent"].as_f64().filter(|p| p.is_finite()),
                status: meter["status"]
                    .as_str()
                    .map(|s| s.chars().take(32).collect()),
                resets_at,
            }
        })
        .collect()
}

fn key_usage(slot: u8, body: Result<Value, UsageError>) -> KeyUsage {
    match body {
        Ok(body) => {
            // The worker's own rule decides whether this key can be used.
            let highest_percent = credentials::highest_usage_percent(&body);
            KeyUsage {
                slot,
                meters: meters(&body),
                highest_percent,
                usable: highest_percent.is_some(),
                error: None,
            }
        }
        Err(error) => KeyUsage {
            slot,
            meters: vec![],
            highest_percent: None,
            usable: false,
            error: Some(error.message()),
        },
    }
}

/// The next slot and the warning, by the worker's rule: one key is used without
/// a usage read; with more, the usable key with the lowest highest meter, ties
/// to the lower slot.
fn summarize(source: Option<KeySource>, slots: Vec<KeyUsage>, checked_ms: u64) -> ModelUsage {
    let next_slot = if slots.len() == 1 {
        Some(slots[0].slot)
    } else {
        slots
            .iter()
            .filter_map(|s| s.highest_percent.map(|p| (s.slot, p)))
            .fold(
                None,
                |best: Option<(u8, f64)>, (slot, percent)| match best {
                    Some((_, lowest)) if lowest <= percent => best,
                    _ => Some((slot, percent)),
                },
            )
            .map(|(slot, _)| slot)
    };
    let usable: Vec<f64> = slots.iter().filter_map(|s| s.highest_percent).collect();
    let warning = if slots.is_empty() {
        None
    } else if usable.is_empty() {
        Some(if slots.len() == 1 {
            "This key is at a limit or could not be checked. A run may stop until a meter resets."
                .to_string()
        } else {
            "Every key is at a limit or could not be checked. New runs cannot get a model answer until a meter resets.".to_string()
        })
    } else if usable.iter().all(|p| *p >= NEAR_LIMIT_PERCENT) {
        Some(format!(
            "Every usable key is near a limit ({NEAR_LIMIT_PERCENT:.0}% or more). A long run may stop when a meter reaches 100%."
        ))
    } else {
        None
    };
    ModelUsage {
        key_source: source.map(|s| match s {
            KeySource::Environment => "environment".to_string(),
            KeySource::KeyFile => "key_file".to_string(),
        }),
        slots,
        next_slot,
        warning,
        checked_ms,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn body(rolling: f64, weekly: f64, monthly: f64) -> Value {
        let meter =
            |p: f64| json!({"status": "ok", "percent": p, "resetsAt": "2099-01-01T00:00:00Z"});
        json!({"usage": {"rolling": meter(rolling), "weekly": meter(weekly), "monthly": meter(monthly)}})
    }

    fn usage(slots: Vec<KeyUsage>) -> ModelUsage {
        summarize(Some(KeySource::KeyFile), slots, 1)
    }

    #[test]
    fn meters_are_read_in_page_order_with_their_reset_time() {
        let read = key_usage(1, Ok(body(12., 40., 7.)));
        assert_eq!(read.meters.len(), 3);
        assert_eq!(read.meters[1].window, "weekly");
        assert_eq!(read.meters[1].percent, Some(40.));
        assert_eq!(
            read.meters[1].resets_at.as_deref(),
            Some("2099-01-01T00:00:00Z")
        );
        assert_eq!(read.highest_percent, Some(40.));
        assert!(read.usable);
    }

    #[test]
    fn next_slot_follows_the_worker_rule() {
        let result = usage(vec![
            key_usage(1, Ok(body(10., 100., 5.))), // weekly at the limit
            key_usage(2, Ok(body(40., 30., 20.))),
            key_usage(3, Err(UsageError::Refused(401))),
        ]);
        assert_eq!(result.next_slot, Some(2));
        assert_eq!(result.warning, None);
        assert!(!result.slots[0].usable);
        assert_eq!(
            result.slots[2].error.as_deref(),
            Some("OpenCode refused this key.")
        );
        // Ties go to the lower slot.
        let tie = usage(vec![
            key_usage(1, Ok(body(5., 5., 5.))),
            key_usage(2, Ok(body(5., 5., 5.))),
        ]);
        assert_eq!(tie.next_slot, Some(1));
    }

    #[test]
    fn one_key_is_the_next_slot_even_when_it_cannot_be_checked() {
        let result = usage(vec![key_usage(3, Err(UsageError::Transport))]);
        assert_eq!(result.next_slot, Some(3));
        assert!(result.warning.unwrap().contains("This key"));
    }

    #[test]
    fn warns_when_every_key_is_near_or_at_a_limit() {
        let near = usage(vec![
            key_usage(1, Ok(body(95., 10., 10.))),
            key_usage(2, Ok(body(10., 91., 10.))),
        ]);
        assert_eq!(near.next_slot, Some(2));
        assert!(near.warning.unwrap().contains("near a limit"));
        let none = usage(vec![
            key_usage(1, Ok(body(100., 0., 0.))),
            key_usage(2, Err(UsageError::Rejected)),
        ]);
        assert_eq!(none.next_slot, None);
        assert!(none.warning.unwrap().contains("Every key"));
    }

    #[test]
    fn no_key_gives_no_slot_and_no_warning() {
        let result = summarize(None, vec![], 1);
        assert_eq!(
            (result.next_slot, result.warning, result.key_source),
            (None, None, None)
        );
    }

    #[test]
    fn a_body_that_echoes_the_key_is_found() {
        assert!(contains(b"{\"k\":\"secret-key\"}", b"secret-key"));
        assert!(!contains(b"{}", b""));
    }

    #[test]
    fn the_result_never_holds_a_key() {
        let result = usage(vec![key_usage(1, Ok(body(1., 2., 3.)))]);
        let text = serde_json::to_string(&result).unwrap();
        assert!(!text.contains("key-"), "{text}");
    }
}
