use marinaframe_control::{
    controller, models, provider, store, table_reading, types, util, validation, worker,
};
use serde_json::json;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use types::*;
use util::Result;

fn arguments(raw: Vec<String>) -> Result<BTreeMap<String, String>> {
    if !raw.len().is_multiple_of(2) {
        return Err("options_require_values".into());
    }
    let mut args = BTreeMap::new();
    for pair in raw.as_chunks::<2>().0 {
        if !pair[0].starts_with("--") || args.insert(pair[0][2..].into(), pair[1].clone()).is_some()
        {
            return Err("invalid_or_duplicate_option".into());
        }
    }
    Ok(args)
}
fn take(args: &mut BTreeMap<String, String>, name: &str) -> Result<String> {
    args.remove(name).ok_or(format!("missing_option_{name}"))
}
fn boolean(args: &mut BTreeMap<String, String>, name: &str) -> Result<bool> {
    match args.remove(name).as_deref() {
        None | Some("false") => Ok(false),
        Some("true") => Ok(true),
        _ => Err(format!("invalid_boolean_{name}")),
    }
}
fn steps(args: &mut BTreeMap<String, String>) -> Result<Option<u64>> {
    args.remove("steps")
        .map(|v| v.parse::<u64>().map_err(|_| "invalid_step_boundary".into()))
        .transpose()
}
fn no_extra(args: &BTreeMap<String, String>) -> Result<()> {
    if args.is_empty() {
        Ok(())
    } else {
        Err("unknown_option".into())
    }
}
fn execute() -> Result<serde_json::Value> {
    let mut raw = std::env::args().skip(1);
    let command = raw.next().unwrap_or_else(|| "help".into());
    if command == "help" || command == "--help" {
        return Ok(
            json!({"program":"MarinaFrame 0.4.0 Rust authoritative controller","commands":{
        "run":"--task DIR --source SPEC --worker-python PYTHON [--worker-source SRC] [--policy deterministic|live] [--on-ambiguity abstain|draft] [--provider-transfer-basis TEXT] [--model deepseek-v4.1-flash|crouton-alpha-free[,FALLBACK]] [--model-review true] [--context stateless|conversation] [--max-context-tokens 8000..120000] [--investigation-thinking disabled|enabled] [--max-output-tokens 16..32768] [--request-wall-seconds 1..600] [--investigation-temperature 0..2] [--phase1-only true] [--inspection-workers 1..32] [--steps N]",
        "resume":"--task DIR [--continue-after-unknown true] [--clear-cancel true] [--steps N]",
        "step":"--task DIR --intervention JSON --actor human_operator|assistant_operator --note TEXT",
        "revise":"--task DIR --request FILE.json (operator mark-and-revise request; one focused model pass, see docs/APP_SPEC.md)",
        "force-keep":"--task DIR --revision ID (keep the not-kept edits of a revision anyway; recorded as operator-forced)",
        "status":"--task DIR","verify":"--task DIR","cancel":"--task DIR","recover-checkpoint":"--task DIR",
        "read-table":"--crops DIR --out NEW_DIR --provider-transfer-basis TEXT (live offset-table cell transcription; see docs/VISION_TABLE_READING.md)",
        "vision-request":"--request DIR --out NEW_DIR --provider-transfer-basis TEXT (one sheet_setup or build_review request; see docs/LLM_SETUP_AND_REVIEW.md)"},
        "automated_engineering_approval":false,"live_campaign_aggregate_caps":null}),
        );
    }
    let mut args = arguments(raw.collect())?;
    if command == "check-contract" {
        let path = take(&mut args, "file")?;
        no_extra(&args)?;
        let contract: validation::Contract =
            util::parse(&util::read_bounded(Path::new(&path), 262_144)?, 262_144)?;
        contract.check_shape()?;
        return Ok(
            json!({"schema_valid":true,"outcome":contract.outcome,"artifact_verification_performed":false,"engineering_approved":false}),
        );
    }
    if command == "provider-worker" {
        let path = PathBuf::from(take(&mut args, "response")?);
        let timeout = take(&mut args, "timeout")?
            .parse::<u64>()
            .map_err(|_| "invalid_request_timeout")?;
        no_extra(&args)?;
        provider::provider_worker(&path, timeout)?;
        return Ok(json!({"provider_worker":"finished"}));
    }
    if command == "read-table" {
        let crops = util::absolute(Path::new(&take(&mut args, "crops")?))?;
        let out = util::absolute(Path::new(&take(&mut args, "out")?))?;
        let basis = take(&mut args, "provider-transfer-basis")?;
        no_extra(&args)?;
        return table_reading::read_table(&crops, &out, &basis);
    }
    if command == "vision-request" {
        let request = util::absolute(Path::new(&take(&mut args, "request")?))?;
        let out = util::absolute(Path::new(&take(&mut args, "out")?))?;
        let basis = take(&mut args, "provider-transfer-basis")?;
        no_extra(&args)?;
        return provider::vision::vision_request(&request, &out, &basis);
    }
    let task = PathBuf::from(take(&mut args, "task")?);
    if command == "check-validation" {
        let observation =
            util::read_json(Path::new(&take(&mut args, "observation")?), 2 * 1024 * 1024)?;
        let domain = util::read_json(Path::new(&take(&mut args, "domain")?), 2 * 1024 * 1024)?;
        let context = util::read_json(Path::new(&take(&mut args, "context")?), 2 * 1024 * 1024)?;
        let audit_pin = args.remove("audit-pin");
        no_extra(&args)?;
        let contract = validation::assess(&task, &observation, &domain, &context)?;
        // Without --audit-pin this offline diagnostic cannot know the controller's
        // pin; it then reports readiness for every check except the pin.
        let ready = match &audit_pin {
            Some(pin) => validation::ready(&task, &observation, &domain, &context, Some(pin)),
            None => validation::ready_legacy_unpinned(&task, &observation, &domain, &context),
        };
        return Ok(
            json!({"well_formed_current_audit":true,"outcome":contract.outcome,
            "ready_for_human_review":ready.is_ok(),"audit_implementation_pinned":audit_pin.is_some(),"engineering_approved":false}),
        );
    }
    if command == "cancel" {
        no_extra(&args)?;
        if !task.is_dir() || task.is_symlink() {
            return Err("invalid_task_root".into());
        }
        if !task.join("cancel.request").exists() {
            util::atomic_json(
                &task.join("cancel.request"),
                &json!({"schema_version":"marinaframe.cancel.v1","requested_ms":util::now_ms()}),
                false,
            )?;
        }
        return Ok(json!({"cancellation_requested":true,"engineering_approved":false}));
    }
    if command == "recover-checkpoint" {
        no_extra(&args)?;
        return store::Store::recover_checkpoint(&task);
    }
    if command == "run" {
        let source = util::absolute(Path::new(&take(&mut args, "source")?))?;
        if !source.is_file() || source.is_symlink() {
            return Err("source_spec_missing_or_symlink".into());
        }
        let python = util::absolute(Path::new(&take(&mut args, "worker-python")?))?;
        if !python.is_file() {
            return Err("worker_python_missing".into());
        }
        let worker_source = args
            .remove("worker-source")
            .map(|s| util::absolute(Path::new(&s)).map(|p| p.to_string_lossy().into_owned()))
            .transpose()?;
        let policy = match args.remove("policy").as_deref() {
            None | Some("deterministic") => Policy::Deterministic,
            Some("live") => Policy::Live,
            _ => return Err("unknown_policy".into()),
        };
        // The CLI keeps `abstain` as its default, so scripted and frozen
        // benchmark runs behave as before; the desktop app starts `draft` runs.
        let on_ambiguity = match args.remove("on-ambiguity").as_deref() {
            None | Some("abstain") => OnAmbiguity::Abstain,
            Some("draft") => OnAmbiguity::Draft,
            _ => return Err("unknown_on_ambiguity".into()),
        };
        let basis = args.remove("provider-transfer-basis").unwrap_or_default();
        if basis.chars().count() > 1024 {
            return Err("authorization_basis_limit".into());
        }
        if policy == Policy::Live && basis.is_empty() {
            return Err("live_provider_transfer_basis_required".into());
        }
        // The vision-model veto sends drawing crops, so it needs a transfer basis.
        let model_review = boolean(&mut args, "model-review")?;
        if model_review && basis.is_empty() {
            return Err("model_review_requires_provider_transfer_basis".into());
        }
        let conversation = match args.remove("context").as_deref() {
            None | Some("stateless") => false,
            Some("conversation") => true,
            _ => return Err("invalid_investigation_context".into()),
        };
        let phase1_only = boolean(&mut args, "phase1-only")?;
        if phase1_only && (policy != Policy::Live || on_ambiguity != OnAmbiguity::Draft) {
            return Err("phase1_only_requires_live_draft".into());
        }
        let mut limits = OperationalLimits {
            phase1_only,
            investigation_conversation: conversation,
            investigation_thinking: match args.remove("investigation-thinking").as_deref() {
                None | Some("disabled") => false,
                Some("enabled") => true,
                _ => return Err("invalid_investigation_thinking".into()),
            },
            ..OperationalLimits::default()
        };
        if let Some(value) = args.remove("max-output-tokens") {
            limits.max_output_tokens_per_request =
                value.parse().map_err(|_| "invalid_max_output_tokens")?;
        }
        if let Some(value) = args.remove("investigation-temperature") {
            limits.investigation_temperature = value
                .parse()
                .map_err(|_| "invalid_investigation_temperature")?;
        }
        if let Some(value) = args.remove("max-context-tokens") {
            limits.max_context_tokens = value.parse().map_err(|_| "invalid_context_budget")?;
        }
        limits.validate()?;
        // Ordered models: the first is used until it is rate limited, then the
        // next. The default is the desktop app's list (models::DEFAULT_MODELS).
        let mut models = match args.remove("model") {
            Some(list) => models::parse_list(&list)?,
            None => models::DEFAULT_MODELS.map(String::from).to_vec(),
        };
        let model = models.remove(0);
        // Unset: no bound; the machine-wide worker pool shares the cores.
        let inspection_workers = args
            .remove("inspection-workers")
            .map(|value| {
                value
                    .parse::<u32>()
                    .ok()
                    .filter(|n| (1..=worker::MAX_INSPECTION_WORKERS).contains(n))
                    .ok_or("invalid_inspection_workers")
            })
            .transpose()?;
        let count = steps(&mut args)?;
        no_extra(&args)?;
        let config = Config {
            worker_python: python.to_string_lossy().into_owned(),
            worker_source,
            source_spec: source.to_string_lossy().into_owned(),
            policy,
            limits,
            provider_transfer_authorized: !basis.is_empty(),
            authorization_basis: basis,
            model,
            fallback_models: models,
            binary_sha256: util::file_hash(&std::env::current_exe().map_err(|_| "binary_path")?)?,
            on_ambiguity,
            inspection_workers,
        };
        let mut store = store::Store::create(&task, controller::new_state(config))?;
        if model_review {
            store.append(
                controller::model_review::REQUESTED_EVENT,
                json!({"can_veto":true,"can_approve":false,"engineering_approved":false}),
            )?;
        }
        if controller::initialize(&mut store)? {
            controller::run_loop(&mut store, count)?;
        }
        return Ok(controller::summary(&store));
    }
    let mut store = store::Store::open(&task)?;
    match command.as_str() {
        "status" => {
            no_extra(&args)?;
            Ok(controller::summary(&store))
        }
        "verify" => {
            no_extra(&args)?;
            store.verify(false)
        }
        "resume" => {
            let names = [
                "expected-head-sha256",
                "expected-generation-id",
                "expected-revision-id",
                "expected-task-id",
            ];
            if names.iter().any(|name| args.contains_key(*name)) {
                let expected = names
                    .iter()
                    .map(|name| take(&mut args, name))
                    .collect::<Result<Vec<_>>>()?;
                if Some(&expected[0]) != store.head.as_ref()
                    || Some(&expected[1]) != store.state.generation_id.as_ref()
                    || Some(&expected[2]) != store.state.revision_id.as_ref()
                    || expected[3] != store.state.task_id
                {
                    return Err("stale_or_foreign_intervention".into());
                }
            }
            let unknown = boolean(&mut args, "continue-after-unknown")?;
            let clear = boolean(&mut args, "clear-cancel")?;
            let count = steps(&mut args)?;
            no_extra(&args)?;
            controller::resume(&mut store, unknown, clear, count)?;
            Ok(controller::summary(&store))
        }
        "step" => {
            let path = take(&mut args, "intervention")?;
            let actor = take(&mut args, "actor")?;
            let note = take(&mut args, "note")?;
            no_extra(&args)?;
            let input = util::parse(&util::read_bounded(Path::new(&path), 65_536)?, 65_536)?;
            controller::intervene(&mut store, input, &actor, &note)?;
            Ok(controller::summary(&store))
        }
        "revise" => {
            let path = take(&mut args, "request")?;
            no_extra(&args)?;
            let request = util::parse(&util::read_bounded(Path::new(&path), 65_536)?, 65_536)?;
            let revision = controller::revision::revise(&mut store, request)?;
            Ok(json!({"revision":revision,"task":controller::summary(&store)}))
        }
        "force-keep" => {
            let revision_id = take(&mut args, "revision")?;
            no_extra(&args)?;
            let forced = controller::revision::force_keep(&mut store, &revision_id)?;
            Ok(json!({"revision":forced,"task":controller::summary(&store)}))
        }
        _ => Err("unknown_command".into()),
    }
}
fn main() {
    worker::install_signals();
    match execute() {
        Ok(value) => println!("{}", serde_json::to_string(&value).unwrap()),
        Err(code) => {
            eprintln!(
                "{}",
                json!({"ok":false,"error_code":code,"engineering_approved":false})
            );
            std::process::exit(2);
        }
    }
}
