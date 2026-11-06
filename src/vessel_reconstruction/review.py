"""Serialized local review events; inference records remain immutable."""
from __future__ import annotations

import fcntl
import os
from datetime import datetime, timezone
from pathlib import Path

from .provenance import digest_file, digest_object, safe_relative_file, write_json
from .run_record import verify_run, MAX_RECORD_BYTES
from .schema import load_bounded_json

REVIEW_LIMITATION = ("Local named review record only; no authenticated signatory, professional authorization, "
                    "digital signature or class approval is implied.")


def _history(root: Path, run_id: str, evidence_hash: str) -> list:
    path = root / "review_history.json"
    history = load_bounded_json(safe_relative_file(root, "review_history.json"), max_bytes=8 * 1024 * 1024) if path.exists() else []
    if not isinstance(history, list) or len(history) > 1024:
        raise ValueError("Review history exceeds the supported event bound or has invalid structure.")
    previous = ""
    for event in history:
        if not isinstance(event, dict):
            raise ValueError("Review history hash chain is inconsistent.")
        payload = {key: value for key, value in event.items() if key != "event_sha256"}
        if (event.get("previous_event_sha256") != previous or digest_object(payload) != event.get("event_sha256")
                or event.get("run_id") != run_id or event.get("evidence_sha256") != evidence_hash
                or event.get("engineering_approved") is not False or event.get("identity_verified") is not False):
            raise ValueError("Review history hash chain or evidence binding is inconsistent.")
        previous = event["event_sha256"]
    return history


def review_state(run_dir: str | Path) -> dict:
    """Derive review display state from the checked history, not inference JSON."""
    root = Path(run_dir)
    if not verify_run(root)["valid"]:
        raise ValueError("Immutable run evidence no longer verifies; review is blocked.")
    result = load_bounded_json(safe_relative_file(root, "result.json"), max_bytes=MAX_RECORD_BYTES, max_nodes=3_000_000)
    history = _history(root, result["run_id"], digest_file(safe_relative_file(root, "manifest.json")))
    if not history:
        return {"state": "unreviewed", "engineering_approved": False, "identity_verified": False,
                "limitation": REVIEW_LIMITATION}
    event = history[-1]
    return {"state": event["decision"], "engineering_approved": False,
            "reviewer": event["reviewer"], "notes": event["notes"],
            "latest_event_sha256": event["event_sha256"], "identity_verified": False,
            "limitation": REVIEW_LIMITATION}


def record_review(run_dir: str | Path, *, decision: str, reviewer: str, notes: str, expected_run_id: str) -> dict:
    root = Path(run_dir)
    if not isinstance(decision, str) or decision not in ("accept_geometry", "reject", "needs_information"):
        raise ValueError("Unknown review decision.")
    if (not isinstance(reviewer, str) or not 1 <= len(reviewer.strip()) <= 256
            or not isinstance(notes, str) or not 1 <= len(notes.strip()) <= 4096):
        raise ValueError("A bounded reviewer identity and explanatory notes are required.")
    verification = verify_run(root)
    if not verification["valid"]:
        raise ValueError("Immutable source, inference, or export evidence no longer verifies; review is blocked.")
    lock_path = root / ".review.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        verification = verify_run(root)
        if not verification["valid"]:
            raise ValueError("Immutable evidence changed while acquiring the review lock.")
        result = load_bounded_json(safe_relative_file(root, "result.json"), max_bytes=MAX_RECORD_BYTES, max_nodes=3_000_000)
        if result.get("run_id") != expected_run_id:
            raise ValueError("The run identifier changed or is not the intended run.")
        if decision == "accept_geometry" and not verification["exports_allowed"]:
            raise ValueError("A blocked or incomplete reconstruction cannot be accepted.")
        evidence_hash = digest_file(safe_relative_file(root, "manifest.json"))
        history = _history(root, expected_run_id, evidence_hash)
        if len(history) >= 1024:
            raise ValueError("Review event limit reached; preserve and export the existing history.")
        event = {"schema_version": "2.0", "run_id": expected_run_id, "decision": decision,
                 "reviewer": reviewer.strip(), "notes": notes.strip(),
                 "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                 "previous_event_sha256": history[-1]["event_sha256"] if history else "",
                 "evidence_sha256": evidence_hash, "evidence_binding": "immutable_manifest_sha256",
                 "engineering_approved": False, "identity_verified": False}
        event["event_sha256"] = digest_object(event)
        history.append(event)
        # History is authoritative; review_state is an explicitly mutable cache.
        # A failure between writes leaves a valid appended event, never a changed
        # inference record. review_state() always derives from that history.
        write_json(root / "review_history.json", history)
        state = {"schema_version": "2.0", "run_id": expected_run_id, "state": decision,
                 "engineering_approved": False, "reviewer": reviewer.strip(), "notes": notes.strip(),
                 "latest_event_sha256": event["event_sha256"], "identity_verified": False,
                 "limitation": REVIEW_LIMITATION}
        write_json(root / "review_state.json", state)
        return event
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
