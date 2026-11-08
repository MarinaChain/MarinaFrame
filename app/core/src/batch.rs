//! Batch queue (design plan M6): many drawing sets dropped at once, one run per set.
//!
//! [`plan_batch`] groups dropped files and folders into drawing sets without
//! reading them. [`BatchQueue`] keeps the sets that wait, in order, in the app
//! config folder (`batch_queue.json`), so a restart keeps the queue. The
//! backend's pump starts waiting sets while fewer runs than the native slot
//! limit are running; each start reads the set (intake) and starts its run with
//! the proposed labels, as if the person pressed Start reading without edits.
use crate::intake::{ACCEPTED_EXTENSIONS, MAX_FILES};
use crate::storage::{self, AppPaths};
use crate::{AppError, AppResult};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

pub const QUEUE_FILE: &str = "batch_queue.json";
/// At most this many sets in one drop, and waiting at once.
pub const MAX_SETS: usize = 40;
/// Same bounds as the native worker admission (rust-control worker.rs): half the
/// cores, at least 1, at most 8; `MARINAFRAME_NATIVE_SLOTS` overrides.
const MAX_NATIVE_SLOTS: usize = 8;

/// How many runs may do native work at once: the same rule as the worker's admission.
pub fn native_slots() -> usize {
    std::env::var("MARINAFRAME_NATIVE_SLOTS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|slots| (1..=MAX_NATIVE_SLOTS).contains(slots))
        .unwrap_or_else(|| {
            let cores = std::thread::available_parallelism().map_or(2, |n| n.get());
            (cores / 2).clamp(1, MAX_NATIVE_SLOTS)
        })
}

/// One drawing set: the files one run reads.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct DrawingSet {
    pub name: String,
    pub files: Vec<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct SkippedPath {
    pub path: String,
    pub reason: String,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct BatchPlan {
    pub sets: Vec<DrawingSet>,
    pub skipped: Vec<SkippedPath>,
}

fn is_drawing(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .is_some_and(|e| ACCEPTED_EXTENSIONS.contains(&e.to_ascii_lowercase().as_str()))
}

fn is_pdf(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .is_some_and(|e| e.eq_ignore_ascii_case("pdf"))
}

fn stem(path: &Path) -> String {
    path.file_stem()
        .or_else(|| path.file_name())
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "Drawing set".into())
}

/// Regular files of a folder (no symlinks, no hidden files), sorted by name.
fn folder_entries(folder: &Path) -> (Vec<PathBuf>, Vec<PathBuf>) {
    let mut files = vec![];
    let mut folders = vec![];
    let Ok(entries) = std::fs::read_dir(folder) else {
        return (files, folders);
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if entry.file_name().to_string_lossy().starts_with('.') {
            continue;
        }
        match std::fs::symlink_metadata(&path) {
            Ok(meta) if meta.is_file() => files.push(path),
            Ok(meta) if meta.is_dir() => folders.push(path),
            _ => {}
        }
    }
    files.sort();
    folders.sort();
    (files, folders)
}

/// Loose files: each PDF is its own set (a PDF is usually one vessel's whole set);
/// the images together are one set named `group_name`.
fn sets_from_files(files: &[PathBuf], group_name: &str, plan: &mut BatchPlan) {
    let mut images = vec![];
    for file in files {
        if !is_drawing(file) {
            plan.skipped.push(SkippedPath {
                path: file.to_string_lossy().into_owned(),
                reason: "Not a PDF, PNG, TIFF or JPEG drawing.".into(),
            });
        } else if is_pdf(file) {
            plan.sets.push(DrawingSet {
                name: stem(file),
                files: vec![file.to_string_lossy().into_owned()],
            });
        } else {
            images.push(file.to_string_lossy().into_owned());
        }
    }
    if !images.is_empty() {
        plan.sets.push(DrawingSet {
            name: group_name.to_string(),
            files: images,
        });
    }
}

/// Group dropped paths into drawing sets. Files dropped on their own are one set, as
/// before (one vessel's sheets; the intake lets the person skip pages). A dropped
/// folder is a batch: a subfolder is one set (the person grouped those sheets) and the
/// folder's own files follow [`sets_from_files`]. A set with more than [`MAX_FILES`]
/// files, or sets beyond [`MAX_SETS`], are skipped with a reason.
pub fn plan_batch(paths: &[String]) -> BatchPlan {
    let mut plan = BatchPlan {
        sets: vec![],
        skipped: vec![],
    };
    let mut loose = vec![];
    for raw in paths {
        let path = PathBuf::from(raw);
        match std::fs::symlink_metadata(&path) {
            Ok(meta) if meta.is_dir() => {
                let (files, folders) = folder_entries(&path);
                sets_from_files(&files, &stem(&path), &mut plan);
                for folder in folders {
                    let (inner, _) = folder_entries(&folder);
                    let drawings: Vec<String> = inner
                        .iter()
                        .filter(|f| is_drawing(f))
                        .map(|f| f.to_string_lossy().into_owned())
                        .collect();
                    if !drawings.is_empty() {
                        plan.sets.push(DrawingSet {
                            name: stem(&folder),
                            files: drawings,
                        });
                    }
                }
            }
            Ok(meta) if meta.is_file() => loose.push(path),
            _ => plan.skipped.push(SkippedPath {
                path: raw.clone(),
                reason: "Not found, or a link.".into(),
            }),
        }
    }
    // Loose dropped files: one set, named after the first drawing.
    let (drawings, others): (Vec<_>, Vec<_>) = loose.into_iter().partition(|f| is_drawing(f));
    for other in others {
        plan.skipped.push(SkippedPath {
            path: other.to_string_lossy().into_owned(),
            reason: "Not a PDF, PNG, TIFF or JPEG drawing.".into(),
        });
    }
    if let Some(first) = drawings.first() {
        plan.sets.push(DrawingSet {
            name: stem(first),
            files: drawings
                .iter()
                .map(|f| f.to_string_lossy().into_owned())
                .collect(),
        });
    }

    let (fits, too_big): (Vec<_>, Vec<_>) = plan
        .sets
        .into_iter()
        .partition(|set| set.files.len() <= MAX_FILES);
    plan.skipped
        .extend(too_big.into_iter().map(|set| SkippedPath {
            path: set.name,
            reason: format!("More than {MAX_FILES} sheets in one set."),
        }));
    plan.sets = fits;
    if plan.sets.len() > MAX_SETS {
        for set in plan.sets.split_off(MAX_SETS) {
            plan.skipped.push(SkippedPath {
                path: set.name,
                reason: format!("At most {MAX_SETS} sets at once."),
            });
        }
    }
    plan
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum QueueState {
    Waiting,
    Starting,
    /// The set could not be read or started; it stays until the person removes it.
    Failed,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct QueuedSet {
    pub id: String,
    pub name: String,
    pub files: Vec<String>,
    pub added_ms: u64,
    pub state: QueueState,
    #[serde(default)]
    pub message: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct QueueView {
    /// Runs that may do native work at once.
    pub slots: usize,
    /// Runs running now (any run in the runs folder) plus sets being started.
    pub running: usize,
    /// Sets in start order (failed ones keep their place until removed).
    pub waiting: Vec<QueuedSet>,
    /// Why waiting sets do not start, when they cannot (for example AI drafting off).
    pub held: Option<String>,
}

/// The waiting sets, in order, kept in the app config folder.
pub struct BatchQueue {
    sets: Mutex<Vec<QueuedSet>>,
}

impl BatchQueue {
    /// Read the saved queue. A set that was starting when the app closed waits again.
    pub fn load(paths: &AppPaths) -> Self {
        let mut sets: Vec<QueuedSet> =
            storage::read_config_json(paths, QUEUE_FILE).unwrap_or_default();
        for set in &mut sets {
            if set.state == QueueState::Starting {
                set.state = QueueState::Waiting;
            }
        }
        Self {
            sets: Mutex::new(sets),
        }
    }

    fn with<T>(
        &self,
        paths: &AppPaths,
        change: impl FnOnce(&mut Vec<QueuedSet>) -> AppResult<T>,
    ) -> AppResult<T> {
        let mut sets = self
            .sets
            .lock()
            .map_err(|_| AppError::from_code("registry_poisoned"))?;
        let result = change(&mut sets)?;
        storage::write_config_json(paths, QUEUE_FILE, &*sets)?;
        Ok(result)
    }

    pub fn snapshot(&self) -> Vec<QueuedSet> {
        self.sets.lock().map(|s| s.clone()).unwrap_or_default()
    }

    /// Add sets at the end, in the given order.
    pub fn add(&self, paths: &AppPaths, sets: &[DrawingSet], now_ms: u64) -> AppResult<()> {
        self.with(paths, |queue| {
            if queue.len() + sets.len() > MAX_SETS {
                return Err(AppError::new(
                    "queue_full",
                    &format!("At most {MAX_SETS} sets can wait at once."),
                ));
            }
            for (index, set) in sets.iter().enumerate() {
                if set.files.is_empty() || set.files.len() > MAX_FILES {
                    return Err(AppError::new(
                        "intake_files",
                        &format!("Each set needs 1 to {MAX_FILES} drawing files."),
                    ));
                }
                queue.push(QueuedSet {
                    id: format!("batch-{now_ms}-{index}"),
                    name: set.name.chars().take(200).collect(),
                    files: set.files.clone(),
                    added_ms: now_ms,
                    state: QueueState::Waiting,
                    message: None,
                });
            }
            Ok(())
        })
    }

    /// Remove a waiting or failed set. A set being started cannot be removed.
    pub fn remove(&self, paths: &AppPaths, id: &str) -> AppResult<()> {
        self.with(paths, |queue| {
            let index = position(queue, id)?;
            if queue[index].state == QueueState::Starting {
                return Err(AppError::new(
                    "queue_starting",
                    "This set is starting; it cannot be removed now.",
                ));
            }
            queue.remove(index);
            Ok(())
        })
    }

    /// Move a set earlier (-1) or later (+1) in the order.
    pub fn move_set(&self, paths: &AppPaths, id: &str, delta: i64) -> AppResult<()> {
        self.with(paths, |queue| {
            let index = position(queue, id)?;
            let target = index as i64 + delta.signum();
            if (0..queue.len() as i64).contains(&target) {
                queue.swap(index, target as usize);
            }
            Ok(())
        })
    }

    pub fn starting_count(&self) -> usize {
        self.snapshot()
            .iter()
            .filter(|s| s.state == QueueState::Starting)
            .count()
    }

    /// Mark up to `free` waiting sets, first in order, as starting, and return them.
    pub fn take_for_start(&self, paths: &AppPaths, free: usize) -> Vec<QueuedSet> {
        if free == 0 {
            return vec![];
        }
        self.with(paths, |queue| {
            Ok(queue
                .iter_mut()
                .filter(|s| s.state == QueueState::Waiting)
                .take(free)
                .map(|set| {
                    set.state = QueueState::Starting;
                    set.clone()
                })
                .collect())
        })
        .unwrap_or_default()
    }

    /// A start ended: a started set leaves the queue; a failed one stays with its reason.
    pub fn finish(&self, paths: &AppPaths, id: &str, result: Result<(), String>) {
        let _ = self.with(paths, |queue| {
            let index = position(queue, id)?;
            match result {
                Ok(()) => {
                    queue.remove(index);
                }
                Err(message) => {
                    queue[index].state = QueueState::Failed;
                    queue[index].message = Some(message);
                }
            }
            Ok(())
        });
    }
}

fn position(queue: &[QueuedSet], id: &str) -> AppResult<usize> {
    queue
        .iter()
        .position(|s| s.id == id)
        .ok_or_else(|| AppError::new("queue_unknown", "This set is no longer in the queue."))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn touch(path: &Path) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, b"x").unwrap();
    }

    fn paths(dir: &Path) -> AppPaths {
        AppPaths {
            config_dir: dir.join("config"),
            data_dir: dir.join("data"),
            repo_root: None,
        }
    }

    fn set(name: &str) -> DrawingSet {
        DrawingSet {
            name: name.into(),
            files: vec![format!("/sheets/{name}.pdf")],
        }
    }

    #[test]
    fn a_folder_gives_one_set_per_pdf_per_subfolder_and_one_for_loose_images() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("Yard order");
        touch(&root.join("tug-a.pdf"));
        touch(&root.join("ferry.PDF"));
        touch(&root.join("sheet-1.png"));
        touch(&root.join("sheet-2.tif"));
        touch(&root.join("notes.txt"));
        touch(&root.join(".DS_Store"));
        touch(&root.join("Launch 24/profile.png"));
        touch(&root.join("Launch 24/body plan.png"));
        touch(&root.join("Launch 24/readme.md"));
        std::fs::create_dir_all(root.join("Empty")).unwrap();

        let plan = plan_batch(&[root.to_string_lossy().into_owned()]);
        let names: Vec<&str> = plan.sets.iter().map(|s| s.name.as_str()).collect();
        assert_eq!(names, vec!["ferry", "tug-a", "Yard order", "Launch 24"]);
        assert_eq!(plan.sets[2].files.len(), 2, "loose images are one set");
        assert_eq!(
            plan.sets[3].files.len(),
            2,
            "a subfolder is one set of its drawings"
        );
        assert_eq!(plan.skipped.len(), 1, "notes.txt: {:?}", plan.skipped);
    }

    #[test]
    fn dropped_files_and_missing_paths() {
        let dir = tempfile::tempdir().unwrap();
        let pdf = dir.path().join("a.pdf");
        let png = dir.path().join("b.png");
        touch(&pdf);
        touch(&png);
        let missing = dir.path().join("gone.pdf");
        let plan = plan_batch(&[
            pdf.to_string_lossy().into_owned(),
            png.to_string_lossy().into_owned(),
            missing.to_string_lossy().into_owned(),
        ]);
        assert_eq!(plan.sets.len(), 1, "files dropped on their own are one set");
        assert_eq!(plan.sets[0].files.len(), 2);
        assert_eq!(plan.skipped[0].reason, "Not found, or a link.");
    }

    #[test]
    fn too_many_sheets_in_one_set_is_skipped() {
        let dir = tempfile::tempdir().unwrap();
        let folder = dir.path().join("big").join("huge set");
        for i in 0..=MAX_FILES {
            touch(&folder.join(format!("s{i:02}.png")));
        }
        let plan = plan_batch(&[dir.path().join("big").to_string_lossy().into_owned()]);
        assert!(plan.sets.is_empty());
        assert!(plan.skipped[0].reason.contains("sheets"));
    }

    #[test]
    fn the_queue_keeps_order_moves_and_survives_a_restart() {
        let dir = tempfile::tempdir().unwrap();
        let app = paths(dir.path());
        let queue = BatchQueue::load(&app);
        queue.add(&app, &[set("a"), set("b"), set("c")], 7).unwrap();
        let ids: Vec<String> = queue.snapshot().iter().map(|s| s.id.clone()).collect();
        queue.move_set(&app, &ids[2], -1).unwrap();
        let names = |q: &BatchQueue| {
            q.snapshot()
                .iter()
                .map(|s| s.name.clone())
                .collect::<Vec<_>>()
        };
        assert_eq!(names(&queue), vec!["a", "c", "b"]);

        let started = queue.take_for_start(&app, 2);
        assert_eq!(started.len(), 2);
        assert_eq!(queue.starting_count(), 2);
        // A restart: sets that were starting wait again, in the same order.
        let again = BatchQueue::load(&app);
        assert_eq!(names(&again), vec!["a", "c", "b"]);
        assert_eq!(again.starting_count(), 0);
    }

    #[test]
    fn a_finished_start_leaves_and_a_failed_one_stays_with_its_reason() {
        let dir = tempfile::tempdir().unwrap();
        let app = paths(dir.path());
        let queue = BatchQueue::load(&app);
        queue.add(&app, &[set("a"), set("b")], 1).unwrap();
        let started = queue.take_for_start(&app, 5);
        assert!(
            queue.remove(&app, &started[0].id).is_err(),
            "a starting set stays"
        );
        queue.finish(&app, &started[0].id, Ok(()));
        queue.finish(
            &app,
            &started[1].id,
            Err("The drawings could not be read.".into()),
        );
        let left = queue.snapshot();
        assert_eq!(left.len(), 1);
        assert_eq!(left[0].state, QueueState::Failed);
        queue.remove(&app, &left[0].id).unwrap();
        assert!(queue.snapshot().is_empty());
        assert!(queue.take_for_start(&app, 0).is_empty());
    }

    #[test]
    fn a_full_queue_refuses_more_sets() {
        let dir = tempfile::tempdir().unwrap();
        let app = paths(dir.path());
        let queue = BatchQueue::load(&app);
        let many: Vec<DrawingSet> = (0..MAX_SETS).map(|i| set(&format!("s{i}"))).collect();
        queue.add(&app, &many, 1).unwrap();
        assert!(queue.add(&app, &[set("one more")], 2).is_err());
    }

    #[test]
    fn native_slots_are_between_one_and_eight() {
        assert!((1..=MAX_NATIVE_SLOTS).contains(&native_slots()));
    }
}
