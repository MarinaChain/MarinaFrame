//! The automatic body-plan calibration of a run, as one review item (docs/AUTO_CALIBRATION.md).
//! The worker writes `domain/body-plan-check.json` and the overlay PNG
//! (`src/vessel_reconstruction/body_plan_intake.py`) when the intake made a body-plan reading.
//! The person's decision is saved like a part review (`parts::review_component`) under
//! [`REVIEW_ID`]; it is app state, never written into the run folder.
use crate::files;
use crate::parts::PartReview;
use crate::types::BodyPlanCheckView;
use serde_json::Value;
use std::collections::HashMap;
use std::path::Path;

pub const CHECK_FILE: &str = "domain/body-plan-check.json";
/// The review id of the calibration item (no ship-cad part has this id).
pub const REVIEW_ID: &str = "body_plan_calibration";
const CHECK_MAX_BYTES: usize = 256 * 1024;

fn strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .map(|items| {
            items
                .iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default()
}

/// The review item of a run, when its worker wrote one.
pub fn read(task: &Path, reviews: &HashMap<String, PartReview>) -> Option<BodyPlanCheckView> {
    let bytes =
        marinaframe_control::util::read_bounded(&task.join(CHECK_FILE), CHECK_MAX_BYTES).ok()?;
    let check: Value = serde_json::from_slice(&bytes).ok()?;
    let overlay = format!("domain/{}", check["overlay"].as_str()?);
    crate::artifact::guard_artifact_path(task, &overlay).ok()?;
    let (width, height) = files::png_size(&task.join(&overlay))?;
    Some(BodyPlanCheckView {
        overlay_path: overlay,
        width,
        height,
        used: check["used"].as_bool().unwrap_or(false),
        stations_used: strings(&check["stations_used"]),
        reason: check["reason"].as_str().unwrap_or_default().to_string(),
        flags: strings(&check["flags"]),
        notes: strings(&check["notes"]),
        warnings: strings(&check["warnings"]),
        review: reviews.get(REVIEW_ID).cloned(),
    })
}

/// True when the run has a calibration item to review.
pub fn exists(task: &Path) -> bool {
    task.join(CHECK_FILE).is_file()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn png(path: &Path) {
        // A 1 x 1 PNG.
        let bytes: [u8; 67] = [
            0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48,
            0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00,
            0x00, 0x1f, 0x15, 0xc4, 0x89, 0x00, 0x00, 0x00, 0x0a, 0x49, 0x44, 0x41, 0x54, 0x78,
            0x9c, 0x63, 0x00, 0x01, 0x00, 0x00, 0x05, 0x00, 0x01, 0x0d, 0x0a, 0x2d, 0xb4, 0x00,
            0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
        ];
        std::fs::write(path, bytes).unwrap();
    }

    #[test]
    fn reads_the_check_and_the_saved_review() {
        let task = tempfile::tempdir().unwrap();
        let domain = task.path().join("domain");
        std::fs::create_dir_all(&domain).unwrap();
        assert!(read(task.path(), &HashMap::new()).is_none());
        png(&domain.join("body-plan-check.png"));
        std::fs::write(
            domain.join("body-plan-check.json"),
            r#"{"overlay":"body-plan-check.png","used":false,"stations_used":[],
               "reason":"calibration has open flags","flags":["sides: checks disagree"],
               "notes":["baseline is not labelled"],"warnings":[]}"#,
        )
        .unwrap();
        let mut reviews = HashMap::new();
        reviews.insert(
            REVIEW_ID.to_string(),
            PartReview {
                decision: "accepted".into(),
                note: None,
            },
        );
        let view = read(task.path(), &reviews).unwrap();
        assert_eq!(view.overlay_path, "domain/body-plan-check.png");
        assert_eq!((view.width, view.height), (1, 1));
        assert!(!view.used);
        assert_eq!(view.flags, vec!["sides: checks disagree"]);
        assert_eq!(view.review.unwrap().decision, "accepted");
        assert!(exists(task.path()));
    }

    #[test]
    fn rejects_an_overlay_outside_the_task() {
        let task = tempfile::tempdir().unwrap();
        let domain = task.path().join("domain");
        std::fs::create_dir_all(&domain).unwrap();
        std::fs::write(
            domain.join("body-plan-check.json"),
            r#"{"overlay":"../../outside.png","used":true}"#,
        )
        .unwrap();
        assert!(read(task.path(), &HashMap::new()).is_none());
    }
}
