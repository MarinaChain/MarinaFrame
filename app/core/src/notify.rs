//! A desktop notification when a run stops (a queued or a live run).
//!
//! The watcher sees each task's status every round; a task that was running and
//! now is not gives one notification, once per run. The text holds the vessel or
//! run name and the outcome only, never drawing content. Settings can turn it off
//! (`Settings.notify_finished`).
//!
//! macOS shows it through `osascript` (`display notification`), which needs no
//! extra crate or permission prompt beyond the system's own. The texts go in as
//! script arguments (`on run argv`), never inside the script source, so a run name
//! cannot change the script. Other systems: no notification (the app is macOS-first).
use crate::types::{Status, TaskSummary};
use std::collections::{HashMap, HashSet};

/// Longest run name in a notification; macOS cuts long texts anyway.
const MAX_NAME_CHARS: usize = 80;

/// What one notification says.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Notice {
    pub task: String,
    pub title: String,
    pub body: String,
}

/// The outcome words of a stopped run, or None when it needs no notification
/// (a cancel is the person's own action).
fn outcome(status: Status) -> Option<&'static str> {
    match status {
        Status::Draft => Some("Draft ready to check."),
        Status::NeedsReview => Some("Ready for your review."),
        Status::Declined => Some("Declined. Open the run to see why."),
        Status::Failed => Some("Stopped with an error."),
        Status::Paused | Status::Blocked => Some("Waiting for you."),
        Status::Cancelled | Status::Running => None,
    }
}

/// Remembers each task's last status, and which runs already gave a notification.
#[derive(Default)]
pub struct FinishWatcher {
    last: HashMap<String, Status>,
    notified: HashSet<String>,
    primed: bool,
}

impl FinishWatcher {
    /// The runs that stopped since the last round. The first round only records
    /// statuses, so opening the app does not repeat old results.
    pub fn poll(&mut self, tasks: &[TaskSummary]) -> Vec<Notice> {
        let mut notices = vec![];
        for task in tasks {
            let was_running = self.last.get(&task.task) == Some(&Status::Running);
            if self.primed && was_running && task.status != Status::Running {
                if let Some(words) = outcome(task.status) {
                    if self.notified.insert(task.task.clone()) {
                        notices.push(Notice {
                            task: task.task.clone(),
                            title: "MarinaFrame".into(),
                            body: format!("{}: {words}", plain_name(&task.name)),
                        });
                    }
                }
            }
            // A run that goes again (resume) may notify again when it next stops.
            if task.status == Status::Running {
                self.notified.remove(&task.task);
            }
            self.last.insert(task.task.clone(), task.status);
        }
        self.primed = true;
        notices
    }
}

/// One line, no control characters, at most [`MAX_NAME_CHARS`].
fn plain_name(name: &str) -> String {
    let flat: String = name
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect();
    let trimmed = flat.trim();
    if trimmed.chars().count() <= MAX_NAME_CHARS {
        return trimmed.to_string();
    }
    let mut cut: String = trimmed.chars().take(MAX_NAME_CHARS - 1).collect();
    cut.push('…');
    cut
}

/// The osascript arguments: the script (fixed) and the texts as `argv` items.
fn osascript_args(notice: &Notice) -> Vec<String> {
    vec![
        "-e".into(),
        "on run argv".into(),
        "-e".into(),
        "display notification (item 2 of argv) with title (item 1 of argv)".into(),
        "-e".into(),
        "end run".into(),
        notice.title.clone(),
        notice.body.clone(),
    ]
}

/// Show the notification. Errors are ignored: a notification is never essential.
pub fn show(notice: &Notice) {
    if cfg!(target_os = "macos") {
        let _ = std::process::Command::new("/usr/bin/osascript")
            .args(osascript_args(notice))
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
            .and_then(|mut child| child.wait());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn task(id: &str, name: &str, status: Status) -> TaskSummary {
        TaskSummary {
            task: id.into(),
            name: name.into(),
            status,
            policy: String::new(),
            updated_ms: 0,
            sections: 0,
        }
    }

    #[test]
    fn one_notice_when_a_running_run_stops_and_none_on_the_first_round() {
        let mut watcher = FinishWatcher::default();
        // First round: old results never notify.
        assert!(watcher
            .poll(&[
                task("a", "Old", Status::Draft),
                task("b", "Tug", Status::Running)
            ])
            .is_empty());
        assert!(watcher
            .poll(&[task("b", "Tug", Status::Running)])
            .is_empty());
        let notices = watcher.poll(&[task("b", "Tug", Status::Draft)]);
        assert_eq!(notices.len(), 1);
        assert_eq!(notices[0].body, "Tug: Draft ready to check.");
        // The same stop is not repeated.
        assert!(watcher.poll(&[task("b", "Tug", Status::Draft)]).is_empty());
    }

    #[test]
    fn a_cancel_gives_no_notice_and_a_resumed_run_can_notify_again() {
        let mut watcher = FinishWatcher::default();
        watcher.poll(&[task("c", "Ferry", Status::Running)]);
        assert!(watcher
            .poll(&[task("c", "Ferry", Status::Cancelled)])
            .is_empty());
        watcher.poll(&[task("c", "Ferry", Status::Running)]);
        let notices = watcher.poll(&[task("c", "Ferry", Status::Failed)]);
        assert_eq!(notices[0].body, "Ferry: Stopped with an error.");
    }

    #[test]
    fn a_new_run_that_finishes_between_two_rounds_gives_no_notice() {
        // It was never seen running, so there is no "stopped" change to report.
        let mut watcher = FinishWatcher::default();
        watcher.poll(&[]);
        assert!(watcher
            .poll(&[task("d", "Launch", Status::Draft)])
            .is_empty());
    }

    #[test]
    fn names_are_one_short_line_and_go_in_as_arguments() {
        let long = format!("Line\none\"; do shell script \"x{}", "y".repeat(200));
        let name = plain_name(&long);
        assert!(!name.contains('\n'));
        assert_eq!(name.chars().count(), MAX_NAME_CHARS);
        let notice = Notice {
            task: "t".into(),
            title: "MarinaFrame".into(),
            body: name.clone(),
        };
        let args = osascript_args(&notice);
        // The script lines are fixed; the name is only an argv item.
        assert!(args[..6].iter().all(|a| !a.contains("shell")));
        assert_eq!(args.last().unwrap(), &name);
    }
}
