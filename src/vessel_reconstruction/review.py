"""Local review history; records decisions, never grants class certification."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

from .pipeline import verify_run
from .provenance import digest_object, write_json


def record_review(run_dir: str | Path, *, decision: str, reviewer: str, notes: str, expected_run_id: str) -> dict:
    root = Path(run_dir)
    result_path = root / "result.json"
    result = json.loads(result_path.read_text())
    if result.get("run_id") != expected_run_id:
        raise ValueError("The run identifier changed or is not the intended run.")
    if decision not in {"accept_geometry", "reject", "needs_information"}:
        raise ValueError("Unknown review decision.")
    if not reviewer.strip() or not notes.strip():
        raise ValueError("A reviewer identity and explanatory notes are required.")
    if not verify_run(root)["valid"]:
        raise ValueError("Source or export hashes no longer match; review is blocked.")
    if decision == "accept_geometry" and (not result.get("exports") or any(g.get("severity", "blocking") == "blocking" for g in result.get("gaps", []))):
        raise ValueError("A blocked or incomplete reconstruction cannot be accepted.")
    history_path = root / "review_history.json"
    history = json.loads(history_path.read_text()) if history_path.exists() else []
    previous = ""
    for event in history:
        payload = {k: v for k, v in event.items() if k != "event_sha256"}
        if event.get("previous_event_sha256") != previous or digest_object(payload) != event.get("event_sha256"):
            raise ValueError("Review history hash chain is inconsistent.")
        previous = event["event_sha256"]
    event = {"run_id": expected_run_id, "decision": decision, "reviewer": reviewer.strip(), "notes": notes.strip(), "timestamp_utc": datetime.now(timezone.utc).isoformat(), "previous_event_sha256": previous, "evidence_sha256": digest_object(result["provenance"]), "engineering_approved": False, "identity_verified": False}
    event["event_sha256"] = digest_object(event)
    history.append(event)
    write_json(history_path, history)
    result["review"] = {"state": decision, "engineering_approved": False, "reviewer": reviewer.strip(), "notes": notes.strip(), "latest_event_sha256": event["event_sha256"], "identity_verified": False, "limitation": "Local named review record only; no authenticated signatory, professional authorization, digital signature or class approval is implied."}
    write_json(result_path, result)
    return event

