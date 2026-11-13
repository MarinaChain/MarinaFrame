use marinaframe_app_core::design_record::{DesignRecord, SCHEMA};
use serde_json::Value;

const FIXTURE: &str = include_str!("../../../tests/fixtures/design_record/kvlcc2.json");

#[test]
fn schema_vocabulary_is_explicitly_supported() {
    fn check(rule: &Value) {
        let Some(object) = rule.as_object() else {
            return;
        };
        for (key, child) in object {
            assert!(
                [
                    "$schema",
                    "$id",
                    "$ref",
                    "$defs",
                    "title",
                    "description",
                    "type",
                    "properties",
                    "required",
                    "additionalProperties",
                    "propertyNames",
                    "items",
                    "minItems",
                    "minLength",
                    "minimum",
                    "pattern",
                    "const",
                    "enum",
                    "allOf",
                    "anyOf",
                    "oneOf",
                    "if",
                    "then",
                    "else"
                ]
                .contains(&key.as_str()),
                "unsupported keyword: {key}"
            );
            match key.as_str() {
                "properties" | "$defs" => {
                    for nested in child.as_object().unwrap().values() {
                        check(nested);
                    }
                }
                "allOf" | "anyOf" | "oneOf" => {
                    for nested in child.as_array().unwrap() {
                        check(nested);
                    }
                }
                "additionalProperties" | "propertyNames" | "items" | "if" | "then" | "else" => {
                    check(child)
                }
                _ => {}
            }
        }
    }
    check(&serde_json::from_str::<Value>(SCHEMA).unwrap());
}

#[test]
fn mutated_record_cannot_bypass_validation_on_save() {
    let mut record = DesignRecord::from_json(FIXTURE).unwrap();
    record.engineering_approved = true;
    assert!(record.to_json().is_err());
    let mut record = DesignRecord::from_json(FIXTURE).unwrap();
    record.main_dimensions.get_mut("length").unwrap().value = f64::INFINITY;
    assert!(record.to_json().is_err());
}

#[test]
fn public_design_roundtrip_and_invalid_corpus() {
    let expected: Value = serde_json::from_str(FIXTURE).unwrap();
    let record = DesignRecord::from_json(FIXTURE).unwrap();
    let actual: Value = serde_json::from_str(&record.to_json().unwrap()).unwrap();
    assert_eq!(actual, expected);
    let cases: Vec<Value> = serde_json::from_str(include_str!(
        "../../../tests/fixtures/design_record/invalid.json"
    ))
    .unwrap();
    for case in cases {
        let mut invalid = expected.clone();
        let path = case["path"].as_array().unwrap();
        let mut parent = &mut invalid;
        for part in &path[..path.len() - 1] {
            parent = &mut parent[part.as_str().unwrap()];
        }
        let key = path.last().unwrap().as_str().unwrap();
        if case["delete"] == true {
            parent.as_object_mut().unwrap().remove(key);
        } else {
            parent[key] = case["value"].clone();
        }
        assert!(
            DesignRecord::from_json(&invalid.to_string()).is_err(),
            "{}",
            case["name"]
        );
    }
}
