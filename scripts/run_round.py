#!/usr/bin/env python3
"""Run one small live-model MarinaFrame test round the standard way.

    source scripts/load_opencode_keys.sh
    python scripts/run_round.py --cases c1 c2 --inputs work/factory/inputs \
        --out ../work/round-foo --binary rust-control/target/release/marinaframe \
        --worker-source src --worker-python .venv/bin/python \
        --policy live --on-ambiguity draft --context conversation

Development rounds and the desktop app draft with Claude Sonnet 5.5 through the
Claude subscription (the `claude` CLI, no key) and fall back to Crouton Alpha
Free, then DeepSeek V4.1 Flash, through OpenCode Go only when the subscription
is rate limited (founder decision 2026-11-09); pass --model to choose another
ordered list. A Claude-only list (--model claude-sonnet-5-5) needs no OpenCode
Go key.

With --sheet-only each case starts like a drawing dropped in the app: the case
folder's drawings go through `vessel_reconstruction.intake prepare` and
`write-spec` (app/core/src/intake.rs), and the controller runs on that
sheet-only spec. Use the app's settings: --policy live --on-ambiguity draft.

Runs at most a few cases with the controller, writes one log, a result.json per
case and a digest from scripts/round_digest.py, and stops early when the first
cases fail the same way. --out must be inside the main checkout's work/ folder
(never a worktree's). Controller keys come from OPENCODE_API_KEY* in the
environment; this script never reads, prints or logs them. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
# More concurrent cases mainly overlap model waits: the controller serializes native CAD work.
MAX_JOBS = 6
DIGEST = SCRIPTS / "round_digest.py"
EARLY_STOP_AFTER = 2  # finished cases after which the digest may stop the round
# Drawing files a sheet-only case reads (the app's accepted types, app/core/src/intake.rs).
DRAWING_EXTENSIONS = (".pdf", ".png", ".tif", ".tiff", ".jpg", ".jpeg")
# Ordered models of development rounds (rust-control/src/models.rs DEFAULT_MODELS):
# the controller uses the next one when the current one is rate limited.
DEVELOPMENT_MODELS = "claude-sonnet-5-5,crouton-alpha-free,deepseek-v4.1-flash"
# Models reached through OpenCode Go (they need OPENCODE_API_KEY*).
OPENCODE_GO_MODELS = ("crouton-alpha-free", "deepseek-v4.1-flash")


def main_checkout() -> Path:
    """The main checkout root (this script may run from a linked worktree)."""
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=SCRIPTS, check=True, capture_output=True, text=True,
    ).stdout.strip()
    return Path(common).resolve().parent


def worktree_roots() -> list[Path]:
    """All checkout roots git knows about, main checkout included."""
    listing = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=SCRIPTS,
        check=True, capture_output=True, text=True,
    ).stdout
    return [Path(line.split(" ", 1)[1]).resolve()
            for line in listing.splitlines() if line.startswith("worktree ")]


def validate_out(out: Path, main: Path, worktrees: list[Path]) -> None:
    """Round data belongs in the main checkout's work/, never in a worktree."""
    out = out.resolve()
    for worktree in worktrees:
        if worktree != main and (out == worktree or worktree in out.parents):
            sys.exit(f"--out is inside git worktree {worktree}; round data must go to the main checkout's work/")
    if main / "work" not in out.parents:
        sys.exit(f"--out must be a new folder under {main / 'work'} (the main checkout's work/)")
    if out.exists():
        sys.exit(f"--out already exists: {out}; give each round its own folder")


def load_cases(values: list[str]) -> list[str]:
    """Case ids, or one path to a file holding one id per line."""
    if len(values) == 1 and Path(values[0]).is_file():
        lines = Path(values[0]).read_text().splitlines()
        values = [line.strip() for line in lines]
    cases = []
    for case in values:
        if not case or case.startswith("#") or case in cases:
            continue
        if "/" in case or case in (".", ".."):
            sys.exit(f"invalid case id: {case!r}")
        cases.append(case)
    return cases


class RoundLog:
    """One append-only log file, safe for detached runs and concurrent cases."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def write(self, message: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {message}\n"
        with self.lock:
            with self.path.open("a") as log:
                log.write(line)
        print(line, end="", flush=True)


def controller_status(stdout: str) -> dict:
    """The controller prints one final JSON summary line (drivers before us relied on it)."""
    for line in reversed(stdout.splitlines()):
        try:
            status = json.loads(line)
        except ValueError:
            continue
        return status if isinstance(status, dict) else {}
    return {}


def intake(args: argparse.Namespace, arguments: list[str]) -> dict:
    """Run `python -m vessel_reconstruction.intake <arguments>` as the app does; its JSON answer.

    The intake reader is local: it gets no provider key.
    """
    environment = {name: value for name, value in os.environ.items() if not name.startswith("OPENCODE_API_KEY")}
    environment["PYTHONPATH"] = str(args.worker_source.resolve())
    completed = subprocess.run([str(args.worker_python.absolute()), "-m", "vessel_reconstruction.intake", *arguments],
                               capture_output=True, text=True, env=environment, check=False)
    try:
        answer = json.loads(completed.stdout)
    except ValueError:
        answer = {"message": completed.stderr[-500:]}
    if completed.returncode != 0 or not isinstance(answer, dict):
        message = answer.get("message", "") if isinstance(answer, dict) else ""
        raise RuntimeError(f"intake {arguments[0]} failed: {message}"[:600])
    return answer


def sheet_only_spec(args: argparse.Namespace, case: str, case_dir: Path) -> Path:
    """Prepare the case's drawings and write a sheet-only spec, as a drop in the app with no edits."""
    drawings = sorted(path for path in (args.inputs / case).iterdir()
                      if path.is_file() and path.suffix.lower() in DRAWING_EXTENSIONS)
    if not drawings:
        raise RuntimeError(f"no drawing file ({', '.join(DRAWING_EXTENSIONS)}) in {args.inputs / case}")
    folder = case_dir / "intake"
    preview = intake(args, ["prepare", "--out", str(folder / "prepare"), *map(str, drawings)])
    # The app adds these two fields before the person starts the run (intake::prepare_intake).
    preview.update(intake_id=f"intake-{case}", ai_active=True)
    (folder / "preview.json").write_text(json.dumps(preview, indent=2) + "\n")
    written = intake(args, ["write-spec", "--preview", str(folder / "preview.json"),
                            "--out", str(folder / "run-input")])
    return Path(written["spec_path"])


def run_case(log: RoundLog, args: argparse.Namespace, case: str) -> None:
    case_dir = args.out / case
    case_dir.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    try:
        source = sheet_only_spec(args, case, case_dir) if args.sheet_only else None
    except (RuntimeError, OSError, KeyError) as exc:
        (case_dir / "result.json").write_text(json.dumps({
            "case": case, "exit_code": None, "controller_status": "intake_error",
            "termination_reason": str(exc)[:600], "wall_seconds": round(time.perf_counter() - started, 1),
        }, indent=2) + "\n")
        log.write(f"{case}: intake_error ({str(exc)[:200]})")
        return
    command = build_command(args, case, source)
    (case_dir / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    # Stream to files like the earlier drivers, so a case folder is complete
    # evidence even if this script is interrupted (round_digest reads stdout.log).
    with (case_dir / "stdout.log").open("w") as stdout, (case_dir / "stderr.log").open("w") as stderr:
        completed = subprocess.run(command, stdout=stdout, stderr=stderr, text=True, check=False)
    status = controller_status((case_dir / "stdout.log").read_text())
    (case_dir / "result.json").write_text(json.dumps({
        "case": case_dir.name,
        "exit_code": completed.returncode,
        "controller_status": status.get("status", "cli_error"),
        "termination_reason": status.get("termination_reason"),
        "wall_seconds": round(time.perf_counter() - started, 1),
    }, indent=2) + "\n")
    log.write(f"{case_dir.name}: exit {completed.returncode}, "
              f"status {status.get('status', 'cli_error')}")


def run_digest(case_dirs: list[Path], as_json: bool = False) -> str:
    command = [sys.executable, str(DIGEST), *[str(path) for path in case_dirs]]
    if as_json:
        command.append("--json")
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout


def early_stop_hint(case_dirs: list[Path]) -> str | None:
    if not case_dirs:
        return None
    summary = json.loads(run_digest(case_dirs, as_json=True))["summary"]
    return summary["early_stop_hint"]


def build_command(args: argparse.Namespace, case: str, source: Path | None = None) -> list[str]:
    """The controller command of one case; ``source`` replaces the case's spec.json (sheet-only mode)."""
    source = source or args.inputs / case / "spec.json"
    command = [str(args.binary.resolve()), "run",
               "--task", str(args.out.resolve() / case / "task"),
               "--source", str(source.resolve()),
               # absolute(), not resolve(): a venv python is a symlink to the base interpreter,
               # and resolving it would leave the venv (no CAD packages).
               "--worker-python", str(args.worker_python.absolute()),
               "--worker-source", str(args.worker_source.resolve()),
               "--model", args.model]
    if args.basis:
        command += ["--provider-transfer-basis", args.basis]
    return command + args.extra


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", nargs="+", required=True, help="case ids, or one file of ids")
    parser.add_argument("--inputs", required=True, type=Path, help="folder holding <case>/spec.json")
    parser.add_argument("--out", required=True, type=Path, help="new round folder under main work/")
    parser.add_argument("--binary", required=True, type=Path, help="marinaframe controller")
    parser.add_argument("--worker-source", required=True, type=Path)
    parser.add_argument("--worker-python", required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=2,
                        help=f"concurrent cases (1-{MAX_JOBS}); CAD work is still serialized by the "
                             "controller's native admission lock, so more jobs mainly overlap model waits")
    parser.add_argument("--max-cases", type=int, default=4)
    parser.add_argument("--basis", help="provider transfer basis text (required for --policy live)")
    parser.add_argument("--no-early-stop", action="store_true")
    parser.add_argument("--model", default=DEVELOPMENT_MODELS,
                        help="ordered OpenCode Go models, comma-separated (default: %(default)s)")
    parser.add_argument("--sheet-only", action="store_true",
                        help="start each case from its drawing files through the app's intake, not its spec.json")
    args, extra = parser.parse_known_args(argv)
    if not 1 <= args.jobs <= MAX_JOBS:
        sys.exit(f"--jobs must be 1 to {MAX_JOBS}")
    if "--model" in extra:
        sys.exit("give --model once")
    if extra and (len(extra) % 2 or any(not flag.startswith("--") for flag in extra[0::2])):
        sys.exit(f"extra options must be --option value pairs: {extra}")
    args.extra = extra
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    main_root, worktrees = main_checkout(), worktree_roots()
    validate_out(args.out, main_root, worktrees)
    cases = load_cases(args.cases)[: args.max_cases]
    if not cases:
        sys.exit("no cases selected")
    for name, path in (("--binary", args.binary), ("--inputs", args.inputs),
                       ("--worker-python", args.worker_python), ("--worker-source", args.worker_source)):
        if not path.exists():
            sys.exit(f"{name} does not exist: {path}")
    if args.sheet_only:
        missing = [case for case in cases if not (args.inputs / case).is_dir()]
    else:
        missing = [case for case in cases if not (args.inputs / case / "spec.json").is_file()]
    if missing:
        needed = "case folder" if args.sheet_only else "spec.json"
        sys.exit(f"no {needed} under --inputs for: {', '.join(missing)}")
    options = dict(zip(args.extra[0::2], args.extra[1::2]))
    live = options.get("--policy") == "live"
    if live:
        # Claude models use the claude CLI's subscription login, never a key;
        # only OpenCode Go models in the list need OPENCODE_API_KEY*.
        uses_go = any(model in OPENCODE_GO_MODELS for model in args.model.split(","))
        if uses_go and not any(name.startswith("OPENCODE_API_KEY") and os.environ[name] for name in os.environ):
            sys.exit("no OPENCODE_API_KEY* variable is set; run: source scripts/load_opencode_keys.sh")
        if not args.basis:
            sys.exit("live policy needs an explicit provider transfer basis (--basis)")

    args.out.mkdir(parents=True)
    log = RoundLog(args.out / "round.log")
    # The controller takes the per-user native admission lock itself; record the
    # same path the earlier drivers logged (rust-control/src/worker.rs).
    admission_lock = (Path(os.environ.get("TMPDIR") or "/tmp")
                      / f"marinaframe-native-admission-{os.geteuid()}.lock").resolve()
    meta = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cases": cases, "jobs": args.jobs,
            "sheet_only": args.sheet_only, "models": args.model.split(","),
            "native_admission_lock": str(admission_lock), "binary": str(args.binary)}
    (args.out / "round.json").write_text(json.dumps(meta, indent=2) + "\n")
    log.write(f"round of {len(cases)} case(s), jobs {args.jobs}, models {args.model}, out {args.out}")

    # The first EARLY_STOP_AFTER cases run first; if they fail the same way, the round stops.
    # The rest then run in a pool: a new case starts as soon as any case ends.
    finished: list[Path] = []

    def run_all(batch: list[str]) -> None:
        with ThreadPoolExecutor(max_workers=min(args.jobs, len(batch))) as pool:
            list(pool.map(lambda case: run_case(log, args, case), batch))
        finished.extend(args.out / case for case in batch)

    first, rest = cases[:EARLY_STOP_AFTER], cases[EARLY_STOP_AFTER:]
    run_all(first)
    hint = None if args.no_early_stop or not rest else early_stop_hint(finished)
    if hint:
        log.write(f"early stop: {hint}")
        meta["early_stop_hint"] = hint
    elif rest:
        run_all(rest)
    (args.out / "digest.md").write_text(f"Models (in fallback order): {args.model}\n\n" + run_digest(finished))
    meta["finished"] = [path.name for path in finished]
    (args.out / "round.json").write_text(json.dumps(meta, indent=2) + "\n")
    log.write(f"digest written for {len(finished)} case(s): {args.out / 'digest.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
