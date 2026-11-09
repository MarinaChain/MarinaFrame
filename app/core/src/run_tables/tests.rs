use super::*;

/// Files as `exports/tank_tables.py` writes them (one built tank, one tank not built).
const CAPACITY_CSV: &str = "# Draft stamp.\n# engineering_approved=false\n\
\"# Volumes are moulded volumes of the built tank solids; weight at 98 % fill.\"\n\
id,name,content,frames,built,volume_100_m3,volume_98_m3,density_t_m3,weight_98_t,lcg_m,tcg_m,vcg_m,\
max_free_surface_moment_tm,printed_volume_m3,source_name,source_content,source_frames,source_volume,\
source_density,source_centroid,notes\n\
db1,No 1 water ballast,water ballast,4...8,True,2.000,1.960,1.025,2.009,3.000,0.000,0.250,1.367,2.100,\
read,read,read,traced,read,traced,\n\
'=evil,\"Hold, aft\",dry,,False,,,,,,,,,,read,read,,guessed,,guessed,not built\n\
db2,No 2 water ballast,water ballast,8...10,True,1.000,0.980,,,5.000,0.000,0.200,,,read,read,read,traced,guessed,traced,\n";
const SOUNDING_CSV: &str = "# Draft stamp.\n\"# Tank db1: No 1 water ballast (water ballast).\"\n\
sounding_m,ullage_m,volume_m3,fill_pct,lcg_m\n\
0.000,0.500,0.000,0.00,\n0.250,0.250,1.000,50.00,3.000\n0.500,0.000,2.000,100.00,3.000\n";

fn task_with_tables(tmp: &tempfile::TempDir) -> PathBuf {
    let task = tmp.path().join("task");
    let tables = task.join(TANK_TABLES_FOLDER);
    std::fs::create_dir_all(&tables).unwrap();
    std::fs::write(tables.join("V_r0001_DRAFT_capacity_plan.csv"), CAPACITY_CSV).unwrap();
    std::fs::write(tables.join("V_r0001_DRAFT_sounding_db1.csv"), SOUNDING_CSV).unwrap();
    task
}

#[test]
fn csv_cells_may_hold_quoted_commas_quotes_and_line_breaks() {
    let rows = parse_csv("a,\"b, c\",\"say \"\"x\"\"\"\r\n\"two\nlines\",\n");
    assert_eq!(
        rows,
        [vec!["a", "b, c", "say \"x\""], vec!["two\nlines", ""]]
    );
}

#[test]
fn tank_ids_become_file_names_as_in_python() {
    assert_eq!(safe_name("db1"), "db1");
    assert_eq!(safe_name("=evil"), "evil");
    assert_eq!(safe_name("No 3 (P)"), "No-3-P");
    assert_eq!(safe_name("../x"), "x");
    assert_eq!(safe_name("##"), "vessel");
}

#[test]
fn the_capacity_plan_keeps_values_labels_and_group_totals() {
    let tmp = tempfile::tempdir().unwrap();
    let task = task_with_tables(&tmp);
    let plan = read_capacity_plan(&task).unwrap();
    assert!(!plan.engineering_approved);
    assert_eq!(plan.file, "tank_tables/V_r0001_DRAFT_capacity_plan.csv");
    assert_eq!(plan.stamp[1], "engineering_approved=false");
    assert_eq!(plan.rows.len(), 3);
    let db1 = &plan.rows[0];
    assert_eq!(
        (db1.id.as_str(), db1.content.as_str(), db1.frames.as_str()),
        ("db1", "water ballast", "4...8")
    );
    assert!(db1.built && db1.has_sounding);
    assert_eq!(
        (db1.volume_100_m3, db1.weight_98_t, db1.vcg_m),
        (Some(2.0), Some(2.009), Some(0.25))
    );
    assert_eq!(db1.sources["volume"], "traced");
    assert_eq!(db1.sources["weight"], "traced");
    // A formula-guarded text cell shows without its guard; an empty value has no number.
    let hold = &plan.rows[1];
    assert_eq!(
        (hold.id.as_str(), hold.name.as_str()),
        ("=evil", "Hold, aft")
    );
    assert!(!hold.built && !hold.has_sounding && hold.volume_100_m3.is_none());
    assert_eq!(hold.notes, "not built");
    assert!(!hold.sources.contains_key("frames"));
    // A guessed density makes the weight guessed.
    assert_eq!(plan.rows[2].sources["weight"], "guessed");
    assert_eq!(plan.groups.len(), 2);
    let ballast = &plan.groups[0];
    assert_eq!(
        (ballast.content.as_str(), ballast.tanks, ballast.built),
        ("water ballast", 2, 2)
    );
    assert!((ballast.volume_100_m3 - 3.0).abs() < 1e-9);
    assert!((ballast.weight_98_t - 2.009).abs() < 1e-9);
    assert_eq!((plan.groups[1].tanks, plan.groups[1].built), (1, 0));
}

#[test]
fn a_run_without_tank_tables_has_no_capacity_plan() {
    let tmp = tempfile::tempdir().unwrap();
    assert!(read_capacity_plan(tmp.path()).is_none());
    assert!(tank_model_path(tmp.path()).is_none());
}

#[test]
fn the_sounding_table_of_a_tank_has_its_columns_and_levels() {
    let tmp = tempfile::tempdir().unwrap();
    let task = task_with_tables(&tmp);
    let table = read_sounding_table(&task, "db1").unwrap();
    assert!(!table.engineering_approved);
    assert_eq!(table.file, "tank_tables/V_r0001_DRAFT_sounding_db1.csv");
    assert_eq!(table.columns[..3], ["sounding_m", "ullage_m", "volume_m3"]);
    assert_eq!(table.rows.len(), 3);
    assert_eq!(table.rows[0][4], None);
    assert_eq!(
        table.rows[2][..4],
        [Some(0.5), Some(0.0), Some(2.0), Some(100.0)]
    );
}

#[test]
fn a_sounding_table_is_read_only_for_a_tank_of_the_plan() {
    let tmp = tempfile::tempdir().unwrap();
    let task = task_with_tables(&tmp);
    for id in ["db2", "../db1", "nope"] {
        assert_eq!(
            read_sounding_table(&task, id).unwrap_err().code,
            "sounding_not_found",
            "{id}"
        );
    }
}

#[test]
fn structure_files_are_the_steel_tables_and_ocx_files() {
    let tmp = tempfile::tempdir().unwrap();
    let folder = tmp.path().join(STRUCTURE_FOLDER);
    std::fs::create_dir_all(&folder).unwrap();
    for name in [
        "b_DRAFT_steel_totals.csv",
        "b_DRAFT_steel_members.csv",
        "b_DRAFT.3docx",
        "notes.txt",
    ] {
        std::fs::write(folder.join(name), "x").unwrap();
    }
    let files = structure_files(tmp.path());
    let roles: Vec<&str> = files.iter().map(|f| f.role.as_str()).collect();
    assert_eq!(roles, ["ocx_structure", "steel_members", "steel_totals"]);
    assert_eq!(files[0].path, "structure/b_DRAFT.3docx");
    assert_eq!(files[0].bytes, 1);
}
