//! The live model's tool catalog, loaded from the shared
//! `tool_catalog.json`, and the tools offered in the current phase.
use super::investigation_mode;
use super::revision;
use crate::store::Store;
use crate::types::*;
use serde_json::Value;

/// The live model's tools. `build_draft` is offered only when the task's
/// ambiguity policy is `draft`.
pub fn tool_catalog(on_ambiguity: &OnAmbiguity) -> Value {
    let entries: Vec<Value> = serde_json::from_str(include_str!(
        "../../../src/vessel_reconstruction/tool_catalog.json"
    ))
    .expect("valid shared tool catalog");
    let mut tools: Vec<Value> = entries
        .into_iter()
        .filter(|entry| {
            entry["tier"] == "base"
                || (*on_ambiguity == OnAmbiguity::Draft && entry["tier"] == "draft")
        })
        .map(|mut entry| {
            let object = entry.as_object_mut().expect("tool catalog entry");
            for key in ["operation", "route", "tier", "python_catalog"] {
                object.remove(key);
            }
            entry
        })
        .collect();
    if *on_ambiguity == OnAmbiguity::Draft {
        let index = tools
            .iter()
            .position(|tool| tool["name"] == "build_draft")
            .unwrap();
        let draft = tools.remove(index);
        tools.insert(3, draft);
    }
    Value::Array(tools)
}

pub(super) fn phase_tool_catalog(store: &Store) -> Value {
    let mut tools = tool_catalog(&store.state.config.on_ambiguity);
    if revision::active(store) {
        // A focused revision pass asks for section edits only.
        tools
            .as_array_mut()
            .unwrap()
            .retain(|tool| tool["name"] == "propose_section");
        return tools;
    }
    let next = match store.state.domain["description_phase"].as_str() {
        Some("views") => Some("describe_views"),
        Some("setups") => Some("propose_sheet_setup"),
        Some("vessel") => Some("describe_vessel"),
        _ => None,
    };
    if investigation_mode(store) {
        if let Some(name) = next {
            tools.as_array_mut().unwrap().retain(|tool| {
                tool["name"] == name || (name == "describe_vessel" && tool["name"] == "read_region")
            });
        }
    }
    tools
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::controller::deterministic::decision;
    use crate::controller::test_support::*;
    use serde_json::json;
    #[test]
    fn description_operations_are_bounded_and_draft_only() {
        let view = json!({"view_id":"fore-body","kind":"body_fore","region_px":[10,20,300,400]});
        for (name, arguments) in [
            ("survey_sheet", json!({})),
            ("describe_views", json!({"views":[view.clone()]})),
            (
                "describe_vessel",
                json!({"description":{"principal":{"beam":{"value":12.0,"source":"measured"}},"stations":[{"id":"s0","x_m":0.0}]}}),
            ),
        ] {
            let operation = decision(name, arguments.clone(), "contract test")
                .operation()
                .unwrap();
            assert_eq!(operation.name(), name);
            assert_eq!(operation.args(), arguments);
            assert!(operation.is_investigation());
            for policy in [OnAmbiguity::Abstain, OnAmbiguity::Draft] {
                assert_eq!(
                    tool_catalog(&policy)
                        .as_array()
                        .unwrap()
                        .iter()
                        .any(|tool| tool["name"] == name),
                    policy == OnAmbiguity::Draft
                );
            }
        }
        for (name, arguments) in [
            ("survey_sheet", json!({"phase1_only":true})),
            ("describe_views", json!({"views":[]})),
            (
                "describe_views",
                json!({"views":[view.clone(),view.clone()]}),
            ),
            (
                "describe_views",
                json!({"views":[{"view_id":"body","kind":"body","region_px":[20,0,10,100]}]}),
            ),
            (
                "describe_vessel",
                json!({"description":{"stations":vec![json!({});301]}}),
            ),
            (
                "describe_vessel",
                json!({"description":{"notes":"x".repeat(2001)}}),
            ),
        ] {
            assert!(
                decision(name, arguments, "bounds test")
                    .operation()
                    .is_err(),
                "{name}"
            );
        }
    }

    #[test]
    fn read_phase_catalog_does_not_distract_with_section_tools() {
        let (_tmp, mut store) = fixture();
        store.state.config.policy = Policy::Live;
        store.state.config.on_ambiguity = OnAmbiguity::Draft;
        store.state.domain = json!({"description_phase":"setups"});
        let catalog = phase_tool_catalog(&store);
        let names = catalog
            .as_array()
            .unwrap()
            .iter()
            .map(|t| t["name"].as_str().unwrap())
            .collect::<Vec<_>>();
        assert_eq!(names, vec!["propose_sheet_setup"]);
        store.state.domain["description_phase"] = json!("vessel");
        let catalog = phase_tool_catalog(&store);
        assert!(catalog
            .as_array()
            .unwrap()
            .iter()
            .any(|tool| tool["name"] == "describe_vessel"));
        assert!(catalog
            .as_array()
            .unwrap()
            .iter()
            .any(|tool| tool["name"] == "read_region"));
        assert_eq!(catalog.as_array().unwrap().len(), 2);
    }

    #[test]
    fn draft_tool_is_offered_only_in_draft_mode() {
        let names = |catalog: Value| {
            catalog
                .as_array()
                .unwrap()
                .iter()
                .map(|t| t["name"].as_str().unwrap().to_string())
                .collect::<Vec<_>>()
        };
        assert!(!names(tool_catalog(&OnAmbiguity::Abstain)).contains(&"build_draft".into()));
        assert!(names(tool_catalog(&OnAmbiguity::Draft)).contains(&"build_draft".into()));
    }
}

#[cfg(test)]
mod shared_catalog_tests {
    use super::*;
    use std::collections::BTreeSet;

    #[test]
    fn catalog_matches_controller_operations_and_python_handlers() {
        let entries: Vec<Value> = serde_json::from_str(include_str!(
            "../../../src/vessel_reconstruction/tool_catalog.json"
        ))
        .unwrap();
        let mut names = BTreeSet::new();
        let python = format!(
            "{}\n{}",
            include_str!("../../../src/vessel_reconstruction/agent_tools.py"),
            include_str!("../../../src/vessel_reconstruction/investigation_tools.py")
        );
        for entry in &entries {
            let name = entry["operation"].as_str().unwrap();
            assert!(names.insert(name), "duplicate operation {name}");
            if entry["route"] == "worker" && !["initialize", "observe"].contains(&name) {
                assert!(
                    python.contains(&format!("def _{name}(")),
                    "missing Python handler {name}"
                );
            }
        }
        // These dictionaries are the actual Python argument allowlists. Compare
        // their keys in both directions, including internal worker operations.
        fn dictionary_keys(source: &str) -> BTreeSet<&str> {
            let parts: Vec<_> = source.split('"').collect();
            parts
                .windows(3)
                .step_by(2)
                .filter_map(|window| window[2].trim_start().starts_with(':').then_some(window[1]))
                .collect()
        }
        let domain = include_str!("../../../src/vessel_reconstruction/agent_tools.py")
            .split("        expected = {")
            .nth(1)
            .unwrap()
            .split("        if name not in expected:")
            .next()
            .unwrap();
        let investigation =
            include_str!("../../../src/vessel_reconstruction/investigation_tools.py")
                .split("INVESTIGATION_ARGUMENTS = {")
                .nth(1)
                .unwrap()
                .split("\n}")
                .next()
                .unwrap();
        let mut handlers = dictionary_keys(domain);
        handlers.extend(dictionary_keys(investigation));
        let worker_operations: BTreeSet<_> = entries
            .iter()
            .filter(|entry| entry["route"] == "worker")
            .map(|entry| entry["operation"].as_str().unwrap())
            .filter(|name| !["initialize", "observe"].contains(name))
            .collect();
        assert_eq!(worker_operations, handlers);
        let offered: BTreeSet<_> = tool_catalog(&OnAmbiguity::Draft)
            .as_array()
            .unwrap()
            .iter()
            .map(|entry| entry["name"].as_str().unwrap().to_owned())
            .collect();
        let declared: BTreeSet<_> = entries
            .iter()
            .filter(|entry| entry["tier"] != "internal")
            .map(|entry| entry["name"].as_str().unwrap().to_owned())
            .collect();
        assert_eq!(offered, declared);
        let types = include_str!("../types.rs");
        let operation_names = types
            .split("pub fn name(&self)")
            .nth(1)
            .unwrap()
            .split("    /// The model investigation tools")
            .next()
            .unwrap();
        let typed: BTreeSet<_> = operation_names
            .lines()
            .filter_map(|line| {
                line.split_once("=> \"")
                    .and_then(|(_, rest)| rest.split_once('"').map(|(name, _)| name.to_owned()))
            })
            .collect();
        assert_eq!(offered, typed);
    }
}
