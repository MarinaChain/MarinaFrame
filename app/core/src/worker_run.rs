//! How the app runs its Python workers (intake, export, part revision): always
//! through the controller's shared supervisor (`marinaframe_control::supervised`).
//! Each worker gets its own process group and only the allowlisted environment;
//! a cancel or a stall stops the whole group. Our own deterministic code has no
//! wall-clock limit: only the progress watchdog stops a worker that does not
//! advance. Sandboxed model code keeps its own caps inside the worker.
use crate::error::{AppError, AppResult};
use crate::intake::Worker;
use marinaframe_control::supervised::{self, Finished, Watch, WatchedEnd, WorkerCommand};
use std::path::Path;
use std::time::Duration;

/// When a worker run is stopped besides its own exit.
pub struct Supervision<'a> {
    /// True when the person asked to stop.
    pub cancelled: &'a dyn Fn() -> bool,
    /// No progress report for this long stops the worker.
    pub stall_period: Duration,
}

/// A run nobody can cancel, with the default stall period.
pub const UNCANCELLABLE: Supervision<'static> = Supervision {
    cancelled: &supervised::never_cancelled,
    stall_period: supervised::DEFAULT_STALL_PERIOD,
};

/// How errors of one kind of worker are named for the person.
pub struct WorkerWords {
    /// Error code prefix: `<prefix>_worker`, `<prefix>_cancelled`, `<prefix>_stalled`.
    pub code: &'static str,
    /// The worker as the sentence subject, for example "The export".
    pub name: &'static str,
    /// Added after a stop message, for example " The old part stays."
    pub after_stop: &'static str,
}

impl Worker<'_> {
    /// `python -m <module>` with the shared worker environment.
    /// Refused when no worker Python is set or found.
    pub(crate) fn module_command(&self, module: &str) -> AppResult<WorkerCommand> {
        if self.python.is_empty() || !Path::new(self.python).is_file() {
            return Err(AppError::from_code("worker_python_missing"));
        }
        let mut command = WorkerCommand::python(self.python, self.source);
        command.args(["-m", module]);
        Ok(command)
    }

    /// Run `command` to its end under `supervision`. A worker that exits (with
    /// any status) is returned; a cancel, a stall or a failed start is an error.
    pub(crate) fn run_supervised(
        &self,
        command: &mut WorkerCommand,
        supervision: &Supervision,
        words: &WorkerWords,
    ) -> AppResult<Finished> {
        let watch = Watch {
            stall_period: supervision.stall_period,
            cancelled: supervision.cancelled,
            operation: "starting",
        };
        let end = supervised::run_watched(command, &watch).map_err(|_| {
            AppError::new(
                &format!("{}_worker", words.code),
                &format!("{} could not start.", words.name),
            )
        })?;
        match end {
            WatchedEnd::Finished(finished) => Ok(finished),
            WatchedEnd::Cancelled => Err(AppError::new(
                &format!("{}_cancelled", words.code),
                &format!("{} was cancelled.{}", words.name, words.after_stop),
            )),
            WatchedEnd::Stalled { stage, minutes } => Err(AppError::new(
                &format!("{}_stalled", words.code),
                &format!(
                    "{} was stopped at {stage} after {minutes:.1} min without progress.{}",
                    words.name, words.after_stop
                ),
            )),
        }
    }
}
