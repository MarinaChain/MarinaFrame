//! Versioned draft engineering records. The canonical schema is embedded.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

pub const SCHEMA: &str = include_str!("../../../schemas/design-record-v1.schema.json");
pub const SCHEMA_V1_1: &str = include_str!("../../../schemas/design-record-v1.1.schema.json");

fn schema_for_version(version: Option<&str>) -> Result<Value, String> {
    let text = match version {
        Some("1.0.0") => SCHEMA,
        Some("1.1.0") => SCHEMA_V1_1,
        _ => {
            return Err(format!(
                "Unsupported design record schema version: {version:?}"
            ))
        }
    };
    serde_json::from_str(text).map_err(|e| e.to_string())
}

/// Explicit pure migration. Only the version changes; no quantity is converted.
/// Validate both endpoints and retain the original JSON values, not a serde copy.
pub fn migrate_v1_0_0_to_v1_1_0(source: &Value) -> Result<Value, String> {
    if source.get("schema_version").and_then(Value::as_str) != Some("1.0.0") {
        return Err("Migration requires a 1.0.0 design record".into());
    }
    DesignRecord::from_json(&source.to_string())?;
    let mut migrated = source.clone();
    migrated["schema_version"] = "1.1.0".into();
    DesignRecord::from_json(&migrated.to_string())?;
    Ok(migrated)
}

impl DesignRecord {
    /// Validate against the embedded contract before typed deserialization.
    pub fn from_json(text: &str) -> Result<Self, String> {
        let value: Value = serde_json::from_str(text).map_err(|e| e.to_string())?;
        let schema = schema_for_version(value.get("schema_version").and_then(Value::as_str))?;
        validate_node(&value, &schema, &schema)?;
        let record: Self = serde_json::from_str(text).map_err(|e| e.to_string())?;
        record.check_speed()?;
        Ok(record)
    }

    /// Revalidate public fields on save; mutation cannot bypass the contract.
    pub fn to_json(&self) -> Result<String, String> {
        let value = serde_json::to_value(self).map_err(|e| e.to_string())?;
        let schema = schema_for_version(value.get("schema_version").and_then(Value::as_str))?;
        validate_node(&value, &schema, &schema)?;
        self.check_speed()?;
        serde_json::to_string(&value).map_err(|e| e.to_string())
    }

    fn check_speed(&self) -> Result<(), String> {
        if let Some(speed) = &self.requirements.service_speed {
            let expected = speed.kn.value * 1852.0 / 3600.0;
            if (speed.m_s.value - expected).abs() > 1e-12_f64.max(expected.abs() * 1e-12) {
                return Err("Speed kn and m/s must agree".into());
            }
        }
        Ok(())
    }
}

/// Evaluate only the JSON Schema vocabulary used by this embedded contract.
/// This is not a general-purpose validator. Contract tests guard vocabulary drift.
fn validate_node(value: &Value, rule: &Value, root: &Value) -> Result<(), String> {
    let fail = || Err(format!("Value does not satisfy design-record rule: {rule}"));
    if let Some(reference) = rule.get("$ref").and_then(Value::as_str) {
        let target = root
            .pointer(reference.trim_start_matches('#'))
            .ok_or("Unknown schema reference")?;
        validate_node(value, target, root)?;
    }
    for keyword in ["allOf", "anyOf", "oneOf"] {
        if let Some(rules) = rule.get(keyword).and_then(Value::as_array) {
            let count = rules
                .iter()
                .filter(|r| validate_node(value, r, root).is_ok())
                .count();
            if (keyword == "allOf" && count != rules.len())
                || (keyword == "anyOf" && count == 0)
                || (keyword == "oneOf" && count != 1)
            {
                return fail();
            }
        }
    }
    if let Some(condition) = rule.get("if") {
        let branch = if validate_node(value, condition, root).is_ok() {
            "then"
        } else {
            "else"
        };
        if let Some(branch_rule) = rule.get(branch) {
            validate_node(value, branch_rule, root)?;
        }
    }
    if let Some(constant) = rule.get("const") {
        if value != constant {
            return fail();
        }
    }
    if let Some(options) = rule.get("enum").and_then(Value::as_array) {
        if !options.contains(value) {
            return fail();
        }
    }
    if let Some(types) = rule.get("type") {
        let matches = |t: &str| match t {
            "object" => value.is_object(),
            "array" => value.is_array(),
            "string" => value.is_string(),
            "number" => value.as_f64().is_some_and(f64::is_finite),
            "null" => value.is_null(),
            "boolean" => value.is_boolean(),
            _ => false,
        };
        let valid = types.as_str().is_some_and(matches)
            || types
                .as_array()
                .is_some_and(|items| items.iter().any(|t| t.as_str().is_some_and(matches)));
        if !valid {
            return fail();
        }
    }
    if let Some(text) = value.as_str() {
        if rule
            .get("minLength")
            .and_then(Value::as_u64)
            .is_some_and(|n| text.chars().count() < n as usize)
        {
            return fail();
        }
        if let Some(pattern) = rule.get("pattern").and_then(Value::as_str) {
            // The contract's only pattern is a lowercase SHA-256 digest.
            if pattern != "^[a-f0-9]{64}$"
                || text.len() != 64
                || !text
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            {
                return fail();
            }
        }
    }
    if let Some(number) = value.as_f64() {
        if !number.is_finite()
            || rule
                .get("minimum")
                .and_then(Value::as_f64)
                .is_some_and(|n| number < n)
        {
            return fail();
        }
    }
    if let Some(items) = value.as_array() {
        if rule
            .get("minItems")
            .and_then(Value::as_u64)
            .is_some_and(|n| items.len() < n as usize)
        {
            return fail();
        }
        if let Some(item_rule) = rule.get("items") {
            for item in items {
                validate_node(item, item_rule, root)?;
            }
        }
    }
    if let Some(fields) = value.as_object() {
        if let Some(required) = rule.get("required").and_then(Value::as_array) {
            for field in required {
                if !fields.contains_key(field.as_str().ok_or("Invalid required field")?) {
                    return fail();
                }
            }
        }
        for (name, child) in fields {
            if let Some(name_rule) = rule.get("propertyNames") {
                validate_node(&Value::String(name.clone()), name_rule, root)?;
            }
            if let Some(child_rule) = rule.get("properties").and_then(|p| p.get(name)) {
                validate_node(child, child_rule, root)?;
            } else if let Some(additional) = rule.get("additionalProperties") {
                if additional == false {
                    return fail();
                }
                if additional.is_object() {
                    validate_node(child, additional, root)?;
                }
            }
        }
    }
    Ok(())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesignRecord {
    pub schema_version: String,
    pub design_id: String,
    pub name: String,
    pub status: String,
    pub engineering_approved: bool,
    pub data_scope: Scope,
    pub requirements: Requirements,
    pub main_dimensions: BTreeMap<String, Quantity>,
    pub hull: Hull,
    pub compartments: Vec<Component>,
    pub tanks: Vec<Component>,
    pub weights: Vec<Component>,
    pub loading_conditions: Vec<Component>,
    pub midship_section_inputs: Vec<Component>,
    pub appendages: Vec<Component>,
    pub results: Results,
    pub lineage: Lineage,
    pub designer_decisions: Vec<Decision>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Uncertainty {
    pub kind: String,
    pub lower: f64,
    pub upper: f64,
    pub basis: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Quantity {
    pub value: f64,
    pub unit: String,
    pub uncertainty: Option<Uncertainty>,
    pub uncertainty_reason: Option<String>,
    pub method: String,
    pub method_version: String,
    pub sources: Vec<String>,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileReference {
    pub path: String,
    pub sha256: String,
    pub media_type: String,
    pub source_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Component {
    pub id: String,
    pub kind: String,
    pub quantities: BTreeMap<String, Quantity>,
    pub labels: BTreeMap<String, String>,
    pub files: Vec<FileReference>,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Scope {
    pub kind: String,
    pub customer_id: Option<String>,
    pub permitted_uses: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Speed {
    pub kn: Quantity,
    pub m_s: Quantity,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Requirements {
    pub quantities: BTreeMap<String, Quantity>,
    pub service_speed: Option<Speed>,
    pub cargo_types: Vec<String>,
    pub class_notation: Option<String>,
    pub flag: Option<String>,
    pub constraints: Vec<Component>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Hull {
    pub parameters: BTreeMap<String, Quantity>,
    pub surfaces: Vec<FileReference>,
    pub coordinate_system: String,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Lineage {
    pub parent_design_id: Option<String>,
    pub variation_parameters: BTreeMap<String, Quantity>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Decision {
    pub id: String,
    pub candidate_id: String,
    pub action: String,
    pub reason: String,
    pub designer_id: String,
    pub recorded_at: String,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Results {
    pub hull_variation: BTreeMap<String, Evidence>,
    pub hydrostatics: BTreeMap<String, Evidence>,
    pub resistance: BTreeMap<String, Evidence>,
    pub power: BTreeMap<String, Evidence>,
    pub fuel: BTreeMap<String, Evidence>,
    pub capacities: BTreeMap<String, Evidence>,
    pub stability: BTreeMap<String, Evidence>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    content = "value",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum Evidence {
    Quantity(Quantity),
    Text(String),
    Flag(bool),
    Missing(()),
    List(Vec<Evidence>),
    Object(BTreeMap<String, Evidence>),
}
