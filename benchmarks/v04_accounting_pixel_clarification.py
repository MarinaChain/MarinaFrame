"""Clarify dev8 first-request pixels from terminal accounting and bound receipts.

Read-only evidence derivation. No provider, native, image-pixel, request-payload,
credential, sealed-source or evaluator-reference access. Existing accounting
snapshots and request counts are never rewritten.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def derive(root: Path) -> dict:
    observed = {}

    def read(path: Path):
        raw = path.read_bytes()
        observed[str(path)] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        return json.loads(raw)

    accounting = read(root / "accounting.json")
    attempts_path = root / "provider-attempts.jsonl"
    raw = attempts_path.read_bytes()
    observed[str(attempts_path)] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    attempts = [json.loads(line) for line in raw.splitlines() if line]
    rows = sorted((r for r in accounting["trials"] if r["cohort"].startswith("dev8-")),
                  key=lambda r: r["trial"])
    if len(rows) != 6 or {r["trial"] for r in rows} != {f"trial-{i:02d}/task" for i in range(1, 7)}:
        raise ValueError("Expected the completed, separately declared six-trial dev8 cohort")
    results = []
    image_keys = ("artifact_id", "sha256", "bytes", "evidence_kind", "view",
                  "generation_id", "revision_id", "step_sha256", "pixels_attached")
    for row in rows:
        task = Path(row["original_task"])
        if not task.is_relative_to("/tmp/marinaframe-v04-dev8"):
            raise ValueError("Only original dev8 tasks are admitted")
        checkpoint_path = task / "state.json"
        checkpoint = read(checkpoint_path)
        if checkpoint["head_sha256"] != row["head_sha256"] or row["strict_valid"] is not True:
            raise ValueError("Original terminal task differs from strictly verified accounting")
        calls = [c for c in attempts if c["task_id"] == row["task_id"] and c["outcome"] == "completed"]
        first = min(calls, key=lambda c: c["receipt_event_sequence"])
        receipt_path = Path(first["receipt_path"])
        if not receipt_path.is_relative_to(task / "receipts"):
            raise ValueError("Foreign receipt")
        receipt = read(receipt_path)
        if observed[str(receipt_path)]["sha256"] != first["receipt_sha256"]:
            raise ValueError("Receipt bytes changed since accounting")
        event_path = task / "events" / f"{first['receipt_event_sequence']:08d}.json"
        event = read(event_path)
        artifact = event["payload"]["receipt_file"]
        if (event["kind"] != "provider_result" or receipt["state"] != "completed"
                or artifact["sha256"] != first["receipt_sha256"]
                or (task / artifact["path"]) != receipt_path
                or receipt["request_id"] != first["request_id"]
                or json.dumps(receipt, sort_keys=True) != json.dumps(event["payload"]["receipt"], sort_keys=True)):
            raise ValueError("First completed receipt lacks its exact committed binding")
        normalized_images = [{key: image.get(key) for key in image_keys} for image in receipt["images"]]
        if normalized_images != first["images"]:
            raise ValueError("Receipt image metadata differs from accounting")
        prior = min((b for b in row["build_observations"] if b["valid"] is True), key=lambda b: b["sequence"])
        if prior["sequence"] >= first["intent_sequence"] or prior["actor"] != "assistant_operator":
            raise ValueError("Seeded candidate was not established before the first request")
        bound = [image for image in normalized_images
                 if image["pixels_attached"] is True
                 and image["evidence_kind"] == "step_reimport_render"
                 and image["view"] in {"body", "oblique"}
                 and all(image[key] == prior[key] for key in ("generation_id", "revision_id", "step_sha256"))]
        if {i["view"] for i in bound} != {"body", "oblique"}:
            raise ValueError("First completed request lacks one or both bound prior views")
        if any(re.fullmatch(r"[0-9a-f]{64}", i["sha256"] or "") is None for i in bound):
            raise ValueError("Image identity is malformed")
        validation = checkpoint["state"].get("domain", {}).get("validation")
        binding = ((validation or {}).get("contract") or {}).get("binding") or {}
        results.append({
            "cohort": row["cohort"], "trial": row["trial"], "task_id": row["task_id"],
            "terminal_status": row["historical_status"], "terminal_head_sha256": row["head_sha256"],
            "strict_history_valid": row["strict_valid"], "assistant_setup_actions": row["assistant_setup_actions"],
            "prior_candidate_build": prior, "first_completed_request_id": first["request_id"],
            "intent_sequence": first["intent_sequence"], "receipt_event_sequence": first["receipt_event_sequence"],
            "receipt_path": str(receipt_path), "receipt_sha256": first["receipt_sha256"],
            "receipt_event_path": str(event_path), "receipt_event_sha256": observed[str(event_path)]["sha256"],
            "bound_prior_images": bound, "first_completed_request_has_bound_prior_body_and_oblique": True,
            "other_attached_evidence_kinds": sorted({i["evidence_kind"] for i in normalized_images
                                                     if i["pixels_attached"] is True and i not in bound}),
            "terminal_validation_step_binding_present": bool(binding.get("step_sha256")),
            "terminal_audit_bound_views_from_original_accounting": row["final_current_STEP_views_on_completed_receipts"],
            "terminal_checkpoint_path": str(checkpoint_path),
            "terminal_checkpoint_sha256": observed[str(checkpoint_path)]["sha256"],
        })
    unchanged = all(digest(Path(path)) == item["sha256"] for path, item in observed.items())
    if not unchanged:
        raise ValueError("An original observation source changed")
    return {
        "schema_version": "marinaframe.accounting-pixel-clarification.v1",
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "script_sha256": digest(Path(__file__)), "trials": results,
        "all_six_first_completed_requests_have_bound_prior_body_and_oblique": True,
        "inputs": observed, "all_input_bytes_unchanged": unchanged,
        "accounting_snapshot_or_denominator_changes": False,
        "native_calls": 0, "provider_calls": 0, "image_pixel_reads": 0,
        "request_payload_reads": 0, "credential_reads": 0, "sealed_reference_reads": 0,
        "meaning": "Bound receipt metadata establishes attached prior pixels. It does not establish model attention, comprehension, correction, semantic accuracy or engineering approval.",
        "empty_final_list_explanation": "The original field matches completed image receipts to the terminal validation contract's STEP hash. Abstained trials01/03/04/06 have no such terminal validation binding, even though their first completed requests attached both bound prior views.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accounting", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = derive(args.accounting.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"trials": len(result["trials"]), "all_prior_views_bound": True,
                      "input_files": len(result["inputs"]), "all_input_bytes_unchanged": True}))


if __name__ == "__main__":
    main()
