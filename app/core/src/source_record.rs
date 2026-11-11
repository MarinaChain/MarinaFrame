//! Source records of a run's sections, parts and tanks (docs/SOURCE_RECORD.md): where each item
//! was read on the drawings, or the guess and the inputs it came from. The workers write them
//! (`src/vessel_reconstruction/source_record.py`); this module checks their form and passes them
//! to the app, which shows the source sheet beside the 3D model. A run made before the records
//! existed has none: the app then says "no source record; run again".
use marinaframe_control::util;
use serde_json::Value;
use std::collections::HashMap;
use std::path::Path;

/// The record file of a capacity plan: `<stem>_source_records.json` beside `<stem>_capacity_plan.csv`.
pub const TANK_RECORDS_SUFFIX: &str = "_source_records.json";
/// The same limits as the worker (`source_record.py`), so a record is always small.
const MAX_REGIONS: usize = 8;
const MAX_INPUTS: usize = 12;
/// Longest text of a record (the worker keeps 240 characters; this leaves room for UTF-8).
const MAX_TEXT_BYTES: usize = 1024;
/// Largest record file read (a few hundred tanks of at most ~2.5 KB each).
const MAX_FILE_BYTES: usize = 2 * 1024 * 1024;

fn short_text(value: &Value) -> bool {
    value
        .as_str()
        .is_some_and(|text| !text.trim().is_empty() && text.len() <= MAX_TEXT_BYTES)
}

fn region_ok(region: &Value) -> bool {
    let box_ok = match &region["box_px"] {
        Value::Null => true,
        Value::Array(items) => {
            items.len() == 4
                && items.iter().all(Value::is_number)
                && region["page_px"]
                    .as_array()
                    .is_some_and(|page| page.len() == 2 && page.iter().all(Value::is_u64))
        }
        _ => false,
    };
    short_text(&region["sheet"]) && region["page"].is_u64() && box_ok
}

fn input_ok(input: &Value) -> bool {
    match input.get("part") {
        Some(part) => short_text(part),
        None => region_ok(input),
    }
}

/// The record when it has a known kind and the fields of that kind, within the size limits;
/// otherwise None (the app then treats the item as having no record).
pub fn checked(value: &Value) -> Option<Value> {
    let ok = match value["kind"].as_str()? {
        "read" => value["regions"].as_array().is_some_and(|regions| {
            (1..=MAX_REGIONS).contains(&regions.len()) && regions.iter().all(region_ok)
        }),
        "guessed" => {
            short_text(&value["method"])
                && value["inputs"]
                    .as_array()
                    .is_some_and(|inputs| inputs.len() <= MAX_INPUTS && inputs.iter().all(input_ok))
        }
        "unknown" => short_text(&value["reason"]),
        _ => false,
    };
    ok.then(|| value.clone())
}

/// The tank records beside a capacity plan, by tank id (empty when the run has none).
pub fn read_tank_records(capacity: &Path) -> HashMap<String, Value> {
    let Some(name) = capacity.file_name().and_then(|n| n.to_str()) else {
        return HashMap::new();
    };
    let Some(stem) = name.strip_suffix(crate::run_tables::CAPACITY_SUFFIX) else {
        return HashMap::new();
    };
    let path = capacity.with_file_name(format!("{stem}{TANK_RECORDS_SUFFIX}"));
    let Some(file) = util::read_bounded(&path, MAX_FILE_BYTES)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
    else {
        return HashMap::new();
    };
    file["records"]
        .as_object()
        .into_iter()
        .flatten()
        .filter_map(|(id, record)| Some((id.clone(), checked(record)?)))
        .collect()
}

/// The section records of a build record (`result.json`), by section id.
pub fn section_records(record: &Value) -> HashMap<String, Value> {
    record["sections"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|section| {
            let id = section["id"].as_str()?.to_string();
            Some((id, checked(&section["source_record"])?))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn region() -> Value {
        json!({"sheet": "ga.pdf", "page": 0, "view": "plan", "box_px": [1, 2, 30, 40], "page_px": [100, 80]})
    }

    #[test]
    fn the_three_kinds_pass_and_others_do_not() {
        assert!(checked(&json!({"kind": "read", "regions": [region()]})).is_some());
        let dxf = json!({"sheet": "ga.dxf", "page": 0, "view": "profile", "box_px": null});
        assert!(checked(&json!({"kind": "read", "regions": [dxf]})).is_some());
        let guess = json!({"kind": "guessed", "method": "beam box", "inputs": [region(), {"part": "deck"}]});
        assert!(checked(&guess).is_some());
        assert!(checked(&json!({"kind": "unknown", "reason": "not recorded"})).is_some());

        assert!(checked(&json!({"kind": "approved"})).is_none());
        assert!(checked(&json!({"kind": "read", "regions": []})).is_none());
        let no_page = json!({"sheet": "a", "page": 0, "box_px": [1, 2, 3, 4]});
        assert!(checked(&json!({"kind": "read", "regions": [no_page]})).is_none());
        assert!(checked(&json!({"kind": "unknown", "reason": " "})).is_none());
        let many: Vec<Value> = (0..13).map(|i| json!({"part": format!("p{i}")})).collect();
        assert!(checked(&json!({"kind": "guessed", "method": "m", "inputs": many})).is_none());
        assert!(checked(&Value::Null).is_none());
    }

    #[test]
    fn tank_records_are_read_beside_the_capacity_plan() {
        let dir = std::env::temp_dir().join(format!("mf-source-records-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let capacity = dir.join("case_DRAFT_capacity_plan.csv");
        std::fs::write(
            dir.join("case_DRAFT_source_records.json"),
            json!({"schema": "source-record/v1", "records": {
                "fo1": {"kind": "read", "regions": [region()]},
                "bad": {"kind": "read", "regions": []}}})
            .to_string(),
        )
        .unwrap();
        let records = read_tank_records(&capacity);
        assert_eq!(records.len(), 1);
        assert_eq!(records["fo1"]["kind"], "read");
        assert!(read_tank_records(&dir.join("other.csv")).is_empty());
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn section_records_come_from_the_build_record() {
        let record = json!({"sections": [
            {"id": "st1", "source_record": {"kind": "read", "regions": [region()]}},
            {"id": "st2"}]});
        let records = section_records(&record);
        assert_eq!(records.len(), 1);
        assert!(records.contains_key("st1"));
    }
}
