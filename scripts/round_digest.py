#!/usr/bin/env python3
"""Digest finished MarinaFrame controller task folders into a short markdown report.

Use it after a small LLM test round, before launching a bigger one:

    python scripts/round_digest.py RUN_DIR [RUN_DIR ...] [--json]

Each RUN_DIR is a case folder holding task/events/*.json (or a task folder that
holds events/*.json directly). result.json and stdout.log are optional.
Standard library only. Missing fields are tolerated.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# worker_result statuses that count as a blocker (not progress).
BLOCKING_STATUSES = {"blocked", "failed", "rejected", "proposal_refused", "refused", "error"}
# Event kinds that are a blocker by themselves.
BLOCKING_KINDS = ("operation_rejected", "model_output_rejected", "repeated_action_refused")
SUCCESS_STATUSES = {"complete", "completed", "succeeded", "success", "approved", "done"}
MAX_TOOL_RUNS = 12  # longest tool sequence shown per case
EARLY_STOP_MIN_CASES = 2  # fewer cases than this cannot show a pattern
LAST_REASONS = 3
MESSAGE_LIMIT = 140


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def find_events_dir(case_dir: Path) -> Path | None:
    for candidate in (case_dir / "task" / "events", case_dir / "events"):
        if candidate.is_dir():
            return candidate
    return None


def load_events(case_dir: Path) -> list[dict]:
    events_dir = find_events_dir(case_dir)
    if events_dir is None:
        return []
    events = [e for e in (read_json(p) for p in sorted(events_dir.glob("*.json"))) if isinstance(e, dict)]
    return sorted(events, key=lambda e: e.get("sequence") or 0)


def clip(text: Any, limit: int = MESSAGE_LIMIT) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def compress_tools(tools: list[str]) -> str:
    """['a','a','a','b'] -> 'a x3 > b'."""
    parts: list[str] = []
    for tool in tools:
        if parts and parts[-1][0] == tool:
            parts[-1][1] += 1
        else:
            parts.append([tool, 1])
    shown = [f"{t} x{n}" if n > 1 else t for t, n in parts]
    if len(shown) > MAX_TOOL_RUNS:
        shown = shown[:MAX_TOOL_RUNS] + [f"... (+{len(shown) - MAX_TOOL_RUNS} more runs)"]
    return " > ".join(shown) or "(none)"


def action_key(decision: dict) -> str:
    return json.dumps([decision.get("tool"), decision.get("arguments")], sort_keys=True, default=str)


def worker_blocker(event: dict) -> dict | None:
    payload = as_dict(event.get("payload"))
    response = as_dict(payload.get("response"))
    result = as_dict(response.get("result"))
    status = result.get("status") or response.get("status")
    code = result.get("error_code") or response.get("error_code")
    if not code and status not in BLOCKING_STATUSES:
        return None
    return {
        "seq": event.get("sequence"),
        "source": f"worker_result:{payload.get('operation')}",
        "code": code or status,
        "message": clip(result.get("message") or response.get("message") or status),
    }


def event_blocker(event: dict) -> dict | None:
    kind = event.get("kind")
    payload = as_dict(event.get("payload"))
    if kind == "worker_result":
        return worker_blocker(event)
    if kind in BLOCKING_KINDS:
        decision = as_dict(payload.get("decision"))
        return {
            "seq": event.get("sequence"),
            "source": f"{kind}:{decision.get('tool')}",
            "code": payload.get("error_code") or payload.get("reason") or kind,
            "message": clip(payload.get("message") or payload.get("reason") or decision.get("reason")),
        }
    return None


def first_repeat(events: list[dict]) -> dict | None:
    seen: dict[str, Any] = {}
    for event in events:
        if event.get("kind") != "decision":
            continue
        decision = as_dict(as_dict(event.get("payload")).get("decision"))
        key = action_key(decision)
        if key in seen:
            return {
                "seq": event.get("sequence"),
                "source": f"repeat:{decision.get('tool')}",
                "code": "repeated_identical_action",
                "message": f"same tool+arguments as event {seen[key]}",
            }
        seen[key] = event.get("sequence")
    return None


def first_blocker(events: list[dict]) -> dict | None:
    found = [b for b in (event_blocker(e) for e in events) if b]
    repeat = first_repeat(events)
    if repeat:
        found.append(repeat)
    return min(found, key=lambda b: b["seq"] or 0) if found else None


def model_reasons(events: list[dict]) -> list[str]:
    """Reasons given by the model, from provider receipts (also covers rejected outputs)."""
    reasons = []
    for event in events:
        payload = as_dict(event.get("payload"))
        if event.get("kind") == "provider_result":
            reason = as_dict(as_dict(payload.get("receipt")).get("decision")).get("reason")
        elif event.get("kind") == "decision" and payload.get("actor") not in (None, "deterministic_policy"):
            reason = as_dict(payload.get("decision")).get("reason")
        else:
            continue
        if reason:
            reasons.append(clip(reason, 200))
    return reasons[-LAST_REASONS:]


def draft_state(events: list[dict], case_dir: Path, stdout: dict) -> str:
    """'valid draft' only when a build produced a valid candidate; a blocked build is not a draft."""
    builds = [
        as_dict(as_dict(as_dict(e.get("payload")).get("response")).get("result"))
        for e in events
        if e.get("kind") == "worker_result" and as_dict(e.get("payload")).get("operation") == "build_draft"
    ]
    valid = any(as_dict(b.get("candidate")).get("valid") is True for b in builds)
    has_step = any(case_dir.rglob("*.step")) or any(case_dir.rglob("*.stp"))
    if valid or has_step:
        return "valid draft" + (" + STEP" if has_step else "")
    if builds:
        return f"build attempted {len(builds)}x, none valid"
    return "no draft"


def request_stats(events: list[dict], stdout: dict, result: dict, case_dir: Path) -> tuple[int, float | None]:
    counters = as_dict(stdout.get("counters"))
    receipts = [
        as_dict(as_dict(e.get("payload")).get("receipt"))
        for e in events
        if e.get("kind") == "provider_result"
    ]
    requests = counters.get("requests_completed", len(receipts))
    cost = result.get("list_cost_usd")
    if cost is None:
        cost = receipt_list_cost(case_dir)
    return int(requests or 0), cost


def receipt_list_cost(case_dir: Path) -> float | None:
    """Sum provider-reported nominal list cost from request receipts (usage.list_cost)."""
    total, found = 0.0, False
    for path in case_dir.glob("task/receipts/request-*.json"):
        try:
            usage = as_dict(json.loads(path.read_text()).get("usage"))
        except (OSError, ValueError):
            continue
        if isinstance(usage.get("list_cost"), (int, float)):
            total += usage["list_cost"]
            found = True
    return total if found else None


def receipt_models(case_dir: Path) -> dict:
    """Requests per model (requested -> returned) from the request receipts."""
    counts: Counter = Counter()
    for path in sorted(case_dir.glob("task/receipts/request-*.json")):
        try:
            receipt = as_dict(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
        requested = receipt.get("requested_model") or "?"
        returned = receipt.get("returned_model") or "none"
        counts[requested if requested == returned else f"{requested} -> {returned}"] += 1
    return dict(counts)


def digest_case(case_dir: Path) -> dict:
    events = load_events(case_dir)
    stdout = as_dict(read_json(case_dir / "stdout.log") or read_json(case_dir / "stdout.json"))
    result = as_dict(read_json(case_dir / "result.json"))
    terminated = next(
        (as_dict(e.get("payload")) for e in reversed(events) if e.get("kind") == "task_terminated"), {}
    )
    decisions = [
        as_dict(as_dict(e.get("payload")).get("decision")) for e in events if e.get("kind") == "decision"
    ]
    tools = [d.get("tool") or "?" for d in decisions]
    requests, cost = request_stats(events, stdout, result, case_dir)
    counters = as_dict(stdout.get("counters"))
    switches = [as_dict(e.get("payload")) for e in events if e.get("kind") == "model_switched"]
    return {
        "case": case_dir.name,
        "status": stdout.get("status") or result.get("controller_status") or ("terminated" if terminated else "unknown"),
        "reason": terminated.get("reason") or stdout.get("termination_reason") or result.get("termination_reason") or "none",
        "events": len(events),
        "decisions": len(decisions),
        "tools": tools,
        "tool_sequence": compress_tools(tools),
        "first_blocker": first_blocker(events),
        "last_reasons": model_reasons(events),
        "draft": draft_state(events, case_dir, stdout),
        "requests": requests,
        "list_cost_usd": cost,
        "models": receipt_models(case_dir),
        "model_switches": [f"{w.get('from')} -> {w.get('to')} ({w.get('reason')})" for w in switches],
        "prompt_tokens": counters.get("prompt_tokens"),
        "completion_tokens": counters.get("completion_tokens"),
    }


def blocker_label(case: dict) -> str:
    b = case["first_blocker"]
    return f"{b['source'].split(':')[0]}:{b['code']}" if b else "none"


def summarize(cases: list[dict]) -> dict:
    reasons = Counter(c["reason"] for c in cases)
    blockers = Counter(blocker_label(c) for c in cases)
    tools = Counter(t for c in cases for t in c["tools"])
    total = len(cases)
    top_reason, top_reason_n = reasons.most_common(1)[0] if reasons else ("none", 0)
    top_blocker, top_blocker_n = blockers.most_common(1)[0] if blockers else ("none", 0)
    # A case that ends with a valid draft is a success in draft mode (happy path first),
    # whatever its stop reason.
    failed = [c["status"] not in SUCCESS_STATUSES and not c["draft"].startswith("valid draft")
              for c in cases]
    same_prefix = 0  # leading failed cases, in run order, that ended with the top reason
    for case, case_failed in zip(cases, failed):
        if not case_failed or case["reason"] != top_reason:
            break
        same_prefix += 1
    if not cases:
        verdict = "no cases found"
    else:
        drafts = sum(c["draft"].startswith("valid draft") for c in cases)
        verdict = (
            f"{drafts}/{total} valid drafts; {sum(failed)}/{total} failed; most common end `{top_reason}` ({top_reason_n}/{total}); "
            f"most common first blocker `{top_blocker}` ({top_blocker_n}/{total})"
        )
    hint = None
    if same_prefix >= EARLY_STOP_MIN_CASES:
        hint = f"first {same_prefix} cases fail the same way (`{top_reason}`): stop the round and fix this first"
    return {
        "termination_reasons": reasons.most_common(),
        "first_blockers": blockers.most_common(),
        "tool_totals": tools.most_common(),
        "total_requests": sum(c["requests"] for c in cases),
        "total_list_cost_usd": sum(c["list_cost_usd"] or 0 for c in cases),
        "dominant_failure": verdict,
        "early_stop_hint": hint,
    }


def latest_valid_draft_step(events: list[dict], case_dir: Path) -> Path | None:
    """The STEP file of the last build that produced a valid candidate, or None."""
    for event in reversed(events):
        payload = as_dict(event.get("payload"))
        if event.get("kind") != "worker_result" or payload.get("operation") != "build_draft":
            continue
        candidate = as_dict(as_dict(as_dict(payload.get("response")).get("result")).get("candidate"))
        if candidate.get("valid") is True and isinstance(candidate.get("path"), str):
            for name in ("model-draft.step", "model.step"):
                step = case_dir / "task" / candidate["path"] / name
                if step.is_file():
                    return step
    # Builds made by other operations (for example the vessel-table first hull) record no
    # build_draft result: the task's last valid candidate is its draft. A newer STEP can
    # belong to a reading the task set aside (first_hull_tools.keep_better_reading).
    state = case_dir / "task" / "domain" / "state.json"
    try:
        candidate = as_dict(json.loads(state.read_text()).get("last_valid_candidate"))
    except (OSError, ValueError):
        candidate = {}
    if candidate.get("valid") is True and isinstance(candidate.get("path"), str):
        for name in ("model-draft.step", "model.step"):
            step = case_dir / "task" / candidate["path"] / name
            if step.is_file():
                return step
    # No state names a candidate: the newest draft STEP in the task's builds.
    steps = sorted((case_dir / "task").glob("domain/builds/*/model-draft.step"), key=lambda p: p.stat().st_mtime)
    return steps[-1] if steps else None


def truth_hull_name(case_id: str) -> str:
    """The truth file stem of a factory case: "dtmb5415-3v-L0" -> "dtmb5415".

    The level suffix ("-L0") is dropped, and so is the three-view set marker ("-3v"),
    because one hull's truth serves both the body-plan and the three-view sets."""
    hull = case_id.rsplit("-L", 1)[0]
    return hull.removesuffix("-3v")


def score_case(case: dict, case_dir: Path, events: list[dict], factory: Path) -> None:
    """Score the case's final valid draft against DEVELOPMENT truth with the frozen factory
    scorer and gate (2 % RMS half-beam, 5 % in-range volume). Never use it on sealed data."""
    from benchmarks.factory import report, truth  # noqa: PLC0415 (needs the repo on sys.path)
    step = latest_valid_draft_step(events, case_dir)
    case_id = case_dir.name
    if step is None:
        case["score"] = None
        return
    params = json.loads((factory / "params" / f"{case_id}.json").read_text())
    stations = [{"id": f"s{i + 1:02d}", "x_m": x} for i, x in enumerate(params["station_x_m"])]
    hull = truth_hull_name(case_id)
    try:
        score = truth.score_model(factory / "sealed" / "truth" / f"{hull}.npz", step, stations)
    except Exception as exc:  # a scoring failure is reported, not raised
        case["score"] = {"status": "scoring_error", "error": type(exc).__name__}
        return
    main = score.get("summary", {}).get("half_breadth_main")
    hydro = score.get("hydrostatics_at_design_draft", {})
    rms_pct = 100 * main["rms_of_station_rms_m"] / score["truth"]["max_half_breadth_m"] if main else None
    volume = hydro.get("volume_error_relative_within_range")
    case["score"] = {"rms_pct_half_beam": rms_pct, "volume_error_in_range": volume,
                     "correct": bool(rms_pct is not None and rms_pct <= 100 * report.RMS_GATE_FRACTION
                                     and volume is not None and abs(volume) <= report.VOLUME_GATE)}


def render_markdown(cases: list[dict], summary: dict) -> str:
    out = [f"# Round digest ({len(cases)} cases)", ""]
    for c in cases:
        out.append(f"## {c['case']}")
        out.append(f"- end: status `{c['status']}`, reason `{c['reason']}`")
        out.append(f"- decisions: {c['decisions']}; tools: {c['tool_sequence']}")
        b = c["first_blocker"]
        if b:
            out.append(f"- first blocker (event {b['seq']}, {b['source']}): `{b['code']}` - {b['message']}")
        else:
            out.append("- first blocker: none found")
        for reason, repeats in Counter(c["last_reasons"]).items():
            out.append(f"  - model{f' (x{repeats})' if repeats > 1 else ''}: {reason}")
        cost = "n/a" if not c["list_cost_usd"] else f"${c['list_cost_usd']:.4f}"
        out.append(f"- {c['draft']}; requests {c['requests']}; list cost {cost}")
        models = ", ".join(f"{m} x{n}" for m, n in c.get("models", {}).items()) or "none"
        out.append(f"- models: {models}; tokens in/out {c.get('prompt_tokens')}/{c.get('completion_tokens')}")
        for switch in c.get("model_switches", []):
            out.append(f"  - model switch: {switch}")
        score = c.get("score")
        if score and "correct" in score:
            rms = "n/a" if score["rms_pct_half_beam"] is None else f"{score['rms_pct_half_beam']:.2f}%"
            vol = "n/a" if score["volume_error_in_range"] is None else f"{100 * score['volume_error_in_range']:+.1f}%"
            out.append(f"- score (dev truth): {'CORRECT' if score['correct'] else 'wrong'}; RMS {rms} of half-beam; volume {vol}")
        elif score:
            out.append(f"- score: {score['status']} ({score.get('error')})")
        out.append("")
    out.append("## Across cases")
    out.append("- termination: " + ", ".join(f"{r} x{n}" for r, n in summary["termination_reasons"]))
    out.append("- first blockers: " + ", ".join(f"{r} x{n}" for r, n in summary["first_blockers"][:5]))
    out.append("- tool totals: " + ", ".join(f"{t} x{n}" for t, n in summary["tool_totals"][:8]))
    out.append(f"- requests {summary['total_requests']}; list cost ${summary['total_list_cost_usd']:.4f}")
    scored = [c for c in cases if c.get("score") and "correct" in c["score"]]
    if scored:
        out.append(f"- correct (dev truth, frozen gate): {sum(c['score']['correct'] for c in scored)}/{len(cases)} cases "
                   f"({len(scored)} drafts scored)")
    out.append(f"- dominant failure: {summary['dominant_failure']}")
    if summary["early_stop_hint"]:
        out.append(f"- **early stop:** {summary['early_stop_hint']}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+", type=Path, help="finished case/task folders, in run order")
    parser.add_argument("--json", action="store_true", help="print JSON instead of markdown")
    parser.add_argument("--factory", type=Path,
                        help="DEVELOPMENT factory folder (params/, sealed/truth/) to score final drafts; "
                             "never a sealed evaluation split")
    args = parser.parse_args(argv)
    cases = [digest_case(path) for path in args.runs]
    if args.factory:
        if "sealed-v" in str(args.factory.resolve()):
            parser.error("--factory must be development data, not a sealed evaluation split")
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        for case, path in zip(cases, args.runs):
            score_case(case, path, load_events(path), args.factory)
    summary = summarize(cases)
    if args.json:
        print(json.dumps({"cases": cases, "summary": summary}, indent=2, default=str))
    else:
        print(render_markdown(cases, summary), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
