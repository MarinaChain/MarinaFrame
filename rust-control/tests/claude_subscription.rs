//! `marinaframe provider-worker` on the Claude subscription transport, with a
//! fake `claude` executable: a shell script that records its arguments,
//! environment and stdin, and prints a canned stream-json answer. No network.
use marinaframe_control::models::{self, CLAUDE_CLI_ENDPOINT, CLAUDE_SONNET_5_5};
use marinaframe_control::provider::{
    self, claude_cli, ImageReceipt, ProviderInput, Purpose, Receipt, RequestState,
};
use serde_json::{json, Value};
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// A real 2x2 white grayscale PNG, as Pillow writes it.
const PNG: &[u8] = &[
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x02, 0x08, 0x00, 0x00, 0x00, 0x00, 0x57, 0xdd, 0x52,
    0xf8, 0x00, 0x00, 0x00, 0x0e, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0xfc, 0xcf, 0xc0, 0xc4,
    0xc0, 0x00, 0x00, 0x05, 0x0d, 0x01, 0x03, 0xb8, 0x4a, 0x5c, 0x6f, 0x00, 0x00, 0x00, 0x00, 0x49,
    0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
];
/// A value that must never reach the CLI's environment.
const GO_KEY_SENTINEL: &str = "opencode-go-sentinel-value";

fn sha256(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    format!("{:x}", Sha256::digest(bytes))
}

/// The CLI's stream-json lines for one result. `tools` is the init tool list.
fn stream(tools: &[&str], result: Value) -> String {
    let init = json!({"type":"system","subtype":"init","tools":tools,"mcp_servers":[],
        "apiKeySource":"none","model":CLAUDE_SONNET_5_5});
    let event = json!({"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}});
    format!("{init}\n{event}\n{result}\n")
}

fn answer_result() -> Value {
    let answer = json!({"tool":"survey_sheet","arguments":{},"reason":"Read the sheet first."});
    json!({"type":"result","subtype":"success","is_error":false,"api_error_status":null,
        "stop_reason":"tool_use","result":answer.to_string(),"structured_output":answer,
        "uuid":"0f4c2d9e-1111-4222-8333-944455556666","total_cost_usd":0.0321,"duration_ms":2100,
        "usage":{"input_tokens":3,"cache_creation_input_tokens":1500,"cache_read_input_tokens":200,"output_tokens":40},
        "modelUsage":{CLAUDE_SONNET_5_5:{"inputTokens":3,"outputTokens":40,"costUSD":0.0321}}})
}

/// Write a fake `claude` that records what it got and prints `output`.
fn fake_claude(dir: &Path, output: &str) -> PathBuf {
    std::fs::write(dir.join("output.jsonl"), output).unwrap();
    let script = dir.join("claude");
    let d = dir.display();
    std::fs::write(
        &script,
        format!(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > '{d}/args.txt'\nenv > '{d}/env.txt'\ncat > '{d}/stdin.jsonl'\ncat '{d}/output.jsonl'\n"
        ),
    )
    .unwrap();
    std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
    script
}

fn input(purpose: Purpose) -> ProviderInput {
    let url = format!("data:image/png;base64,{}", base64_encode(PNG));
    let messages = json!([{"role":"system","content":purpose.prompt()},
        {"role":"user","content":[{"type":"text","text":"{\"observation\":{}}"},
            {"type":"image_url","image_url":{"url":url,"detail":"original"}}]}]);
    ProviderInput {
        protocol: provider::PROTOCOL.into(),
        request_id: "request-claude-1".into(),
        source_manifest_sha256: "a".repeat(64),
        generation_id: "generation-1".into(),
        revision_id: "r0001".into(),
        observation_sha256: "c".repeat(64),
        images: vec![ImageReceipt {
            artifact_id: "source-page".into(),
            path: "views/source.png".into(),
            sha256: sha256(PNG),
            bytes: PNG.len() as u64,
            mime_type: "image/png".into(),
            evidence_kind: "source_page".into(),
            view: None,
            generation_id: None,
            revision_id: None,
            step_sha256: None,
            pixels_attached: true,
            crop_box_px: None,
            pixel_size: Some([2, 2]),
        }],
        payload: models::payload(CLAUDE_SONNET_5_5, 4096, false, 0.0, messages).unwrap(),
        attempt: 1,
        retry_of: None,
        purpose,
    }
}

fn base64_encode(bytes: &[u8]) -> String {
    use base64::{engine::general_purpose::STANDARD, Engine};
    STANDARD.encode(bytes)
}

/// Run the provider worker with the fake CLI; return the receipt.
fn run_worker(dir: &Path, claude: &Path, input: &ProviderInput) -> Receipt {
    let response = dir.join("receipt.json");
    let mut child = Command::new(env!("CARGO_BIN_EXE_marinaframe"))
        .args(["provider-worker", "--response"])
        .arg(&response)
        .args(["--timeout", "30"])
        .env(claude_cli::BINARY_ENV, claude)
        .env("OPENCODE_API_KEY", GO_KEY_SENTINEL)
        .env("ANTHROPIC_API_KEY", GO_KEY_SENTINEL)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(&serde_json::to_vec(input).unwrap())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&std::fs::read(&response).unwrap()).unwrap()
}

#[test]
fn a_decision_goes_through_the_cli_without_tools_or_keys() {
    let tmp = tempfile::tempdir().unwrap();
    let claude = fake_claude(tmp.path(), &stream(&["StructuredOutput"], answer_result()));
    let request = input(Purpose::Investigation);
    let receipt = run_worker(tmp.path(), &claude, &request);

    // Request build: print mode, no tools, the decision schema, the system prompt.
    let args: Vec<String> = std::fs::read_to_string(tmp.path().join("args.txt"))
        .unwrap()
        .lines()
        .map(String::from)
        .collect();
    let after = |flag: &str| args[args.iter().position(|a| a == flag).unwrap() + 1].clone();
    assert_eq!(args[0], "-p");
    assert_eq!(after("--model"), CLAUDE_SONNET_5_5);
    assert_eq!(after("--tools"), "");
    assert_eq!(after("--json-schema"), claude_cli::DECISION_SCHEMA);
    assert_eq!(after("--input-format"), "stream-json");
    assert!(args.iter().any(|a| a == "--no-session-persistence"));
    assert!(args.iter().any(|a| a.starts_with("You are MarinaFrame")));
    // The image goes in as a base64 content block of the one user message.
    let stdin: Value =
        serde_json::from_str(&std::fs::read_to_string(tmp.path().join("stdin.jsonl")).unwrap())
            .unwrap();
    let image = &stdin["message"]["content"][1];
    assert_eq!(image["type"], "image");
    assert_eq!(image["source"]["data"], base64_encode(PNG));
    // No key and no inherited variable reaches the CLI.
    let environment = std::fs::read_to_string(tmp.path().join("env.txt")).unwrap();
    assert!(!environment.contains(GO_KEY_SENTINEL));
    assert!(!environment.contains("OPENCODE_API_KEY"));
    assert!(environment.contains("CLAUDE_CODE_MAX_OUTPUT_TOKENS=4096"));

    // Receipt: transport, model, usage, cost fields, duration and the decision.
    assert_eq!(
        receipt.state,
        RequestState::Completed,
        "{:?}",
        receipt.error_code
    );
    assert_eq!(receipt.endpoint, CLAUDE_CLI_ENDPOINT);
    assert_eq!(receipt.requested_model, CLAUDE_SONNET_5_5);
    assert_eq!(receipt.returned_model.as_deref(), Some(CLAUDE_SONNET_5_5));
    assert_eq!(receipt.http_status, Some(200));
    assert_eq!(
        receipt.usage,
        json!({"prompt_tokens":1703,"completion_tokens":40,"total_tokens":1743,
            "cost":0.0,"list_cost":0.0321,"billing_source":"subscription"})
    );
    assert_eq!(receipt.observed_cost_usd, Some(0.0));
    assert!(receipt.latency_seconds > 0.0);
    assert_eq!(
        receipt.credential_selection.as_ref().unwrap()["api_key"],
        false
    );
    assert_eq!(receipt.decision.as_ref().unwrap().tool, "survey_sheet");
    assert!(provider::model_bound(&receipt, &request));
    // The stored body is the CLI output; the receipt can be re-derived from it.
    let body = std::fs::read(tmp.path().join("receipt.body")).unwrap();
    provider::verify_receipt_body(&receipt, &body).unwrap();
}

#[test]
fn a_subscription_limit_is_a_rate_limit() {
    let tmp = tempfile::tempdir().unwrap();
    let limited = json!({"type":"result","subtype":"success","is_error":true,"api_error_status":429,
        "result":"You've hit your limit · resets 3pm","uuid":"result-2",
        "usage":{"input_tokens":0,"output_tokens":0},"modelUsage":{}});
    let claude = fake_claude(tmp.path(), &stream(&["StructuredOutput"], limited));
    let receipt = run_worker(tmp.path(), &claude, &input(Purpose::Investigation));
    assert_eq!(receipt.state, RequestState::Failed);
    assert_eq!(receipt.error_code.as_deref(), Some("provider_rate_limited"));
    assert_eq!(receipt.http_status, Some(429));
    assert!(models::rate_limited(&receipt));
}

#[test]
fn invalid_structured_output_is_a_refused_reply_not_a_transport_failure() {
    // Sonnet 5.5 live: five structured-output attempts with unbalanced braces.
    let tmp = tempfile::tempdir().unwrap();
    let exhausted = json!({"type":"result","subtype":"error_max_structured_output_retries",
        "is_error":true,"api_error_status":null,"terminal_reason":"structured_output_retry_exhausted",
        "uuid":"result-3","usage":{"input_tokens":35060,"output_tokens":1800},
        "modelUsage":{CLAUDE_SONNET_5_5:{"inputTokens":35060,"outputTokens":1800}}});
    let claude = fake_claude(tmp.path(), &stream(&["StructuredOutput"], exhausted));
    let receipt = run_worker(tmp.path(), &claude, &input(Purpose::Investigation));
    assert_eq!(receipt.state, RequestState::Failed);
    assert_eq!(
        receipt.error_code.as_deref(),
        Some(claude_cli::INVALID_STRUCTURED_OUTPUT)
    );
    // HTTP 200 from the requested model: the controller returns it to the model.
    assert_eq!(receipt.http_status, Some(200));
    assert!(provider::returned_requested_model(&receipt));
    assert!(!models::rate_limited(&receipt));
}

#[test]
fn a_cli_that_offers_tools_is_refused() {
    let tmp = tempfile::tempdir().unwrap();
    let claude = fake_claude(
        tmp.path(),
        &stream(&["Bash", "StructuredOutput"], answer_result()),
    );
    let receipt = run_worker(tmp.path(), &claude, &input(Purpose::Investigation));
    assert_eq!(receipt.state, RequestState::Failed);
    assert_eq!(
        receipt.error_code.as_deref(),
        Some("provider_cli_configuration")
    );
    assert!(receipt.decision.is_none());
}

#[test]
fn another_model_answering_is_refused() {
    let tmp = tempfile::tempdir().unwrap();
    let mut result = answer_result();
    result["modelUsage"] = json!({"claude-opus-5-5":{"inputTokens":3}});
    let claude = fake_claude(tmp.path(), &stream(&["StructuredOutput"], result));
    let receipt = run_worker(tmp.path(), &claude, &input(Purpose::Investigation));
    assert_eq!(
        receipt.error_code.as_deref(),
        Some("provider_model_identity")
    );
    assert!(!models::rate_limited(&receipt));
}

#[test]
fn a_missing_cli_leaves_the_request_not_sent() {
    let tmp = tempfile::tempdir().unwrap();
    let response = tmp.path().join("receipt.json");
    let mut child = Command::new(env!("CARGO_BIN_EXE_marinaframe"))
        .args(["provider-worker", "--response"])
        .arg(&response)
        .args(["--timeout", "30"])
        .env(claude_cli::BINARY_ENV, tmp.path().join("no-such-claude"))
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(&serde_json::to_vec(&input(Purpose::Investigation)).unwrap())
        .unwrap();
    child.wait().unwrap();
    let receipt: Receipt = serde_json::from_slice(&std::fs::read(&response).unwrap()).unwrap();
    assert_eq!(receipt.state, RequestState::NotSent);
    assert_eq!(receipt.error_code.as_deref(), Some("provider_cli_missing"));
}
