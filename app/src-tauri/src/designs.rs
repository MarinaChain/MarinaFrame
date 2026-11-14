//! Read-only design storage. IDs come from validated records, never from caller paths.
use marinaframe_app_core::design_record::DesignRecord;
use serde::Serialize;
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
    time::UNIX_EPOCH,
};

#[derive(Serialize)]
pub struct DesignSummary {
    id: Option<String>,
    name: String,
    status: Option<String>,
    main_dimensions: Value,
    ship_type: Option<String>,
    updated_ms: Option<u64>,
    validation_error: Option<String>,
}

fn files(runs: &Path) -> Result<Vec<PathBuf>, String> {
    let folder = runs.join("designs");
    if !folder.exists() {
        return Ok(vec![]);
    }
    if fs::symlink_metadata(&folder)
        .map_err(|e| e.to_string())?
        .file_type()
        .is_symlink()
    {
        return Err("The designs folder must not be a symbolic link.".into());
    }
    let mut paths = fs::read_dir(folder)
        .map_err(|e| e.to_string())?
        .map(|entry| entry.map(|e| e.path()).map_err(|e| e.to_string()))
        .collect::<Result<Vec<_>, _>>()?;
    paths.retain(|p| p.extension().is_some_and(|e| e == "json"));
    paths.sort();
    Ok(paths)
}

fn read(path: &Path) -> Result<(DesignRecord, Value), String> {
    let meta = fs::symlink_metadata(path).map_err(|e| e.to_string())?;
    if !meta.file_type().is_file() {
        return Err("Design records must be regular files, not symbolic links.".into());
    }
    let text = fs::read_to_string(path).map_err(|e| e.to_string())?;
    let record = DesignRecord::from_json(&text)?;
    let json = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    Ok((record, json))
}

pub fn list(runs: &Path) -> Result<Vec<DesignSummary>, String> {
    let mut rows = Vec::new();
    for path in files(runs)? {
        let updated_ms = fs::metadata(&path)
            .ok()
            .and_then(|m| m.modified().ok())
            .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
            .map(|t| t.as_millis() as u64);
        let mut row = DesignSummary {
            id: None,
            name: path
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .into_owned(),
            status: None,
            main_dimensions: json!({}),
            ship_type: None,
            updated_ms,
            validation_error: None,
        };
        match read(&path) {
            Ok((record, value)) => {
                row.id = Some(record.design_id);
                row.name = record.name;
                row.status = Some(record.status);
                row.main_dimensions = value["main_dimensions"].clone();
                // The v1 contract does not contain a ship-type field. Do not infer one from cargo.
            }
            Err(error) => row.validation_error = Some(error),
        }
        rows.push(row);
    }
    let ids: Vec<_> = rows.iter().filter_map(|r| r.id.clone()).collect();
    for row in &mut rows {
        if row
            .id
            .as_ref()
            .is_some_and(|id| ids.iter().filter(|other| *other == id).count() > 1)
        {
            row.validation_error = Some("Duplicate design ID.".into());
        }
    }
    Ok(rows)
}

pub fn open(runs: &Path, id: &str) -> Result<Value, String> {
    let mut found = None;
    for path in files(runs)? {
        // Unrelated invalid files cannot prevent opening a valid design.
        if let Ok((record, value)) = read(&path) {
            if record.design_id == id {
                if found.is_some() {
                    return Err("Duplicate design ID.".into());
                }
                found = Some(value);
            }
        }
    }
    found.ok_or_else(|| {
        "Design not found or invalid. Check the validation errors in the design list.".into()
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn public_and_synthetic_mock_records_satisfy_the_contract() {
        for text in [
            include_str!("../../ui/mock/files/designs/kvlcc2.json"),
            include_str!("../../ui/mock/files/designs/kvlcc2-candidate-a.json"),
            include_str!("../../ui/mock/files/designs/kvlcc2-candidate-b.json"),
            include_str!("../../ui/mock/files/designs/kvlcc2-candidate-c.json"),
            include_str!("../../ui/mock/files/designs/kvlcc2-candidate-d.json"),
            include_str!("../../ui/mock/files/designs/kvlcc2-candidate-e.json"),
        ] {
            let record = DesignRecord::from_json(text).unwrap();
            assert!(!record.engineering_approved);
        }
    }

    #[test]
    fn lists_invalid_files_and_opens_by_record_id() {
        let folder = std::env::temp_dir().join(format!(
            "marinaframe-designs-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(folder.join("designs")).unwrap();
        fs::write(
            folder.join("designs/example.json"),
            include_str!("../../../tests/fixtures/design_record/kvlcc2.json"),
        )
        .unwrap();
        fs::write(folder.join("designs/broken.json"), "{}").unwrap();
        let rows = list(&folder).unwrap();
        assert_eq!(rows.len(), 2);
        assert!(rows[0].validation_error.is_some());
        assert_eq!(
            open(&folder, "public-kvlcc2-example").unwrap()["engineering_approved"],
            false
        );
        assert!(open(&folder, "../example").is_err());
        fs::copy(
            folder.join("designs/example.json"),
            folder.join("designs/duplicate.json"),
        )
        .unwrap();
        assert!(open(&folder, "public-kvlcc2-example").is_err());
        assert!(list(&folder)
            .unwrap()
            .iter()
            .all(|r| r.validation_error.is_some()));
        fs::remove_dir_all(folder).unwrap();
    }
}
