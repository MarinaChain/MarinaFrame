//! `propose_section`: the live model writes the shape of one section (draft
//! mode only). The Python worker fairs the curve, clamps it to the declared
//! beam and depth, renders it on the source panel and labels it `ai_inferred`
//! or `ai_corrected` (see `src/vessel_reconstruction/section_authoring.py`).
//! Rust checks only the argument bounds here; the guess contract in
//! `validation.rs` checks the resulting `model_authored` guess.
use crate::util;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

/// Input bounds of a proposal. The worker applies the same bounds per form.
const MIN_OFFSETS: usize = 5;
const MAX_OFFSETS: usize = 24;
const MAX_BASIS_CHARS: usize = 300;
const MAX_DIMENSION_M: f64 = 1000.0;
const FULLNESS: (f64, f64) = (0.5, 1.5);
const MAX_DEADRISE_DEG: f64 = 60.0;

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SectionForm {
    HalfBreadths,
    Blend,
    StandardForm,
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub enum SectionShape {
    U,
    V,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProposeSection {
    pub section_id: String,
    pub form: SectionForm,
    /// One line: what the model based the shape on.
    pub basis: String,
    /// `none`, or the traced candidate id that the proposal corrects.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub replaces: Option<String>,
    /// [height_m, half_breadth_m] pairs (form half_breadths).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub offsets_m: Option<Vec<[f64; 2]>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fullness: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shape: Option<SectionShape>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub beam_m: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub draft_m: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub bilge_radius_m: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub deadrise_deg: Option<f64>,
}

fn within(value: f64, low: f64, high: f64) -> bool {
    value.is_finite() && (low..=high).contains(&value)
}

impl ProposeSection {
    pub fn valid(&self) -> bool {
        let basis_chars = self.basis.chars().count();
        let optional =
            |value: Option<f64>, low: f64, high: f64| value.is_none_or(|v| within(v, low, high));
        util::valid_section_id(&self.section_id)
            && (1..=MAX_BASIS_CHARS).contains(&basis_chars)
            && !self.basis.chars().any(char::is_control)
            && self
                .replaces
                .as_deref()
                .is_none_or(|r| util::valid_id(r, 64))
            && self.offsets_m.as_ref().is_none_or(|offsets| {
                (MIN_OFFSETS..=MAX_OFFSETS).contains(&offsets.len())
                    && offsets
                        .iter()
                        .flatten()
                        .all(|v| within(*v, -MAX_DIMENSION_M, MAX_DIMENSION_M))
            })
            && optional(self.fullness, FULLNESS.0, FULLNESS.1)
            && optional(self.beam_m, 1e-3, MAX_DIMENSION_M)
            && optional(self.draft_m, 1e-3, MAX_DIMENSION_M)
            && optional(self.bilge_radius_m, 0.0, MAX_DIMENSION_M)
            && optional(self.deadrise_deg, 0.0, MAX_DEADRISE_DEG)
            && match self.form {
                SectionForm::HalfBreadths => self.offsets_m.is_some(),
                SectionForm::Blend => true,
                SectionForm::StandardForm => {
                    self.shape.is_some() && self.beam_m.is_some() && self.draft_m.is_some()
                }
            }
    }
}

/// The live model's tool definition.
pub fn tool() -> Value {
    let number = json!({"type":"number"});
    json!({"name":"propose_section","description":"Write the shape of a section yourself when it has no usable traced curve or you judge the trace wrong (you may also correct, complete or fair a trace). form half_breadths: offsets_m = 5-24 [height_m, half_breadth_m] pairs in metres; blend: the two neighbouring sections blended by station position and scaled by fullness (0.5-1.5, 1 = plain blend); standard_form: U or V section with beam_m, draft_m and optional bilge_radius_m, deadrise_deg. basis: one line on what you based it on. replaces: 'none' or the traced candidate id it corrects. The host fairs the curve, clamps it to the declared beam and depth, shows it on the source panel with warnings; build_draft then uses it, labelled ai_inferred or ai_corrected.",
        "parameters":{"type":"object","properties":{
            "section_id":{"type":"string","maxLength":64},
            "form":{"enum":["half_breadths","blend","standard_form"]},
            "basis":{"type":"string","maxLength":MAX_BASIS_CHARS},
            "replaces":{"type":"string","maxLength":64},
            "offsets_m":{"type":"array","items":{"type":"array","items":number,"minItems":2,"maxItems":2},"minItems":MIN_OFFSETS,"maxItems":MAX_OFFSETS},
            "fullness":{"type":"number","minimum":FULLNESS.0,"maximum":FULLNESS.1},
            "shape":{"enum":["U","V"]},
            "beam_m":number,"draft_m":number,"bilge_radius_m":number,
            "deadrise_deg":{"type":"number","minimum":0,"maximum":MAX_DEADRISE_DEG}},
        "required":["section_id","form","basis"],"additionalProperties":false}})
}

#[cfg(test)]
mod tests {
    use super::*;
    fn proposal(arguments: Value) -> Option<ProposeSection> {
        serde_json::from_value(arguments).ok()
    }
    #[test]
    fn proposal_bounds_follow_the_form() {
        let offsets = json!([[0, 0], [1, 1], [2, 1.2], [3, 1.3], [4, 1.3]]);
        let good = [
            json!({"section_id":"s1","form":"half_breadths","basis":"Plan view.","offsets_m":offsets}),
            json!({"section_id":"s1","form":"blend","basis":"Neighbours.","fullness":1.1,"replaces":"trace-abc"}),
            json!({"section_id":"s1","form":"standard_form","basis":"Typical U.","shape":"U","beam_m":4,"draft_m":2}),
        ];
        for arguments in good {
            assert!(proposal(arguments.clone()).unwrap().valid(), "{arguments}");
        }
        let bad = [
            json!({"section_id":"s1","form":"half_breadths","basis":"No offsets."}),
            json!({"section_id":"s1","form":"half_breadths","basis":"Few.","offsets_m":[[0,0],[1,1]]}),
            json!({"section_id":"s1","form":"blend","basis":"Too full.","fullness":3}),
            json!({"section_id":"s1","form":"blend","basis":""}),
            json!({"section_id":"s1","form":"standard_form","basis":"No beam.","shape":"V","draft_m":2}),
            json!({"section_id":"s1","form":"blend","basis":"Bad id.","replaces":"a b"}),
        ];
        for arguments in bad {
            assert!(
                proposal(arguments.clone()).is_none_or(|p| !p.valid()),
                "{arguments}"
            );
        }
        assert!(
            proposal(json!({"section_id":"s1","form":"blend","basis":"x","path":"/etc"})).is_none()
        );
    }
}
