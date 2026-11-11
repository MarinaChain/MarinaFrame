//! The sample vessel: a generated drawing (11 station sections of an analytic hull form,
//! made by `examples/make_sample_ship.py`) and its run spec, built into the app. A
//! first-time user starts it from Home to watch a whole run without their own drawings.
//! No licensed data: the drawing is generated, not scanned.
use crate::error::{AppError, AppResult};
use marinaframe_control::util;
use std::path::{Path, PathBuf};

/// Folder under the runs folder that holds the sample inputs. It has no task state,
/// so the run list skips it.
pub const SAMPLES: &str = "samples";

const SAMPLE_SPEC: &str = include_str!("../sample/spec.json");
const SAMPLE_DRAWING: &[u8] = include_bytes!("../sample/drawing.png");

/// Write the sample spec and drawing into a new folder under `<runs>/samples/`;
/// returns the spec path for `start_run`.
pub fn write_sample(runs_folder: &Path) -> AppResult<PathBuf> {
    let failed = || {
        AppError::new(
            "sample_write",
            "The sample vessel could not be written to the runs folder.",
        )
    };
    let folder = runs_folder
        .join(SAMPLES)
        .join(format!("sample-{}", util::now_ms()));
    std::fs::create_dir_all(&folder).map_err(|_| failed())?;
    std::fs::write(folder.join("drawing.png"), SAMPLE_DRAWING).map_err(|_| failed())?;
    let spec = folder.join("spec.json");
    std::fs::write(&spec, SAMPLE_SPEC).map_err(|_| failed())?;
    Ok(spec)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_sample_is_a_sheet_with_stations_and_its_drawing() {
        let tmp = tempfile::tempdir().unwrap();
        let spec_path = write_sample(tmp.path()).unwrap();
        assert!(spec_path.starts_with(tmp.path().join(SAMPLES)));
        let spec: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&spec_path).unwrap()).unwrap();
        assert_eq!(spec["vessel_id"], "sample-hull");
        assert_eq!(spec["sections"].as_array().unwrap().len(), 11);
        let drawing = spec_path.with_file_name(spec["source"]["file"].as_str().unwrap());
        assert!(std::fs::read(drawing).unwrap().starts_with(b"\x89PNG"));
    }
}
