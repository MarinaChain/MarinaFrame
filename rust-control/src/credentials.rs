//! OpenCode Go credential slots and usage-based key selection.
//!
//! Up to three keys, one per OpenCode Go account, come only from the
//! environment. Before each generation the provider worker reads every
//! account's Go usage meters and uses the key with the most headroom.
//! Receipts record the slot number and meter percentages, never a key.
use crate::util::Result;
use serde_json::{json, Value};

pub const USAGE_ENDPOINT: &str = "https://opencode.ai/zen/go/v1/usage";
/// Slot 1 keeps the original variable name, so single-key setups are unchanged.
pub const CREDENTIAL_VARIABLES: [&str; 3] = [
    "OPENCODE_API_KEY",
    "OPENCODE_API_KEY_2",
    "OPENCODE_API_KEY_3",
];
/// OpenCode Go meters usage over these windows; each must be below 100 %.
const USAGE_WINDOWS: [&str; 3] = ["rolling", "weekly", "monthly"];
const MAX_KEY_BYTES: usize = 512;

pub struct Credential {
    /// 1-based position in CREDENTIAL_VARIABLES.
    pub slot: u8,
    pub key: String,
}

fn valid_key(key: &str) -> bool {
    !key.is_empty() && key.len() <= MAX_KEY_BYTES && key.is_ascii() && !key.contains(['\r', '\n'])
}

/// Load the configured keys. An unset or empty variable is skipped; a malformed
/// or duplicated key is an error, so a typo cannot silently drop an account.
pub fn load(lookup: impl Fn(&str) -> Option<String>) -> Result<Vec<Credential>> {
    let mut credentials: Vec<Credential> = Vec::new();
    for (index, variable) in CREDENTIAL_VARIABLES.iter().enumerate() {
        let Some(key) = lookup(variable).filter(|k| !k.is_empty()) else {
            continue;
        };
        if !valid_key(&key) || credentials.iter().any(|c| c.key == key) {
            return Err("provider_credential_rejected".into());
        }
        credentials.push(Credential {
            slot: index as u8 + 1,
            key,
        });
    }
    if credentials.is_empty() {
        return Err("provider_credential_unavailable".into());
    }
    Ok(credentials)
}

/// Highest meter percentage when every window reports `ok` below 100 %.
/// Returns None when any window is missing, not ok or exhausted.
pub fn highest_usage_percent(body: &Value) -> Option<f64> {
    let mut highest: f64 = 0.;
    for window in USAGE_WINDOWS {
        let meter = &body["usage"][window];
        let percent = meter["percent"].as_f64().filter(|p| p.is_finite())?;
        if meter["status"] != "ok" || !(0. ..100.).contains(&percent) {
            return None;
        }
        highest = highest.max(percent);
    }
    Some(highest)
}

/// Choose the credential with the lowest highest-window usage. Ties go to the
/// lower slot. With one credential no usage read is made.
///
/// Returns the index into `credentials` and a key-free selection record.
pub fn select(
    credentials: &[Credential],
    read_usage: impl Fn(&Credential) -> Result<Value>,
) -> Result<(usize, Value)> {
    if credentials.len() == 1 {
        let record = json!({"policy": "single_credential", "slot": credentials[0].slot});
        return Ok((0, record));
    }
    let mut candidates = Vec::new();
    let mut best: Option<(usize, f64)> = None;
    for (index, credential) in credentials.iter().enumerate() {
        match read_usage(credential) {
            Ok(body) => match highest_usage_percent(&body) {
                Some(percent) => {
                    candidates.push(json!({"slot": credential.slot, "highest_usage_percent": percent}));
                    if best.is_none_or(|(_, lowest)| percent < lowest) {
                        best = Some((index, percent));
                    }
                }
                None => candidates.push(json!({"slot": credential.slot, "unavailable": "usage_exhausted_or_unverified"})),
            },
            Err(code) => candidates.push(json!({"slot": credential.slot, "unavailable": code})),
        }
    }
    let record = |slot: Option<u8>| json!({"policy": "lowest_go_usage", "slot": slot, "candidates": candidates});
    match best {
        Some((index, _)) => Ok((index, record(Some(credentials[index].slot)))),
        None => Err("provider_all_credentials_unavailable".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn usage(rolling: f64, weekly: f64, monthly: f64) -> Value {
        let meter =
            |p: f64| json!({"status": "ok", "percent": p, "resetsAt": "2099-01-01T00:00:00Z"});
        json!({"usage": {"rolling": meter(rolling), "weekly": meter(weekly), "monthly": meter(monthly)}})
    }

    fn keys(count: u8) -> Vec<Credential> {
        (1..=count)
            .map(|slot| Credential {
                slot,
                key: format!("test-key-{slot}"),
            })
            .collect()
    }

    #[test]
    fn load_skips_unset_slots_and_rejects_duplicates_or_malformed_keys() {
        let loaded =
            load(|name| (name == "OPENCODE_API_KEY_3").then(|| "only".to_string())).unwrap();
        assert_eq!((loaded.len(), loaded[0].slot), (1, 3));
        assert!(load(|_| Some("same".to_string())).is_err());
        assert!(load(|name| (name == "OPENCODE_API_KEY").then(|| "a\nb".to_string())).is_err());
        assert_eq!(
            load(|_| None).err().unwrap(),
            "provider_credential_unavailable"
        );
    }

    #[test]
    fn single_credential_needs_no_usage_read() {
        let (index, record) = select(&keys(1), |_| panic!("no usage read expected")).unwrap();
        assert_eq!((index, record["slot"].as_u64()), (0, Some(1)));
    }

    #[test]
    fn selects_lowest_highest_window_and_skips_exhausted_or_unreadable_accounts() {
        let (index, record) = select(&keys(3), |c| match c.slot {
            1 => Ok(usage(10., 100., 5.)), // weekly window exhausted
            2 => Ok(usage(40., 30., 20.)), // highest window 40 %
            _ => Err("provider_usage_http_failure".into()),
        })
        .unwrap();
        assert_eq!((index, record["slot"].as_u64()), (1, Some(2)));
        assert_eq!(record["candidates"].as_array().unwrap().len(), 3);
        assert!(
            !record.to_string().contains("test-key"),
            "selection record must not hold keys"
        );
    }

    #[test]
    fn ties_go_to_lower_slot_and_no_usable_account_is_an_error() {
        let (index, _) = select(&keys(2), |_| Ok(usage(5., 5., 5.))).unwrap();
        assert_eq!(index, 0);
        let error = select(&keys(2), |_| Ok(usage(100., 0., 0.))).err().unwrap();
        assert_eq!(error, "provider_all_credentials_unavailable");
    }

    #[test]
    fn malformed_meters_are_not_usable() {
        assert!(highest_usage_percent(&json!({})).is_none());
        let mut body = usage(1., 2., 3.);
        body["usage"]["weekly"]["status"] = json!("error");
        assert!(highest_usage_percent(&body).is_none());
        body["usage"]["weekly"] = json!({"status": "ok", "percent": "7"});
        assert!(highest_usage_percent(&body).is_none());
    }
}
