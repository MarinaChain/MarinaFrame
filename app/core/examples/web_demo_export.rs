//! Export finished runs for the static, read-only web demo (docs/WEB_DEMO.md).
//!
//!     cargo run --release -p marinaframe-app-core --example web_demo_export -- \
//!         --runs <runs folder> --out <data folder> --worker-python <python> \
//!         [--worker-source <repo>/src] [--config <app config folder>] <slug> [<slug> ...]
//!
//! `--config` is the app config folder the runs were reviewed with: a person's part reviews
//! and sign-off live there, not in the run folder. It is copied to a throwaway folder first,
//! so the exporter never writes into it.
//!
//! For each run folder `<runs>/<slug>` this calls the same read commands the desktop app
//! calls (`Backend`), so the demo shows exactly what the app shows, and writes:
//!
//!   <out>/runs/<slug>/task.json        get_task
//!   <out>/runs/<slug>/events.json      get_events (after 0)
//!   <out>/runs/<slug>/live.json        get_live_steps (after 0)
//!   <out>/runs/<slug>/sections.json    get_hull_sections, keyed by every revision id and path
//!   <out>/runs/<slug>/sources.json     list_sources
//!   <out>/runs/<slug>/pages.json       read_source_page facts, keyed "<source>|<page>|<size>"
//!   <out>/runs/<slug>/pages/...        the page images (PNG) those facts name
//!   <out>/runs/<slug>/exports.json     list_exports, keyed by revision
//!   <out>/runs/<slug>/exports/<rev>/   the exported files of the allowed kinds
//!   <out>/runs/<slug>/tables.json      sounding_table, keyed by tank id
//!   <out>/runs/<slug>/files/<path>     every image, STL or GLB artifact the JSON names
//!   <out>/tasks.json                   list_tasks of the exported runs
//!
//! With `--stage-ui <app/ui> <target>` instead, it stages the UI by the release rules
//! (`release_ui::stage`: only index.html, styles.css, js/, vendor/ and assets/, UI file types,
//! no links, no file above 1 MB) and prints every problem; it exits 1 when there is one.
//!
//! Absolute paths of this computer are replaced with `/MarinaFrame/runs/<slug>`; the build
//! script (scripts/build_web_demo.py) refuses a bundle in which any local path is left.
//! This tool only reads the run folders. It writes nothing into them.
use marinaframe_app_core::sources::PreviewSize;
use marinaframe_app_core::{artifact, AppPaths, Backend};
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

/// The task id the demo shows instead of the local run folder.
const DEMO_RUNS_FOLDER: &str = "/MarinaFrame/runs";
/// The notice id of "A different build of MarinaFrame made this run" (app/core/src/view.rs).
const OTHER_BUILD_NOTICE: &str = "other-build";
/// Export kinds that are copied for download: CAD, mesh, report and table files. The
/// package manifest and the zip package are left out (the manifest names local paths).
const DOWNLOAD_EXTENSIONS: [&str; 8] = ["step", "stp", "glb", "stl", "pdf", "csv", "dxf", "iges"];

struct Options {
    runs: PathBuf,
    out: PathBuf,
    worker_python: String,
    worker_source: Option<PathBuf>,
    config: Option<PathBuf>,
    slugs: Vec<String>,
}

fn parse_options() -> Result<Options, String> {
    let mut runs = None;
    let mut out = None;
    let mut worker_python = None;
    let mut worker_source = None;
    let mut config = None;
    let mut slugs = vec![];
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        let mut value = || args.next().ok_or(format!("{arg} needs a value"));
        match arg.as_str() {
            "--runs" => runs = Some(PathBuf::from(value()?)),
            "--out" => out = Some(PathBuf::from(value()?)),
            "--worker-python" => worker_python = Some(value()?),
            "--worker-source" => worker_source = Some(PathBuf::from(value()?)),
            "--config" => config = Some(PathBuf::from(value()?)),
            _ if arg.starts_with("--") => return Err(format!("unknown option {arg}")),
            _ => slugs.push(arg),
        }
    }
    Ok(Options {
        runs: runs.ok_or("--runs is required")?,
        out: out.ok_or("--out is required")?,
        worker_python: worker_python.ok_or("--worker-python is required")?,
        worker_source,
        config,
        slugs,
    })
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("--stage-ui") {
        let [_, source, target] = args.as_slice() else {
            eprintln!("web_demo_export: --stage-ui <app/ui> <target>");
            std::process::exit(2);
        };
        let problems =
            marinaframe_app_core::release_ui::stage(Path::new(source), Path::new(target));
        for problem in &problems {
            eprintln!("web_demo_export: release UI: {problem}");
        }
        std::process::exit(if problems.is_empty() { 0 } else { 1 });
    }
    let options = match parse_options() {
        Ok(options) => options,
        Err(message) => {
            eprintln!("web_demo_export: {message}");
            std::process::exit(2);
        }
    };
    if let Err(message) = run(&options) {
        eprintln!("web_demo_export: {message}");
        std::process::exit(1);
    }
}

fn run(options: &Options) -> Result<(), String> {
    let runs = options
        .runs
        .canonicalize()
        .map_err(|e| format!("{}: {e}", options.runs.display()))?;
    // A throwaway config folder: the exporter must not read or change the person's settings.
    let config = std::env::temp_dir().join(format!("marinaframe-web-demo-{}", std::process::id()));
    if config.exists() {
        std::fs::remove_dir_all(&config).map_err(|e| e.to_string())?;
    }
    std::fs::create_dir_all(&config).map_err(|e| e.to_string())?;
    if let Some(reviewed) = &options.config {
        copy_folder(reviewed, &config)?;
    }
    let paths = AppPaths {
        config_dir: config.clone(),
        data_dir: config.clone(),
        repo_root: None,
    };
    let backend = Backend::new(paths, options.worker_source.clone(), None);
    let mut settings = backend.get_settings();
    settings.runs_folder = runs.to_string_lossy().into_owned();
    settings.worker_python = options.worker_python.clone();
    settings.ai_drafting = false;
    backend.set_settings(settings).map_err(|e| e.message)?;

    let mut summaries = vec![];
    for slug in &options.slugs {
        let task_dir = runs.join(slug);
        if !task_dir.is_dir() {
            return Err(format!("run folder {} not found", task_dir.display()));
        }
        let out = options.out.join("runs").join(slug);
        if out.exists() {
            std::fs::remove_dir_all(&out).map_err(|e| e.to_string())?;
        }
        std::fs::create_dir_all(&out).map_err(|e| e.to_string())?;
        let exporter = RunExporter {
            backend: &backend,
            task: task_dir.to_string_lossy().into_owned(),
            task_dir,
            out,
            demo_task: format!("{DEMO_RUNS_FOLDER}/{slug}"),
            runs_folder: runs.to_string_lossy().into_owned(),
        };
        summaries.push(exporter.export()?);
        eprintln!("web_demo_export: {slug} exported");
    }
    write_json(&options.out.join("tasks.json"), &Value::Array(summaries))?;
    let _ = std::fs::remove_dir_all(&config);
    Ok(())
}

struct RunExporter<'a> {
    backend: &'a Backend,
    /// The task id the backend takes (the local run folder).
    task: String,
    task_dir: PathBuf,
    out: PathBuf,
    /// The task id the demo shows.
    demo_task: String,
    runs_folder: String,
}

impl RunExporter<'_> {
    fn export(&self) -> Result<Value, String> {
        let backend = self.backend;
        let task = self.task.as_str();
        let mut view = to_value(backend.get_task(task).map_err(|e| e.message)?)?;
        // "A different build made this run" compares the run with this exporter's own binary;
        // on the web nothing can be continued anyway, so the notice would only mislead.
        if let Some(notices) = view["notices"].as_array_mut() {
            notices.retain(|notice| notice["id"] != OTHER_BUILD_NOTICE);
        }
        let events = to_value(backend.get_events(task, 0).map_err(|e| e.message)?)?;
        let live = to_value(backend.get_live_steps(task, 0).map_err(|e| e.message)?)?;
        let sources = backend
            .list_sources(task)
            .map(to_value)
            .unwrap_or_else(|_| Ok(json!({ "sources": [], "revision": null })))?;

        let sections = self.hull_sections(&view, &live)?;
        let pages = self.source_pages(&sources)?;
        let exports = self.exports(&view)?;
        let tables = self.sounding_tables(&view)?;

        let mut named = BTreeSet::new();
        for value in [&view, &live, &sections] {
            collect_strings(value, &mut named);
        }
        self.copy_artifacts(&named)?;

        let summary = view["summary"].clone();
        for (name, value) in [
            ("task.json", view),
            ("events.json", events),
            ("live.json", live),
            ("sections.json", sections),
            ("sources.json", sources),
            ("pages.json", pages),
            ("exports.json", exports),
            ("tables.json", tables),
        ] {
            write_json(&self.out.join(name), &self.scrub(value))?;
        }
        Ok(self.scrub(summary))
    }

    /// Every build the UI may ask sections for: the current revision, each live step's
    /// revision (by id and by path) and each build of the worker catalog.
    fn hull_sections(&self, view: &Value, live: &Value) -> Result<Value, String> {
        let mut keys = BTreeSet::new();
        if let Some(revision) = view["revision"].as_str() {
            keys.insert(revision.to_string());
        }
        for step in live["steps"].as_array().into_iter().flatten() {
            for field in ["id", "path"] {
                if let Some(key) = step["revision"][field].as_str() {
                    keys.insert(key.to_string());
                }
            }
        }
        let state = std::fs::read(self.task_dir.join("domain/state.json"))
            .ok()
            .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok());
        if let Some(state) = state {
            for build in state["builds"].as_array().into_iter().flatten() {
                for field in ["revision_id", "path"] {
                    if let Some(key) = build[field].as_str() {
                        keys.insert(key.to_string());
                    }
                }
            }
        }
        let mut found = Map::new();
        for key in keys {
            if let Ok(sections) = self.backend.get_hull_sections(&self.task, &key) {
                found.insert(key, to_value(sections)?);
            }
        }
        Ok(Value::Object(found))
    }

    /// The thumbnail and the full page of every previewable source page, as PNG files.
    fn source_pages(&self, sources: &Value) -> Result<Value, String> {
        let mut found = Map::new();
        for source in sources["sources"].as_array().into_iter().flatten() {
            if source["previewable"] != json!(true) {
                continue;
            }
            let id = source["id"].as_str().unwrap_or_default();
            let page_count = source["pages"].as_array().map_or(0, Vec::len).max(1);
            for page in 0..page_count as u32 {
                for (size_name, size) in
                    [("thumb", PreviewSize::Thumb), ("full", PreviewSize::Full)]
                {
                    let Ok(preview) = self.backend.read_source_page(&self.task, id, page, size)
                    else {
                        continue;
                    };
                    let mut facts = to_value(&preview)?;
                    let object = facts.as_object_mut().ok_or("preview is not an object")?;
                    if let Some(base64) = object
                        .remove("base64")
                        .and_then(|v| v.as_str().map(String::from))
                    {
                        let file = format!("pages/{}-{page}-{size_name}.png", safe_name(id));
                        let bytes = decode_base64(&base64)?;
                        write_bytes(&self.out.join(&file), &bytes)?;
                        object.insert("file".into(), Value::String(file));
                    }
                    found.insert(format!("{id}|{page}|{size_name}"), facts);
                }
            }
        }
        Ok(Value::Object(found))
    }

    /// Files already exported for the current revision; the allowed kinds are copied.
    fn exports(&self, view: &Value) -> Result<Value, String> {
        let mut found = Map::new();
        let Some(revision) = view["revision"].as_str() else {
            return Ok(Value::Object(found));
        };
        let Ok(result) = self.backend.list_exports(&self.task, revision) else {
            return Ok(Value::Object(found));
        };
        let mut result = to_value(result)?;
        let folder_revision = result["revision"].as_str().unwrap_or(revision).to_string();
        let mut kept = vec![];
        for file in result["files"].as_array().into_iter().flatten() {
            let name = file["file"].as_str().unwrap_or_default();
            let extension = name
                .rsplit('.')
                .next()
                .unwrap_or_default()
                .to_ascii_lowercase();
            if !DOWNLOAD_EXTENSIONS.contains(&extension.as_str()) || name.contains('/') {
                continue;
            }
            let from = self
                .task_dir
                .join("exports")
                .join(&folder_revision)
                .join(name);
            if artifact::guard_inside_task(
                &self.task_dir,
                &format!("exports/{folder_revision}/{name}"),
            )
            .is_err()
            {
                continue;
            }
            let relative = format!("exports/{folder_revision}/{name}");
            std::fs::create_dir_all(self.out.join("exports").join(&folder_revision))
                .map_err(|e| e.to_string())?;
            std::fs::copy(&from, self.out.join(&relative))
                .map_err(|e| format!("{}: {e}", from.display()))?;
            let mut entry = file.clone();
            entry["path"] = Value::String(relative);
            kept.push(entry);
        }
        result["files"] = Value::Array(kept);
        result["folder"] = Value::String(format!("exports/{folder_revision}"));
        found.insert(revision.to_string(), result.clone());
        found.insert(folder_revision, result);
        Ok(Value::Object(found))
    }

    /// The sounding table of every tank the view names.
    fn sounding_tables(&self, view: &Value) -> Result<Value, String> {
        // The capacity plan's rows name the tanks (CapacityRow.id), as sounding_table takes them.
        let tanks: BTreeSet<String> = view["capacity_plan"]["rows"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|row| row["id"].as_str().map(String::from))
            .collect();
        let mut found = Map::new();
        for tank in tanks {
            if let Ok(table) = self.backend.sounding_table(&self.task, &tank) {
                found.insert(tank, to_value(table)?);
            }
        }
        Ok(Value::Object(found))
    }

    /// Copy every task-relative image, STL or GLB file the JSON names, through the same
    /// guard `read_artifact` uses (no links, no `..`, only those types).
    fn copy_artifacts(&self, named: &BTreeSet<String>) -> Result<(), String> {
        for relative in named {
            let Ok((from, _mime, limit)) = artifact::guard_artifact_path(&self.task_dir, relative)
            else {
                continue;
            };
            let size = std::fs::metadata(&from)
                .map(|m| m.len())
                .unwrap_or(u64::MAX);
            if size > limit as u64 {
                continue;
            }
            let to = self.out.join("files").join(relative);
            if let Some(parent) = to.parent() {
                std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            std::fs::copy(&from, &to).map_err(|e| format!("{}: {e}", from.display()))?;
        }
        Ok(())
    }

    /// Replace this computer's run folder with the demo's, in every string.
    fn scrub(&self, value: Value) -> Value {
        match value {
            Value::String(text) => Value::String(only_file_names(
                &text
                    .replace(&self.task, &self.demo_task)
                    .replace(&self.runs_folder, DEMO_RUNS_FOLDER),
            )),
            Value::Array(items) => Value::Array(items.into_iter().map(|v| self.scrub(v)).collect()),
            Value::Object(map) => Value::Object(
                map.into_iter()
                    .map(|(key, v)| (key.replace(&self.task, &self.demo_task), self.scrub(v)))
                    .collect(),
            ),
            other => other,
        }
    }
}

/// Folders whose absolute paths name this computer (its user, temporary or mounted folders).
const LOCAL_ROOTS: [&str; 6] = [
    "/Users/",
    "/home/",
    "/private/",
    "/tmp/",
    "/var/folders/",
    "/Volumes/",
];

/// Replace every other absolute local path in `text` (for example the input sheet a run
/// spec names) with its file name alone. A path ends at white space, a quote or a comma.
fn only_file_names(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(start) = LOCAL_ROOTS.iter().filter_map(|root| rest.find(root)).min() {
        out.push_str(&rest[..start]);
        let path_len = rest[start..]
            .find(|c: char| c.is_whitespace() || matches!(c, '"' | '\'' | ',' | ')'))
            .unwrap_or(rest.len() - start);
        let path = &rest[start..start + path_len];
        out.push_str(path.rsplit('/').find(|part| !part.is_empty()).unwrap_or(""));
        rest = &rest[start + path_len..];
    }
    out.push_str(rest);
    out
}

/// Copy the files of `from` into `to`, recursively; links are skipped.
fn copy_folder(from: &Path, to: &Path) -> Result<(), String> {
    for entry in std::fs::read_dir(from).map_err(|e| format!("{}: {e}", from.display()))? {
        let entry = entry.map_err(|e| e.to_string())?;
        let kind = entry.file_type().map_err(|e| e.to_string())?;
        let target = to.join(entry.file_name());
        if kind.is_dir() {
            std::fs::create_dir_all(&target).map_err(|e| e.to_string())?;
            copy_folder(&entry.path(), &target)?;
        } else if kind.is_file() {
            std::fs::copy(entry.path(), &target).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

fn to_value<T: serde::Serialize>(value: T) -> Result<Value, String> {
    serde_json::to_value(value).map_err(|e| e.to_string())
}

/// Every string in `value` (candidate artifact paths).
fn collect_strings(value: &Value, out: &mut BTreeSet<String>) {
    match value {
        Value::String(text) => {
            out.insert(text.clone());
        }
        Value::Array(items) => items.iter().for_each(|v| collect_strings(v, out)),
        Value::Object(map) => map.values().for_each(|v| collect_strings(v, out)),
        _ => {}
    }
}

/// A source id as a file name: letters, digits, `-` and `_` only.
fn safe_name(id: &str) -> String {
    id.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect()
}

fn decode_base64(text: &str) -> Result<Vec<u8>, String> {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD
        .decode(text)
        .map_err(|e| e.to_string())
}

/// Pretty JSON. Keys keep a fixed order (struct order or sorted), so a rebuild of the same
/// runs gives the same bytes.
fn write_json(path: &Path, value: &Value) -> Result<(), String> {
    let mut bytes = serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?;
    bytes.push(b'\n');
    write_bytes(path, &bytes)
}

fn write_bytes(path: &Path, bytes: &[u8]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(path, bytes).map_err(|e| format!("{}: {e}", path.display()))
}
