//! The GA reading of a commercial ship, when the run has one
//! (`src/vessel_reconstruction/ga_commercial.py`, docs/plans/2026-11-12-ga-commercial.md):
//! principal particulars, counts and spaces, each with a source record. The UI lists them
//! (`app/ui/js/ga_panel.js`) and shows the GA region of a row on hover.
//!
//! The file is the worker's; the app only reads it. A record that fails
//! `source_record::checked` is replaced by null, so the app shows "no source record" for that
//! row instead of drawing a region it cannot trust.
use marinaframe_control::util;
use serde_json::Value;
use std::path::Path;

pub const READING_FILE: &str = "ga_reading/ga_reading.json";
pub const SCHEMA: &str = "marinaframe.ga_reading.v1";
const MAX_BYTES: usize = 2 * 1024 * 1024;

fn check_record(item: &mut Value) {
    if let Some(record) = item.get_mut("source_record") {
        *record = crate::source_record::checked(record).unwrap_or(Value::Null);
    }
}

/// The run's GA reading with checked source records, or None (no file, other schema, or a
/// reading that claims engineering approval).
pub fn read(task: &Path) -> Option<Value> {
    let bytes = util::read_bounded(&task.join(READING_FILE), MAX_BYTES).ok()?;
    let mut reading: Value = serde_json::from_slice(&bytes).ok()?;
    if reading["schema"] != SCHEMA || reading["engineering_approved"] != false {
        return None;
    }
    for group in ["particulars", "counts"] {
        if let Some(items) = reading[group].as_object_mut() {
            items.values_mut().for_each(check_record);
        }
    }
    if let Some(spaces) = reading["spaces"].as_array_mut() {
        spaces.iter_mut().for_each(check_record);
    }
    Some(reading)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn write(task: &Path, value: &Value) {
        std::fs::create_dir_all(task.join("ga_reading")).unwrap();
        std::fs::write(task.join(READING_FILE), serde_json::to_vec(value).unwrap()).unwrap();
    }

    #[test]
    fn records_are_checked_and_approval_is_refused() {
        let dir = tempfile::tempdir().unwrap();
        assert!(read(dir.path()).is_none());
        let region = json!({"sheet":"GA.png","page":0,"view":null,"box_px":[1.0,2.0,30.0,40.0],"page_px":[100,100]});
        let reading = json!({"schema":SCHEMA,"engineering_approved":false,
            "particulars":{"loa_m":{"value":189.99,"source_record":{"kind":"read","regions":[region]}}},
            "counts":{"cargo_holds":{"value":4,"source_record":{"kind":"approved"}}},
            "spaces":[{"id":"cargo_hold-001","source_record":{"kind":"unknown","reason":"no label"}}]});
        write(dir.path(), &reading);
        let view = read(dir.path()).unwrap();
        assert_eq!(
            view["particulars"]["loa_m"]["source_record"]["kind"],
            "read"
        );
        assert!(view["counts"]["cargo_holds"]["source_record"].is_null());
        assert_eq!(view["spaces"][0]["source_record"]["kind"], "unknown");
        let mut approved = reading.clone();
        approved["engineering_approved"] = json!(true);
        write(dir.path(), &approved);
        assert!(read(dir.path()).is_none());
    }
}
