use super::*;
use serde_json::json;
use std::fs;
use std::os::unix::fs::symlink;
use std::path::PathBuf;

/// The start of a PNG file: enough for `files::png_size`.
fn png(width: u32, height: u32) -> Vec<u8> {
    let mut bytes = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR".to_vec();
    bytes.extend(width.to_be_bytes());
    bytes.extend(height.to_be_bytes());
    bytes.extend([8, 2, 0, 0, 0]);
    bytes
}

fn write(path: &Path, bytes: &[u8]) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, bytes).unwrap();
}

fn write_json(path: &Path, value: &Value) {
    write(path, &serde_json::to_vec(value).unwrap());
}

fn no_worker() -> intake::Worker<'static> {
    intake::Worker {
        python: "",
        source: None,
    }
}

/// A run started from a dropped set: `lines.png` (the spec page, replaced once in r0001) and
/// a two-page `tables.pdf`. Returns the temporary folder and the task folder in it.
fn intake_run() -> (tempfile::TempDir, PathBuf) {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path().join("task");
    write_json(
        &task.join("state.json"),
        &json!({"state": {"created_ms": 1000}}),
    );
    let sheet =
        |label: &str, scale: &str| json!({"type_label": label, "scale": {"main_text": scale}});
    write_json(
        &task.join("intake/intake.json"),
        &json!({"spec_page_id": "p1", "pages": [
            {"page_id": "p1", "file_name": "Lines plan.png", "page_index": 0, "width_px": 40, "height_px": 20,
             "dpi": 150.0, "source_file": "sources/Lines_plan.png", "sheet": sheet("Lines plan", "1:50")},
            {"page_id": "p2", "file_name": "tables.pdf", "page_index": 0, "source_file": "sources/tables.pdf",
             "sheet": sheet("Hydrostatic tables", "")},
            {"page_id": "p3", "file_name": "tables.pdf", "page_index": 1, "source_file": "sources/tables.pdf"}
        ]}),
    );
    write(&task.join("intake/sources/Lines_plan.png"), &png(40, 20));
    write(
        &task.join("intake/sources/tables.pdf"),
        b"%PDF-1.7 two pages",
    );
    write(&task.join("domain/input/source.png"), &png(40, 20));
    write(&task.join("domain/input/replacement-abc.png"), &png(80, 40));
    write(
        &task.join("domain/input/sheet-p2.pdf"),
        b"%PDF-1.7 two pages",
    );
    write(
        &task.join("domain/input/sheet-p3.pdf"),
        b"%PDF-1.7 two pages",
    );
    write(
        &task.join("domain/input/submitted_spec.json"),
        br#"{"source": {"file": "sources/Lines_plan.png"}}"#,
    );
    write(&task.join("domain/input/intake.json"), b"{}");
    write_json(
        &task.join("domain/sheet-revisions/abc/previous-state.json"),
        &json!({"sheet_review": {"sheets": [{"id": "source", "file": "source.png"}]}}),
    );
    write_json(
        &task.join("domain/state.json"),
        &json!({"revision": 2, "sources": {"source": {"file": "replacement-abc.png", "sha256": "new"}},
        "sheet_review": {"sheets": [
            {"id": "source", "label": "Lines plan.png", "status": "replaced", "file": "replacement-abc.png", "sha256": "new", "version": 2},
            {"id": "p2", "label": "tables.pdf", "status": "ok", "file": "sheet-p2.pdf", "sha256": "t", "version": 1, "page_index": 0},
            {"id": "p3", "label": "tables.pdf", "status": "ok", "file": "sheet-p3.pdf", "sha256": "t", "version": 1, "page_index": 1}
        ], "outputs": [], "requests": [], "history": [
            {"sheet_id": "source", "label": "Lines plan.png", "previous_revision_id": "r0000", "revision_id": "r0001",
             "previous_sha256": "old", "sha256": "new", "previous_state": "sheet-revisions/abc/previous-state.json",
             "time_ms": 5000, "engineering_approved": false}
        ]}}),
    );
    (tmp, task)
}

fn named<'a>(list: &'a SourceList, name: &str) -> &'a SourceFile {
    list.sources
        .iter()
        .find(|source| source.name == name)
        .unwrap_or_else(|| {
            panic!(
                "no source {name}: {:?}",
                list.sources.iter().map(|s| &s.name).collect::<Vec<_>>()
            )
        })
}

#[test]
fn an_intake_run_lists_dropped_files_replacements_and_spec_inputs() {
    let (_tmp, task) = intake_run();
    let list = list_sources(&task).unwrap();
    assert_eq!(list.revision.as_deref(), Some("r0002"));
    let names: Vec<&str> = list.sources.iter().map(|s| s.name.as_str()).collect();
    assert_eq!(
        names,
        [
            "Lines plan.png",
            "tables.pdf",
            "Lines plan.png, version 2",
            "spec.json",
            "intake.json"
        ]
    );

    let original = named(&list, "Lines plan.png");
    let replacement = named(&list, "Lines plan.png, version 2");
    assert_eq!(original.kind, SourceKind::Drawing);
    assert_eq!(original.role, "Main drawing");
    assert_eq!(original.status, SourceStatus::Replaced);
    assert_eq!(original.replaced_by.as_ref(), Some(&replacement.id));
    assert_eq!(
        (original.used_from.as_deref(), original.used_to.as_deref()),
        (Some("r0000"), Some("r0000"))
    );
    assert_eq!(original.added_ms, Some(1000));
    assert_eq!(original.pages.len(), 1);
    let page = &original.pages[0];
    assert_eq!(
        (page.sheet_type.as_deref(), page.scale.as_deref()),
        (Some("Lines plan"), Some("1:50"))
    );
    assert_eq!(
        (page.width_px, page.height_px, page.dpi),
        (Some(40), Some(20), Some(150.0))
    );
    assert!(page.replaced);
    // Not recorded for a dropped file: hashed from the bytes in the task.
    assert_eq!(
        original.sha256.as_deref(),
        Some(util::hash(&png(40, 20)).as_str())
    );
    assert_eq!(original.size_bytes, Some(png(40, 20).len() as u64));
    assert!(original.previewable);

    assert_eq!(replacement.status, SourceStatus::Current);
    assert_eq!(replacement.version, 2);
    assert_eq!(replacement.role, "Replacement for Lines plan.png");
    assert_eq!(replacement.sha256.as_deref(), Some("new"));
    assert_eq!(
        (
            replacement.used_from.as_deref(),
            replacement.used_to.as_deref()
        ),
        (Some("r0001"), None)
    );
    assert_eq!(replacement.added_ms, Some(5000));
    assert_eq!(replacement.pages[0].width_px, Some(80));

    let tables = named(&list, "tables.pdf");
    assert_eq!(tables.kind, SourceKind::Pdf);
    assert_eq!(tables.status, SourceStatus::Current);
    assert_eq!(
        tables.pages.iter().map(|p| p.index).collect::<Vec<_>>(),
        [0, 1]
    );
    assert_eq!(
        tables.pages[0].sheet_type.as_deref(),
        Some("Hydrostatic tables")
    );
    // An empty scale on the record is no scale.
    assert_eq!(tables.pages[0].scale, None);

    let spec = named(&list, "spec.json");
    assert_eq!(spec.kind, SourceKind::Spec);
    assert_eq!(spec.role, "Run spec written from the drawing set");
    assert_eq!(named(&list, "intake.json").role, "Drawing set record");
    // The UI gets ids, never locations.
    let sent = serde_json::to_string(&list).unwrap();
    assert!(!sent.contains("intake/sources") && !sent.contains("domain/input"));
}

#[test]
fn a_spec_run_from_an_older_checkpoint_names_the_file_the_spec_gave() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path().join("task");
    write(&task.join("domain/input/source.png"), &png(30, 10));
    write(
        &task.join("domain/input/submitted_spec.json"),
        br#"{"source": {"file": "drawings/harbour.png"}}"#,
    );
    // No sheet_review: `sheet_review::read` makes one sheet per captured source.
    write_json(
        &task.join("domain/state.json"),
        &json!({"revision": 1, "sources": {"source": {"file": "source.png", "sha256": "recorded"}}}),
    );
    let list = list_sources(&task).unwrap();
    assert_eq!(list.sources.len(), 2);
    let drawing = &list.sources[0];
    assert_eq!(drawing.name, "harbour.png");
    assert_eq!(drawing.role, "Main drawing");
    assert_eq!(drawing.status, SourceStatus::Current);
    assert_eq!(drawing.sha256.as_deref(), Some("recorded"));
    assert_eq!(drawing.pages[0].width_px, Some(30));
    assert_eq!(drawing.added_ms, None);
    assert_eq!(list.sources[1].role, "Run spec as given");
}

#[test]
fn a_sheet_the_intake_could_not_read_is_listed_without_a_file() {
    let tmp = tempfile::tempdir().unwrap();
    let task = tmp.path().join("task");
    write_json(
        &task.join("domain/state.json"),
        &json!({"revision": 0, "sources": {}, "sheet_review": {"sheets": [
            {"id": "unreadable-0", "label": "scan.tif", "status": "unreadable", "reason": "The file could not be read.",
             "file": null, "sha256": null, "version": 0}
        ], "history": []}}),
    );
    let list = list_sources(&task).unwrap();
    let scan = &list.sources[0];
    assert_eq!(scan.name, "scan.tif");
    assert_eq!(scan.status, SourceStatus::Unreadable);
    assert_eq!(scan.note.as_deref(), Some("The file could not be read."));
    assert!(!scan.previewable);
    let error = read_source_page(&task, &no_worker(), &scan.id, 0, PreviewSize::Full).unwrap_err();
    assert_eq!(error.code, "source_not_found");
}

#[test]
fn pages_and_spec_inputs_are_read_from_the_listed_file() {
    let (_tmp, task) = intake_run();
    let list = list_sources(&task).unwrap();
    let original = named(&list, "Lines plan.png");
    let shown = read_source_page(&task, &no_worker(), &original.id, 0, PreviewSize::Thumb).unwrap();
    assert_eq!(shown.mime, "image/png");
    assert_eq!(STANDARD.decode(shown.base64.unwrap()).unwrap(), png(40, 20));
    assert_eq!((shown.width, shown.height), (40, 20));

    let spec = named(&list, "spec.json");
    let text = read_source_page(&task, &no_worker(), &spec.id, 0, PreviewSize::Full).unwrap();
    assert_eq!(
        text.text.as_deref(),
        Some(r#"{"source": {"file": "sources/Lines_plan.png"}}"#)
    );
    assert_eq!(text.base64, None);

    // A PDF page goes to the worker's renderer (here: no Python configured).
    let tables = named(&list, "tables.pdf");
    let error =
        read_source_page(&task, &no_worker(), &tables.id, 1, PreviewSize::Full).unwrap_err();
    assert_eq!(error.code, "worker_python_missing");
    let error =
        read_source_page(&task, &no_worker(), &tables.id, 2, PreviewSize::Full).unwrap_err();
    assert_eq!(error.code, "source_page_missing");
    let error = read_source_page(
        &task,
        &no_worker(),
        "domain/input/source.png",
        0,
        PreviewSize::Full,
    )
    .unwrap_err();
    assert_eq!(error.code, "source_not_found");
}

#[test]
fn recorded_paths_outside_the_task_or_through_a_symlink_are_never_read() {
    let (tmp, task) = intake_run();
    write(&tmp.path().join("secret.png"), &png(9, 9));
    symlink(
        tmp.path().join("secret.png"),
        task.join("intake/sources/link.png"),
    )
    .unwrap();
    symlink(tmp.path(), task.join("intake/outside")).unwrap();
    let mut record: Value =
        serde_json::from_slice(&fs::read(task.join("intake/intake.json")).unwrap()).unwrap();
    let pages = record["pages"].as_array_mut().unwrap();
    for (id, file) in [
        ("p8", "../../secret.png"),
        ("p9", "sources/link.png"),
        ("p10", "outside/secret.png"),
    ] {
        pages.push(json!({"page_id": id, "file_name": file, "page_index": 0, "source_file": file}));
    }
    write_json(&task.join("intake/intake.json"), &record);

    let list = list_sources(&task).unwrap();
    for (name, code) in [
        ("../../secret.png", "unsafe_artifact_path"),
        ("sources/link.png", "artifact_symlink"),
        ("outside/secret.png", "artifact_symlink"),
    ] {
        let source = named(&list, name);
        assert!(!source.previewable, "{name}");
        assert_eq!(
            (source.size_bytes, source.sha256.as_deref()),
            (None, None),
            "{name}"
        );
        assert_eq!(
            source.note.as_deref(),
            Some("This file is not in the run folder.")
        );
        let error =
            read_source_page(&task, &no_worker(), &source.id, 0, PreviewSize::Full).unwrap_err();
        assert_eq!(error.code, code, "{name}");
    }

    // A previous state named by a record cannot point outside the domain folder either.
    let mut domain: Value =
        serde_json::from_slice(&fs::read(task.join("domain/state.json")).unwrap()).unwrap();
    domain["sheet_review"]["history"][0]["previous_state"] = json!("../../secret.json");
    write_json(
        &tmp.path().join("secret.json"),
        &json!({"sheet_review": {"sheets": [{"id": "source", "file": "../../../secret.png"}]}}),
    );
    write_json(&task.join("domain/state.json"), &domain);
    let list = list_sources(&task).unwrap();
    assert!(list
        .sources
        .iter()
        .all(|source| source.sha256.as_deref() != Some(util::hash(&png(9, 9)).as_str())));

    let linked = tmp.path().join("linked-task");
    symlink(&task, &linked).unwrap();
    assert_eq!(list_sources(&linked).unwrap_err().code, "invalid_task_root");
}
