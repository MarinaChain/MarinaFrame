//! Tank and steel-structure tables of a run: the capacity plan, the sounding tables, the steel
//! tables and the OCX file that the Python side writes. The app only reads these files; it does
//! not compute tank or steel values. Every table is a draft (`engineering_approved` is false).
//!
//! Run folder layout (the one place that fixes it; the tank workers
//! `benchmarks/gunnerus/whole_vessel_internals.py` and `benchmarks/tanks/raster_run.py` write
//! their output folder in this form):
//!
//! ```text
//! <task>/tanks.npz                          tank model (vessel_reconstruction.tanks.save_tanks);
//!                                           the export worker reads it (--tanks)
//! <task>/tank_tables/<stem>_capacity_plan.csv     capacity plan (exports/tank_tables.py)
//! <task>/tank_tables/<stem>_sounding_<id>.csv     sounding table of each built tank
//! <task>/structure/*_steel_members.csv      steel table per member (structure/steel.py)
//! <task>/structure/*_steel_totals.csv       steel totals per group
//! <task>/structure/*.3docx                  OCX 3.0.1 file of the block (structure/ocx.py)
//! ```
use crate::error::{AppError, AppResult};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// Tank model file inside the task folder.
pub const TANK_MODEL_FILE: &str = "tanks.npz";
/// Folder inside the task folder with the capacity plan and sounding tables.
pub const TANK_TABLES_FOLDER: &str = "tank_tables";
/// Folder inside the task folder with the steel tables and OCX files.
pub const STRUCTURE_FOLDER: &str = "structure";
const CAPACITY_SUFFIX: &str = "_capacity_plan.csv";
const SOUNDING_INFIX: &str = "_sounding_";
/// Structure files by name suffix, with their role.
const STRUCTURE_ROLES: [(&str, &str); 4] = [
    ("_steel_members.csv", "steel_members"),
    ("_steel_totals.csv", "steel_totals"),
    (".3docx", "ocx_structure"),
    // Display meshes of the members for the 3D view (`structure/display.py`).
    ("_structure.glb", "structure_model"),
];
/// Largest table file the app reads. A capacity plan or a sounding table is a few kB.
const TABLE_MAX_BYTES: usize = 4 * 1024 * 1024;
/// The exports write a text cell that starts with one of these with a leading single quote
/// (`exports/csv_safety.py`); the app shows the text without that quote.
const FORMULA_PREFIXES: [char; 6] = ['=', '+', '-', '@', '\t', '\r'];

/// One tank of the capacity plan (one row of `<stem>_capacity_plan.csv`).
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct CapacityRow {
    /// The tank id; the same id as the tank's part (`ComponentView.id`).
    pub id: String,
    pub name: String,
    /// Content group, for example "water ballast" or "fuel oil".
    pub content: String,
    pub frames: String,
    pub built: bool,
    pub volume_100_m3: Option<f64>,
    pub volume_98_m3: Option<f64>,
    pub density_t_m3: Option<f64>,
    pub weight_98_t: Option<f64>,
    pub lcg_m: Option<f64>,
    pub tcg_m: Option<f64>,
    pub vcg_m: Option<f64>,
    pub max_free_surface_moment_tm: Option<f64>,
    pub printed_volume_m3: Option<f64>,
    /// Source label per value ("traced", "read" or "guessed"): keys name, content, frames,
    /// volume, density, centroid, and weight (the weaker label of volume and density).
    pub sources: BTreeMap<String, String>,
    pub notes: String,
    /// True when the run has a sounding table for this tank.
    pub has_sounding: bool,
}

/// Totals of one content group: volume at 100 % and weight at 98 % of the built tanks.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct CapacityGroup {
    pub content: String,
    pub tanks: u32,
    pub built: u32,
    pub volume_100_m3: f64,
    pub weight_98_t: f64,
}

/// The capacity plan of a run, as the Python export wrote it.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct CapacityPlanView {
    /// Task-relative path of the CSV file.
    pub file: String,
    /// The draft stamp and notes at the top of the file (without the leading '#').
    pub stamp: Vec<String>,
    pub rows: Vec<CapacityRow>,
    pub groups: Vec<CapacityGroup>,
    /// Always false: engineering sign-off happens outside MarinaFrame.
    pub engineering_approved: bool,
}

/// The sounding table of one tank: the CSV columns and one row of numbers per level.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct SoundingTableView {
    pub tank_id: String,
    /// Task-relative path of the CSV file.
    pub file: String,
    pub stamp: Vec<String>,
    /// Column names, for example "sounding_m", "ullage_m", "volume_m3", "fill_pct".
    pub columns: Vec<String>,
    pub rows: Vec<Vec<Option<f64>>>,
    pub engineering_approved: bool,
}

/// One steel table or OCX file of the run's structure folder.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct StructureFile {
    /// "steel_members", "steel_totals", "ocx_structure" or "structure_model" (display GLB).
    pub role: String,
    pub file: String,
    /// Task-relative path.
    pub path: String,
    pub bytes: u64,
}

/// Rows of a CSV text (RFC 4180: quoted cells may hold commas, quotes and line breaks).
fn parse_csv(text: &str) -> Vec<Vec<String>> {
    let mut rows = vec![];
    let mut row = vec![];
    let mut cell = String::new();
    let mut quoted = false;
    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        match (quoted, c) {
            (true, '"') if chars.peek() == Some(&'"') => {
                cell.push('"');
                chars.next();
            }
            (true, '"') => quoted = false,
            (true, _) => cell.push(c),
            (false, '"') => quoted = true,
            (false, ',') => row.push(std::mem::take(&mut cell)),
            (false, '\r') => {}
            (false, '\n') => {
                row.push(std::mem::take(&mut cell));
                rows.push(std::mem::take(&mut row));
            }
            (false, _) => cell.push(c),
        }
    }
    if !cell.is_empty() || !row.is_empty() {
        row.push(cell);
        rows.push(row);
    }
    rows
}

/// A table file: its comment lines (stamp) and its header and data rows as maps.
struct Table {
    stamp: Vec<String>,
    columns: Vec<String>,
    rows: Vec<Vec<String>>,
}

fn read_table(path: &Path) -> Option<Table> {
    let bytes = marinaframe_control::util::read_bounded(path, TABLE_MAX_BYTES).ok()?;
    let text = String::from_utf8(bytes).ok()?;
    let mut stamp = vec![];
    let mut lines = parse_csv(&text).into_iter();
    let columns = loop {
        let row = lines.next()?;
        match row.first() {
            Some(first) if first.starts_with('#') => {
                stamp.push(first.trim_start_matches('#').trim().to_string());
            }
            _ => break row,
        }
    };
    let rows = lines
        .filter(|row| row.iter().any(|c| !c.is_empty()))
        .collect();
    Some(Table {
        stamp,
        columns,
        rows,
    })
}

/// A text cell as written by `safe_text_cell`, without its formula guard.
fn text_cell(raw: &str) -> String {
    match raw.strip_prefix('\'') {
        Some(rest) if rest.starts_with(FORMULA_PREFIXES) => rest.to_string(),
        _ => raw.to_string(),
    }
}

fn number_cell(raw: &str) -> Option<f64> {
    raw.trim().parse::<f64>().ok().filter(|v| v.is_finite())
}

/// The file-name form of a tank id (`exports/source.py` `safe_name`): runs of other characters
/// than letters, digits, '.', '_' and '-' become '-', then '-' and '.' are trimmed.
pub fn safe_name(text: &str) -> String {
    let mut name = String::new();
    let mut in_run = false;
    for c in text.chars() {
        if c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-') {
            name.push(c);
            in_run = false;
        } else if !in_run {
            name.push('-');
            in_run = true;
        }
    }
    let trimmed = name.trim_matches(|c| c == '-' || c == '.');
    if trimmed.is_empty() {
        "vessel".into()
    } else {
        trimmed.into()
    }
}

/// The weaker of two source labels: "guessed" before "traced" before "read".
fn weaker_label(a: Option<&String>, b: Option<&String>) -> Option<String> {
    let rank = |label: &str| match label {
        "guessed" => 0,
        "traced" => 1,
        _ => 2,
    };
    match (a, b) {
        (Some(a), Some(b)) => Some(if rank(b) < rank(a) { b } else { a }.clone()),
        (Some(one), None) | (None, Some(one)) => Some(one.clone()),
        (None, None) => None,
    }
}

/// The capacity plan file of a run (the first by name), if there is one.
fn capacity_file(task: &Path) -> Option<PathBuf> {
    let mut files: Vec<PathBuf> = std::fs::read_dir(task.join(TANK_TABLES_FOLDER))
        .ok()?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|n| n.to_str())
                .is_some_and(|n| n.ends_with(CAPACITY_SUFFIX))
        })
        .collect();
    files.sort();
    files.into_iter().next()
}

/// The sounding table file of tank `id` next to the capacity plan `capacity`.
fn sounding_file(capacity: &Path, id: &str) -> Option<PathBuf> {
    let name = capacity.file_name()?.to_str()?;
    let stem = name.strip_suffix(CAPACITY_SUFFIX)?;
    Some(capacity.with_file_name(format!("{stem}{SOUNDING_INFIX}{}.csv", safe_name(id))))
}

fn relative(task: &Path, path: &Path) -> String {
    path.strip_prefix(task)
        .unwrap_or(path)
        .to_string_lossy()
        .into_owned()
}

fn capacity_row(columns: &[String], cells: &[String], capacity: &Path) -> CapacityRow {
    let get = |name: &str| {
        columns
            .iter()
            .position(|c| c == name)
            .and_then(|i| cells.get(i))
            .map(String::as_str)
            .unwrap_or("")
    };
    let number = |name: &str| number_cell(get(name));
    let mut sources: BTreeMap<String, String> = columns
        .iter()
        .zip(cells)
        .filter_map(|(column, value)| {
            let key = column.strip_prefix("source_")?;
            (!value.is_empty()).then(|| (key.to_string(), value.clone()))
        })
        .collect();
    if let Some(weight) = weaker_label(sources.get("volume"), sources.get("density")) {
        sources.insert("weight".into(), weight);
    }
    let id = text_cell(get("id"));
    let has_sounding = sounding_file(capacity, &id).is_some_and(|path| path.is_file());
    CapacityRow {
        name: text_cell(get("name")),
        content: text_cell(get("content")),
        frames: text_cell(get("frames")),
        built: get("built").eq_ignore_ascii_case("true"),
        volume_100_m3: number("volume_100_m3"),
        volume_98_m3: number("volume_98_m3"),
        density_t_m3: number("density_t_m3"),
        weight_98_t: number("weight_98_t"),
        lcg_m: number("lcg_m"),
        tcg_m: number("tcg_m"),
        vcg_m: number("vcg_m"),
        max_free_surface_moment_tm: number("max_free_surface_moment_tm"),
        printed_volume_m3: number("printed_volume_m3"),
        sources,
        notes: text_cell(get("notes")),
        has_sounding,
        id,
    }
}

/// Totals per content group in first-seen order; tanks that are not built count as 0
/// (the rule of `vessel_reconstruction.tanks.group_totals`).
fn group_totals(rows: &[CapacityRow]) -> Vec<CapacityGroup> {
    let mut groups: Vec<CapacityGroup> = vec![];
    for row in rows {
        let index = match groups.iter().position(|g| g.content == row.content) {
            Some(index) => index,
            None => {
                groups.push(CapacityGroup {
                    content: row.content.clone(),
                    tanks: 0,
                    built: 0,
                    volume_100_m3: 0.0,
                    weight_98_t: 0.0,
                });
                groups.len() - 1
            }
        };
        let group = &mut groups[index];
        group.tanks += 1;
        if row.built {
            group.built += 1;
            group.volume_100_m3 += row.volume_100_m3.unwrap_or(0.0);
            group.weight_98_t += row.weight_98_t.unwrap_or(0.0);
        }
    }
    groups
}

/// The run's capacity plan, or None when the run has none (or it cannot be read).
pub fn read_capacity_plan(task: &Path) -> Option<CapacityPlanView> {
    let capacity = capacity_file(task)?;
    let table = read_table(&capacity)?;
    if !table.columns.iter().any(|c| c == "id") {
        return None;
    }
    let rows: Vec<CapacityRow> = table
        .rows
        .iter()
        .map(|cells| capacity_row(&table.columns, cells, &capacity))
        .collect();
    Some(CapacityPlanView {
        file: relative(task, &capacity),
        stamp: table.stamp,
        groups: group_totals(&rows),
        rows,
        engineering_approved: false,
    })
}

/// The sounding table of one tank of the run's capacity plan.
pub fn read_sounding_table(task: &Path, tank_id: &str) -> AppResult<SoundingTableView> {
    let missing = || {
        AppError::new(
            "sounding_not_found",
            "This run has no sounding table for that tank.",
        )
    };
    let capacity = capacity_file(task).ok_or_else(missing)?;
    // Only a tank of the capacity plan: the id never names an arbitrary file.
    let plan = read_capacity_plan(task).ok_or_else(missing)?;
    if !plan.rows.iter().any(|row| row.id == tank_id) {
        return Err(missing());
    }
    let path = sounding_file(&capacity, tank_id).ok_or_else(missing)?;
    let table = read_table(&path).ok_or_else(missing)?;
    let rows = table
        .rows
        .iter()
        .map(|cells| cells.iter().map(|cell| number_cell(cell)).collect())
        .collect();
    Ok(SoundingTableView {
        tank_id: tank_id.to_string(),
        file: relative(task, &path),
        stamp: table.stamp,
        columns: table.columns,
        rows,
        engineering_approved: false,
    })
}

/// True when the run has a tank model the export worker can read.
pub fn tank_model_path(task: &Path) -> Option<PathBuf> {
    let path = task.join(TANK_MODEL_FILE);
    std::fs::symlink_metadata(&path)
        .is_ok_and(|meta| meta.is_file())
        .then_some(path)
}

/// Role of a structure file from its name, or None for other files.
pub fn structure_role(name: &str) -> Option<&'static str> {
    STRUCTURE_ROLES
        .iter()
        .find(|(suffix, _)| name.ends_with(suffix))
        .map(|(_, role)| *role)
}

/// The steel tables and OCX files of the run's structure folder, by name.
pub fn structure_files(task: &Path) -> Vec<StructureFile> {
    let mut files: Vec<StructureFile> = std::fs::read_dir(task.join(STRUCTURE_FOLDER))
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
        .filter_map(|entry| {
            let file = entry.file_name().into_string().ok()?;
            let role = structure_role(&file)?;
            let meta = std::fs::symlink_metadata(entry.path()).ok()?;
            meta.is_file().then(|| StructureFile {
                role: role.into(),
                path: relative(task, &entry.path()),
                bytes: meta.len(),
                file,
            })
        })
        .collect();
    files.sort_by(|a, b| a.file.cmp(&b.file));
    files
}

#[cfg(test)]
mod tests;
