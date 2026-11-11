//! Person-owned sheet replacement through the normal controller receipt path.
use crate::actions::{self, ActionRegistry};
use crate::{files, intake, AppError, AppResult};
use marinaframe_control::{controller, store::Store, types::Status, util};
use serde_json::{json, Value};
use std::path::Path;

pub fn read(task: &Path) -> Value {
    let Some(domain) = files::read_domain(task) else {
        return json!({"sheets":[], "outputs":[], "requests":[], "history":[]});
    };
    if let Some(review) = domain.get("sheet_review") {
        return review.clone();
    }
    // Older checkpoints can still offer Replace. The worker creates the full
    // dependency record on the first recovery action.
    let sheets: Vec<Value> = domain["sources"]
        .as_object()
        .into_iter()
        .flatten()
        .map(|(id, source)| {
            json!({"id":id, "label":id.replace('_', " "),
            "status":"ok", "reason":"", "file":source["file"],
            "sha256":source["sha256"], "version":1})
        })
        .collect();
    json!({"sheets":sheets, "outputs":[], "requests":[], "history":[]})
}

/// Return after the controller has opened the task; worker progress uses task events.
pub fn replace_sheet(
    registry: &ActionRegistry,
    task: &Path,
    sheet_id: &str,
    file: &Path,
) -> AppResult<()> {
    let review = read(task);
    let known = review["sheets"]
        .as_array()
        .is_some_and(|sheets| sheets.iter().any(|sheet| sheet["id"] == sheet_id))
        || files::read_domain(task).is_some_and(|domain| domain["sources"].get(sheet_id).is_some());
    if !known {
        return Err(AppError::new(
            "sheet_not_found",
            "This run has no such sheet.",
        ));
    }
    let file = intake::check_files(&[file.to_string_lossy().into_owned()])?.remove(0);
    let size = file
        .metadata()
        .map_err(|_| AppError::new("sheet_file", "Choose a drawing file."))?
        .len();
    if size == 0 || size > 256 * 1024 * 1024 {
        return Err(AppError::new(
            "sheet_file",
            "Choose a drawing file under 256 MB.",
        ));
    }
    let location = task.to_path_buf();
    let sheet_id = sheet_id.to_string();
    actions::spawn_with_store(
        registry,
        task,
        move || Store::open(&location),
        move |mut store| {
            if store.state.pending.is_some() {
                return Err("sheet_resume_pending".into());
            }
            let cancel = store.path.join("cancel.request");
            if cancel.exists() {
                std::fs::remove_file(cancel).map_err(|_| "cancel_clear")?;
                store.append("cancellation_acknowledged", json!({"actor":"operator"}))?;
            }
            let inbox = store.path.join("sheet-inbox");
            std::fs::create_dir_all(&inbox).map_err(|_| "sheet_inbox")?;
            let suffix = file
                .extension()
                .and_then(|s| s.to_str())
                .ok_or("sheet_file_type")?;
            let name = format!("{}.{}", util::nonce(), suffix);
            std::fs::copy(&file, inbox.join(&name)).map_err(|_| "sheet_copy")?;
            store.append(
                "sheet_replacement_requested",
                json!({"sheet_id":sheet_id,
                "actor":"person", "engineering_approved":false}),
            )?;
            if !controller::call_worker(
                &mut store,
                "replace_sheet",
                json!({
                    "sheet_id":sheet_id, "file":format!("sheet-inbox/{name}")
                }),
            )? {
                return Err("sheet_replacement_failed".into());
            }
            // A rejected replacement leaves the previous run usable. A partial retry
            // is also a normal draft state, with requests shown by get_task.
            let result = store.state.last_observation.clone();
            store.state.status = if result["ok"] == true {
                Status::DraftNotVerified
            } else {
                Status::Paused
            };
            store.state.termination_reason = Some(if result["ok"] == true {
                "sheet_replaced_review_required".into()
            } else {
                "sheet_replacement_needs_input".into()
            });
            store.append(
                "sheet_replacement_finished",
                json!({"sheet_id":sheet_id,
                "result":result, "engineering_approved":false}),
            )?;
            if result["ok"] != true {
                return Err("replacement_file_invalid".into());
            }
            Ok(())
        },
    )
}
