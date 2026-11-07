//! `marinaframe vision-request` end to end without network: no provider key is
//! available, so the provider worker records a not-sent receipt. The request,
//! receipt and reading record must still be complete and bound to the images.
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

fn request(dir: &Path, purpose: &str, views: &[&str], approved: bool) {
    std::fs::create_dir(dir).unwrap();
    let mut images = vec![];
    for (i, view) in views.iter().enumerate() {
        let name = format!("image-{i}.png");
        std::fs::write(dir.join(&name), PNG).unwrap();
        images.push(json!({"image_id":format!("s{i:03}"),"file":name,"sha256":sha256(PNG),
            "bytes":PNG.len(),"width":2,"height":2,"view":view,"crop_box_px":[0,0,2,2]}));
    }
    let manifest = json!({"schema_version":"marinaframe.vision_request.v1","purpose":purpose,
        "source_sha256":"a".repeat(64),"engineering_approved":approved,
        "context":{"note":"test"},"images":images});
    std::fs::write(dir.join("request.json"), manifest.to_string()).unwrap();
}

fn vision_request(dir: &Path, out: &Path) -> std::process::Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_marinaframe"));
    command
        .arg("vision-request")
        .arg("--request")
        .arg(dir)
        .arg("--out")
        .arg(out)
        .arg("--provider-transfer-basis")
        .arg("test without network");
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
fn without_a_key_the_review_request_is_receipted_as_not_sent() {
    let root = tempfile::tempdir().unwrap();
    let dir = root.path().join("request");
    let out = root.path().join("out");
    request(&dir, "build_review", &["station:s000", "station:s001"], false);
    let output = vision_request(&dir, &out);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let record: Value =
        serde_json::from_slice(&std::fs::read(out.join("vision_reading.json")).unwrap()).unwrap();
    assert_eq!(record["engineering_approved"], false);
    assert_eq!(record["purpose"], "build_review");
    assert!(record["reply"].is_null());
    assert_eq!(record["usage"]["requests_intended"], 1);
    assert_eq!(record["usage"]["requests_not_sent"], 1);
    let receipt = &record["receipts"][0];
    assert_eq!(receipt["state"], "not_sent");
    assert_eq!(receipt["purpose"], "build_review");
    assert_eq!(receipt["images"].as_array().unwrap().len(), 2);
    assert_eq!(receipt["images"][0]["sha256"], sha256(PNG));
    assert_eq!(
        receipt["images"][0]["evidence_kind"],
        "build_review_overlay"
    );
    // The output directory is never reused.
    assert!(!vision_request(&dir, &out).status.success());
}

#[test]
fn request_manifests_cannot_claim_approval_or_change_purpose() {
    let root = tempfile::tempdir().unwrap();
    for (name, purpose, views, approved) in [
        ("approved", "build_review", vec!["station:s000"], true),
        ("decision", "model_decision", vec!["station:s000"], false),
        ("table", "table_transcription", vec!["station:s000"], false),
        // A setup request has exactly one image.
        ("two", "sheet_setup", vec!["sheet_overview", "panel:P1"], false),
    ] {
        let dir = root.path().join(name);
        request(&dir, purpose, &views, approved);
        let output = vision_request(&dir, &root.path().join(format!("{name}-out")));
        assert!(!output.status.success(), "{name} was accepted");
        assert!(!root.path().join(format!("{name}-out/vision_reading.json")).exists());
    }
}
