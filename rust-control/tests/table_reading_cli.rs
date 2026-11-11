//! `marinaframe read-table` end to end without network: no provider key is
//! available, so the provider worker records a not-sent receipt and the run
//! stops. The request, receipt and reading record must still be complete.
use serde_json::{json, Value};
use std::path::Path;
use std::process::Command;

/// A real 2x2 white grayscale PNG, as Pillow writes it.
const PNG: &[u8] = &[
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x02, 0x08, 0x00, 0x00, 0x00, 0x00, 0x57, 0xdd, 0x52,
    0xf8, 0x00, 0x00, 0x00, 0x0e, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0xfc, 0xcf, 0xc0, 0xc4,
    0xc0, 0x00, 0x00, 0x05, 0x0d, 0x01, 0x03, 0xb8, 0x4a, 0x5c, 0x6f, 0x00, 0x00, 0x00, 0x00, 0x49,
    0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
];

fn sha256(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    format!("{:x}", Sha256::digest(bytes))
}

fn crops(dir: &Path, cells: usize) {
    std::fs::create_dir(dir).unwrap();
    let mut entries = vec![];
    for i in 0..cells {
        let name = format!("c000-{i:03}.png");
        std::fs::write(dir.join(&name), PNG).unwrap();
        entries.push(
            json!({"cell_id":format!("c000-{i:03}"),"section_id":"st-0","cell_index":i,
            "crop_file":name,"sha256":sha256(PNG),"bytes":PNG.len(),"width":2,"height":2}),
        );
    }
    let manifest = json!({"schema_version":"marinaframe.table_crops.v1","source_sha256":"a".repeat(64),
        "table_value_units":"feet_inches_eighths","engineering_approved":false,"cells":entries});
    std::fs::write(dir.join("manifest.json"), manifest.to_string()).unwrap();
}

fn read_table(crops: &Path, out: &Path, basis: Option<&str>) -> std::process::Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_marinaframe"));
    command
        .arg("read-table")
        .arg("--crops")
        .arg(crops)
        .arg("--out")
        .arg(out);
    if let Some(basis) = basis {
        command.arg("--provider-transfer-basis").arg(basis);
    }
    for name in [
        "OPENCODE_API_KEY",
        "OPENCODE_API_KEY_2",
        "OPENCODE_API_KEY_3",
    ] {
        command.env_remove(name);
    }
    command.output().unwrap()
}

#[test]
fn without_a_key_the_first_request_is_not_sent_and_the_run_stops() {
    let root = tempfile::tempdir().unwrap();
    crops(&root.path().join("crops"), 6);
    let out = root.path().join("reading");
    let output = read_table(
        &root.path().join("crops"),
        &out,
        Some("No-network test fixture"),
    );
    assert!(output.status.success(), "{output:?}");
    let record: Value =
        serde_json::from_slice(&std::fs::read(out.join("table_reading.json")).unwrap()).unwrap();
    assert_eq!(record["engineering_approved"], false);
    assert_eq!(record["stop_reason"], "provider_not_sent");
    let counts = &record["counts"];
    assert_eq!(counts["cells_requested"], 6);
    assert_eq!(counts["cells_unread"], 6);
    assert_eq!(counts["requests_intended"], 1);
    assert_eq!(counts["requests_not_sent"], 1);
    assert_eq!(counts["requests_completed"], 0);
    let receipts = record["receipts"].as_array().unwrap();
    assert_eq!(receipts.len(), 1);
    let receipt = &receipts[0];
    assert_eq!(receipt["state"], "not_sent");
    assert_eq!(receipt["purpose"], "table_transcription");
    assert_eq!(receipt["http_status"], Value::Null);
    // The first batch holds the per-request image limit (4) of cell crops.
    let images = receipt["images"].as_array().unwrap();
    assert_eq!(images.len(), 4);
    assert!(images
        .iter()
        .all(|i| i["evidence_kind"] == "table_cell_crop" && i["sha256"] == sha256(PNG)));
    // The request on disk is what would have been sent: crop pixels inline.
    let id = receipt["request_id"].as_str().unwrap();
    let request: Value =
        serde_json::from_slice(&std::fs::read(out.join(format!("requests/{id}.json"))).unwrap())
            .unwrap();
    let content = request["payload"]["messages"][1]["content"]
        .as_array()
        .unwrap();
    assert_eq!(content.len(), 5);
    assert!(content[1]["image_url"]["url"]
        .as_str()
        .unwrap()
        .starts_with("data:image/png;base64,"));
    assert_eq!(receipt["prompt_sha256"], record["prompt_sha256"]);
}

#[test]
fn output_must_be_new_and_transfer_basis_is_required() {
    let root = tempfile::tempdir().unwrap();
    crops(&root.path().join("crops"), 1);
    let output = read_table(&root.path().join("crops"), &root.path().join("x"), None);
    assert!(!output.status.success());
    let output = read_table(
        &root.path().join("crops"),
        &root.path().join("crops"),
        Some("No-network test fixture"),
    );
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("table_reading_output_exists"));
}
