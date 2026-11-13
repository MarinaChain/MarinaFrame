use marinaframe_app_core::design_record::{
    migrate_v1_0_0_to_v1_1_0, DesignRecord, SCHEMA, SCHEMA_V1_1,
};
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
    check(&serde_json::from_str::<Value>(SCHEMA_V1_1).unwrap());
}

#[test]
fn explicit_migration_preserves_source_and_validates_both_versions() {
    let source: Value = serde_json::from_str(FIXTURE).unwrap();
    let original = source.clone();
    let mut expected = source.clone();
    expected["schema_version"] = "1.1.0".into();
    let migrated = migrate_v1_0_0_to_v1_1_0(&source).unwrap();
    assert_eq!(source, original);
    assert_eq!(migrated, expected);
    let record = DesignRecord::from_json(&migrated.to_string()).unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&record.to_json().unwrap()).unwrap(),
        expected
    );
    assert!(migrate_v1_0_0_to_v1_1_0(&migrated).is_err());
    for version in ["1.2.0", "2.0.0"] {
        let mut invalid = source.clone();
        invalid["schema_version"] = version.into();
        assert!(DesignRecord::from_json(&invalid.to_string()).is_err());
        assert!(migrate_v1_0_0_to_v1_1_0(&invalid).is_err());
    }
    for pointer in [
        "/extra",
        "/engineering_approved",
        "/requirements/service_speed/kn/value",
    ] {
        let mut invalid = source.clone();
        match pointer {
            "/extra" => invalid["extra"] = 12.into(),
            "/engineering_approved" => invalid["engineering_approved"] = true.into(),
            _ => *invalid.pointer_mut(pointer).unwrap() = 500.into(),
        }
        let before = invalid.clone();
        assert!(migrate_v1_0_0_to_v1_1_0(&invalid).is_err());
        assert_eq!(invalid, before);
    }
}

#[test]
fn efficiency_units_require_explicit_v1_1_and_remain_strict_on_save() {
    for unit in ["g CO2/(t nm)", "nm"] {
        let mut source: Value = serde_json::from_str(FIXTURE).unwrap();
        source["main_dimensions"]["length"]["unit"] = unit.into();
        assert!(DesignRecord::from_json(&source.to_string()).is_err());
        assert!(migrate_v1_0_0_to_v1_1_0(&source).is_err());
        source["schema_version"] = "1.1.0".into();
        let mut record = DesignRecord::from_json(&source.to_string()).unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&record.to_json().unwrap()).unwrap(),
            source
        );
        record.main_dimensions.get_mut("length").unwrap().unit = "invented".into();
        assert!(record.to_json().is_err());
        source["extra"] = 1.into();
        assert!(DesignRecord::from_json(&source.to_string()).is_err());
    }
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
