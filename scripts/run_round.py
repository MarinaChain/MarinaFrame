#!/usr/bin/env python3
"""Run one small live-model MarinaFrame test round the standard way.

    source scripts/load_opencode_keys.sh
    python scripts/run_round.py --cases c1 c2 --inputs work/factory/inputs \
        --out ../work/round-foo --binary rust-control/target/release/marinaframe \
        --worker-source src --worker-python .venv/bin/python \
        --policy live --on-ambiguity draft --context conversation

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
DIGEST = SCRIPTS / "round_digest.py"
EARLY_STOP_AFTER = 2  # finished cases after which the digest may stop the round


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


def run_case(log: RoundLog, command: list[str], case_dir: Path) -> None:
    case_dir.mkdir(parents=True, exist_ok=False)
    (case_dir / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    started = time.perf_counter()
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


def build_command(args: argparse.Namespace, case: str) -> list[str]:
    command = [str(args.binary.resolve()), "run",
               "--task", str(args.out.resolve() / case / "task"),
               "--source", str(args.inputs.resolve() / case / "spec.json"),
               # absolute(), not resolve(): a venv python is a symlink to the base interpreter,
               # and resolving it would leave the venv (no CAD packages).
               "--worker-python", str(args.worker_python.absolute()),
               "--worker-source", str(args.worker_source.resolve())]
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
    parser.add_argument("--jobs", type=int, default=2, help="concurrent cases (1-2)")
    parser.add_argument("--max-cases", type=int, default=4)
    parser.add_argument("--basis", help="provider transfer basis text (required for --policy live)")
    parser.add_argument("--no-early-stop", action="store_true")
    args, extra = parser.parse_known_args(argv)
    if not 1 <= args.jobs <= 2:
        sys.exit("--jobs must be 1 or 2 (small rounds only)")
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
    missing = [case for case in cases if not (args.inputs / case / "spec.json").is_file()]
    if missing:
        sys.exit(f"no spec.json under --inputs for: {', '.join(missing)}")
    options = dict(zip(args.extra[0::2], args.extra[1::2]))
    live = options.get("--policy") == "live"
    if live:
        if not any(name.startswith("OPENCODE_API_KEY") and os.environ[name] for name in os.environ):
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
            "native_admission_lock": str(admission_lock), "binary": str(args.binary)}
    (args.out / "round.json").write_text(json.dumps(meta, indent=2) + "\n")
    log.write(f"round of {len(cases)} case(s), jobs {args.jobs}, out {args.out}")

    finished: list[Path] = []
    for start in range(0, len(cases), args.jobs):
        wave = cases[start: start + args.jobs]
        with ThreadPoolExecutor(max_workers=len(wave)) as pool:
            list(pool.map(lambda case: run_case(log, build_command(args, case), args.out / case), wave))
        finished.extend(args.out / case for case in wave)
        if not args.no_early_stop and EARLY_STOP_AFTER <= len(finished) < len(cases):
            hint = early_stop_hint(finished)
            if hint:
                log.write(f"early stop: {hint}")
                meta["early_stop_hint"] = hint
                break
    (args.out / "digest.md").write_text(run_digest(finished))
    meta["finished"] = [path.name for path in finished]
    (args.out / "round.json").write_text(json.dumps(meta, indent=2) + "\n")
    log.write(f"digest written for {len(finished)} case(s): {args.out / 'digest.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
