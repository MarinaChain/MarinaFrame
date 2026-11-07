#!/usr/bin/env python3
"""Export retained v0.4 scores and intake receipts; never run or rescore a model.

Only the published summary, its bound per-case scores, and the locked initial
intake archive are read.  All numeric cells preserve Python's round-trip decimal
representation.  Blank cells mean unavailable or inapplicable, never imputed 0.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import tarfile


SUMMARY_SHA256 = "d7576b332fc1fae15da52d403ff4f74337d648080745ab12c4373aa107e860f8"
INTAKE_SHA256 = "2e53e6a4ff1fd5f8d6f68ced64f69a921f9e93dbd2adb3b4ada239d13f3d2a17"
COHORTS = {
    "candidate": "supported_procedural",
    "refuse": "procedural_diagnostic",
    "refuse_or_request_evidence": "authentic_partial_no_3d_gold",
}
DIRECT = (
    "attempted process_finalized terminal_record_present workflow_status exit_code "
    "termination_reason execution_failed interrupted_truncated resource_limited "
    "no_progress current_candidate ready_for_review engineering_approved "
    "current_revision current_generation"
).split()
REFUSAL = (
    "explicit_correct_refusal_or_request safe_diagnostic_nonacceptance "
    "no_progress_with_relevant_diagnostic incorrect_acceptance_under_original_label "
    "relevant_blocking_diagnostic"
).split()
GEOMETRY = {
    "independent_geometry_pass": "independent_geometry_pass",
    "source_pixels_per_metre": "source_pixels_per_metre",
    "reference_volume_m3": "reference_volume_m3",
    "reimported_volume_m3": "reimported_volume_m3",
    "volume_relative_error_fraction": "volume_relative_error",
    "section_required_ordinates": "required_ordinates",
    "section_unresolved_ordinates": "unresolved_ordinates",
    "section_resolved_fraction": "resolved_coverage",
    "section_rms_px_resolved_only": "section_rms_px_resolved_only",
    "section_max_px_resolved_only": "section_max_px_resolved_only",
    "competing_interior_ordinates": "competing_interior_ordinates",
    "interior_horizontal_overlap_ordinates": "interior_horizontal_overlap_ordinates",
    "full_span_grid_identity_checked": "full_span_grid_identity_checked",
}
TRACE = {
    "selected_trace_max_error_mm": "max_error_mm",
    "selected_trace_limit_mm": "limit_mm",
    "selected_trace_required_samples": "required_samples",
    "selected_trace_unresolved_samples": "unresolved_samples",
    "selected_trace_passed": "passed",
}
PIXEL = {
    "pixel_required_rows": "required_rows", "pixel_resolved_rows": "resolved_rows",
    "pixel_ambiguous_rows": "ambiguous_rows", "pixel_missing_rows": "missing_rows",
    "pixel_resolved_fraction": "resolved_coverage",
    "pixel_rms_px_resolved_only": "section_rms_px_resolved_only",
    "pixel_max_px_resolved_only": "section_max_px_resolved_only",
}
RESOURCES = (
    "execution_wall_seconds native_queue_wait_seconds cli_cpu_seconds "
    "cli_descendant_max_rss_kib task_disk_bytes wall_scope"
).split()
COUNTERS = (
    "builds operator_actions actions operations policy_calls policy_decisions "
    "rejections requests_intended requests_completed requests_failed "
    "requests_not_sent requests_unknown requests_without_cost prompt_tokens "
    "completion_tokens observed_cost_usd live_calls_reserved"
).split()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path: Path, expected: str | None = None):
    data = path.read_bytes()
    sha = digest(data)
    if expected is not None and sha != expected:
        raise ValueError(f"Retained source digest mismatch: {path}")
    return json.loads(data), sha


def cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("A nonfinite value cannot be represented as a measurement")
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return str(value)


def csv_bytes(rows):
    columns = list(rows[0])
    if any(list(row) != columns for row in rows):
        raise ValueError("Rows have inconsistent columns")
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows({k: cell(v) for k, v in row.items()} for row in rows)
    data = out.getvalue().encode("utf-8")
    parsed = list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))
    expected = [{k: cell(v) for k, v in row.items()} for row in rows]
    if parsed != expected:
        raise ValueError("CSV readback changed a retained value or blank")
    if len({(row["arm"], row["case_id"]) for row in rows}) != len(rows):
        raise ValueError("Duplicate arm/case identity")
    return data


def primary_rows(root: Path, summary):
    records, sources = {}, []
    for entry in summary["all_per_case_scores"]:
        relative = f"scoring/{entry['arm']}/{entry['case_id']}/score.json"
        score, sha = load(root / relative, entry["sha256"])
        key = (entry["arm"], entry["case_id"])
        if key in records or (score["arm"], score["case_id"]) != key:
            raise ValueError("Score identity mismatch or duplicate")
        records[key] = (score, relative, sha)
        sources.append({"path": relative, "sha256": sha, "original_path": entry["path"]})
    if len(records) != summary["primary_attempts"] or len(records) != 92:
        raise ValueError("Primary inventory changed")
    canonical = {case: value for (arm, case), value in records.items()
                 if arm == "new_rust_deterministic"}
    rows = []
    for (arm, case), (score, relative, sha) in sorted(records.items()):
        metadata, meta_path, meta_sha = canonical[case]
        for name in ("expected", "family_key", "convention", "negative"):
            if name in score and score[name] != metadata[name]:
                raise ValueError(f"Case metadata disagrees: {arm}/{case}/{name}")
        expected = score["expected"]
        pixel = arm == "simple_pixel_baseline"
        candidate = expected == "candidate"
        arm_scores = [value[0] for key, value in records.items() if key[0] == arm]
        cohort_scores = [r for r in arm_scores if r["expected"] == expected]
        supported = [r for r in arm_scores if r["expected"] == "candidate"]
        families = collections.Counter(canonical[r["case_id"]][0]["family_key"] for r in supported)
        row = {
            "inventory": "primary_v2", "arm": arm, "case_id": case,
            "attempt_id": score["attempt_id"], "cohort": COHORTS[expected],
            "expected_original": expected, "family_key": metadata["family_key"],
            "convention": metadata["convention"], "negative": metadata["negative"],
            "scope_ambiguous_diagnostic": metadata.get("scope_ambiguous_diagnostic") if expected == "refuse" else None,
            "sensitivity_negative_member": metadata.get("sensitivity_primary_negative_member") if expected == "refuse" else None,
            "arm_attempts_denominator": len(arm_scores),
            "cohort_attempts_denominator": len(cohort_scores),
            "cohort_process_finalized_denominator": sum(r["process_finalized"] for r in cohort_scores),
            "cohort_terminal_records_denominator": None if pixel else sum(r["terminal_record_present"] for r in cohort_scores),
            "cohort_current_exports_denominator": None if pixel else sum(bool(r.get("current_step")) for r in cohort_scores),
            "arm_supported_attempts_denominator": len(supported),
            "arm_supported_exports_denominator": None if pixel else sum(bool(r.get("current_step")) for r in supported),
            "arm_supported_distinct_families": len(families),
            "arm_complete_paired_families_denominator": sum(n == 2 for n in families.values()),
            "arm_original_negative_attempts_denominator": sum(r["expected"] == "refuse" for r in arm_scores),
            "arm_sensitivity_negative_attempts_denominator": sum(
                r["expected"] == "refuse" and canonical[r["case_id"]][0].get("sensitivity_primary_negative_member", False)
                for r in arm_scores),
            "evaluation_status": "source_only_prediction_finalized" if pixel else score["workflow_status"],
        }
        row.update({name: score.get(name) for name in DIRECT})
        row.update({
            "current_step_exported": score["CAD_exported"] if pixel else bool(score.get("current_step")),
            "rendered_views_json": score.get("rendered_views"),
            "supported_full_pass": score.get("full_supported_pass") if candidate and not pixel else None,
            "supported_false_refusal": score.get("supported_false_refusal") if candidate and not pixel else None,
        })
        row.update({name: score.get(name) if not candidate and not pixel else None for name in REFUSAL})
        row["diagnostic_kinds_json"] = sorted({r["kind"] for r in score["diagnostics"] if "kind" in r})
        row["matching_blocking_diagnostic_kinds_json"] = score.get("matching_blocking_diagnostic_kinds")
        geometry = score.get("geometry") or {}
        row["geometry_availability"] = (
            "not_applicable_pixel_only" if pixel else "independent_reference_measured" if geometry
            else "not_applicable_no_complete_3d_gold" if expected == "refuse_or_request_evidence"
            else "not_scored_original_diagnostic" if not candidate else "unavailable_no_current_export"
        )
        row.update({column: geometry.get(name) for column, name in GEOMETRY.items()})
        row["geometry_gate_checks_json"] = geometry.get("checks")
        worst = geometry.get("worst") or {}
        row.update({"worst_" + name: worst.get(name) for name in (
            "section_id", "x_m", "z_m", "actual_y_m", "reference_y_m", "error_mm", "error_px")})
        trace = score.get("selected_trace") or {}
        row.update({column: trace.get(name) for column, name in TRACE.items()})
        row.update({column: score.get(name) if pixel else None for column, name in PIXEL.items()})
        pixel_worst = score.get("worst") or {} if pixel else {}
        row.update({"pixel_worst_" + name: pixel_worst.get(name) for name in ("section_id", "z_m", "error_px")})
        resources = score.get("resources") or {}
        row.update({name: resources.get(name) for name in RESOURCES})
        if pixel:
            row["execution_wall_seconds"] = score.get("execution_wall_seconds")
            row["wall_scope"] = "source-only pixel prediction execution; no CAD"
        row.update({name: (score.get("counters") or {}).get(name) for name in COUNTERS})
        step_hashes = {item["path"]: item["sha256"] for item in score.get("exported_steps", [])}
        row.update({
            "current_step_sha256": step_hashes.get(score.get("current_step")),
            "measurement_sha256": score.get("measurement_sha256"),
            "score_json": relative, "score_sha256": sha,
            "case_metadata_score_json": meta_path, "case_metadata_score_sha256": meta_sha,
            "original_receipt_path": score["original_receipt"]["path"],
            "original_receipt_sha256": score["original_receipt"]["sha256"],
            "output_lock_path": (score.get("output_lock") or {}).get("path"),
            "output_lock_sha256": (score.get("output_lock") or {}).get("sha256"),
            "summary_sha256": SUMMARY_SHA256,
        })
        rows.append(row)
    checks = {}
    for arm, aggregate in summary["arms"].items():
        arm_rows = [r for r in rows if r["arm"] == arm]
        if arm == "simple_pixel_baseline":
            support_rows = [r for r in arm_rows if r["expected_original"] == "candidate"]
            actual = {"attempted": len(arm_rows),
                      "supported_required_rows": sum(r["pixel_required_rows"] for r in support_rows),
                      "supported_resolved_rows": sum(r["pixel_resolved_rows"] for r in support_rows)}
            if any(actual[k] != aggregate[k] for k in actual):
                raise ValueError("Pixel CSV does not reconcile to the retained summary")
        else:
            actual = {"attempted": len(arm_rows),
                      "terminal_records": sum(r["terminal_record_present"] for r in arm_rows),
                      "exported_candidates": sum(r["current_step_exported"] for r in arm_rows),
                      "full_supported_pass": sum(r["supported_full_pass"] is True for r in arm_rows),
                      "explicit_correct_refusals": sum(r["explicit_correct_refusal_or_request"] is True for r in arm_rows),
                      "safe_diagnostic_nonacceptance": sum(r["safe_diagnostic_nonacceptance"] is True for r in arm_rows)}
            if any(actual[k] != aggregate["all"][k] for k in actual):
                raise ValueError(f"CSV does not reconcile to the retained summary: {arm}")
        checks[arm] = actual
    return rows, sources, checks


def intake_rows(root: Path):
    archive = root / "intake_preflight_v1.tar.gz"
    if file_hash(archive) != INTAKE_SHA256:
        raise ValueError("Initial intake archive digest mismatch")
    sources = {}
    with tarfile.open(archive, "r:gz") as saved:
        def member(path, expected=None):
            stream = saved.extractfile(path)
            if stream is None:
                raise ValueError(f"Not an archived file: {path}")
            data = stream.read()
            sha = digest(data)
            if expected is not None and sha != expected:
                raise ValueError(f"Archived evidence digest mismatch: {path}")
            sources[path] = sha
            return json.loads(data), sha

        lock, lock_sha = member("legacy_runs_001/legacy_output_lock.json")
        commitments, _ = member("legacy_runs_001/attempt_commitments.json", lock["attempt_commitments_sha256"])
        rows = []
        for item in sorted(commitments["attempts"], key=lambda r: (r["arm"], r["case_id"])):
            prefix = f"legacy_runs_001/{item['arm']}/{item['case_id']}/primary_001/"
            receipt, receipt_sha = member(prefix + "attempt_record.json", item["receipt_sha256"])
            if any(receipt[key] != item[key] for key in ("arm", "case_id", "attempt_id")):
                raise ValueError("Archived intake receipt identity mismatch")
            inventory = {r["path"].split("/legacy_runs_001/", 1)[1]: r["sha256"]
                         for r in receipt["output_files"] if "/legacy_runs_001/" in r["path"]}

            def output(suffix):
                name = prefix + suffix
                return member(name, inventory[name.removeprefix("legacy_runs_001/")])

            suffix = "task/result.json" if receipt["arm"] == "frozen_02_deterministic" else "task/state.json"
            status, status_sha = output(suffix)
            status = status.get("state", status)
            domain_sha = None
            if suffix.endswith("result.json"):
                diagnostics = status.get("gaps", [])
            else:
                domain, domain_sha = output("task/domain/state.json")
                diagnostics = domain.get("input_errors", [])
            resource, resource_sha = output("resource_usage.json")
            usage = resource["usage"]
            if receipt["cohort"] not in {"procedural", "negative", "authentic_partial"}:
                raise ValueError("Unexpected retained intake cohort")
            procedural = receipt["cohort"] in {"procedural", "negative"}
            row = {
                "inventory": "initial_intake_v1_separate", "arm": receipt["arm"],
                "case_id": receipt["case_id"], "attempt_id": receipt["attempt_id"],
                "recorded_cohort": receipt["cohort"],
                "intake_group": "procedural_fractional_ROI" if procedural else "unchanged_incomplete_authentic_partial",
                "included_in_92_primary": False, "geometry_scored": False,
                "inventory_attempts_denominator": lock["attempts"],
                "arm_attempts_denominator": 15,
                "intake_group_attempts_denominator": 24 if procedural else 6,
                "arm_intake_group_attempts_denominator": 12 if procedural else 3,
                "launched": receipt["launched"], "process_finalized": receipt["finalized"],
                "workflow_status": status["status"], "exit_code": receipt["exit_code"],
                "termination_reason": status.get("termination_reason"),
                "last_observation_status": (status.get("last_observation") or {}).get("status"),
                "last_observation_error_code": (status.get("last_observation") or {}).get("error_code"),
                "diagnostic_kinds_json": sorted({r["kind"] for r in diagnostics if "kind" in r}),
                "diagnostics_json": diagnostics,
                "execution_wall_seconds": receipt["execution_wall_seconds"],
                "native_queue_wait_seconds": receipt["queue_wait_seconds"],
                "cli_user_cpu_seconds": usage["ru_utime"],
                "cli_system_cpu_seconds": usage["ru_stime"],
                "cli_descendant_max_rss_kib": usage["ru_maxrss"],
                "operator_actions": receipt["operator_actions"], "provider_calls": receipt["provider_calls"],
                "supervisory_timeout": receipt["supervisory_timeout"],
                "supervisory_watchdog_seconds": receipt["supervisory_watchdog_seconds"],
                "requested_utc": receipt["requested_utc"], "started_utc": receipt["started_utc"],
                "process_finished_utc": receipt["process_finished_utc"], "finalized_utc": receipt["finalized_utc"],
                "input_sha256": receipt["input_sha256"], "source_image_sha256": receipt["source_image_sha256"],
                "input_tree_sha256": lock["input_tree_sha256"], "freeze_sha256": receipt["freeze_sha256"],
                "receipt_archive_member": prefix + "attempt_record.json", "receipt_sha256": receipt_sha,
                "status_archive_member": prefix + suffix, "status_sha256": status_sha,
                "domain_state_sha256": domain_sha, "resource_usage_sha256": resource_sha,
                "output_tree_sha256": receipt["output_tree_sha256"],
                "output_lock_sha256": lock_sha, "archive_sha256": INTAKE_SHA256,
            }
            rows.append(row)
    groups = dict(collections.Counter(r["intake_group"] for r in rows))
    if len(rows) != 30 or sorted(groups.values()) != [6, 24]:
        raise ValueError("Initial intake inventory changed")
    return rows, [{"archive_member": k, "sha256": v} for k, v in sorted(sources.items())], groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=Path(__file__).resolve().parents[1] / "artifacts/v04/evaluation")
    args = parser.parse_args()
    root = args.evidence.resolve()
    summary, _ = load(root / "scoring/summary.json", SUMMARY_SHA256)
    primary, score_sources, reconciliation = primary_rows(root, summary)
    intake, intake_sources, groups = intake_rows(root)
    outputs = {}
    for name, rows in (("primary_attempts.csv", primary), ("initial_intake_attempts.csv", intake)):
        data = csv_bytes(rows)
        (root / name).write_bytes(data)
        outputs[name] = {"sha256": digest(data), "bytes": len(data), "data_rows": len(rows), "columns": list(rows[0])}
    schema = """# Evaluation CSV definitions

`primary_attempts.csv` contains one row for each of the 92 primary arm/case executions. It is derived only from the unchanged `scoring/summary.json` and its 92 bound per-case score JSON files. `initial_intake_attempts.csv` separately contains all 30 original intake executions, copied from locked receipt, status and resource JSON in `intake_preflight_v1.tar.gz`. It assigns no new geometry or accuracy score. The failed launcher preflight launched zero cases and is not a CSV case row.

## Values and applicability

Files use UTF-8, comma separators, one header row, LF record separators and standard CSV quoting. Booleans are `true`/`false`. Decimal values preserve the source numeric value without display rounding. Empty cells mean unavailable, unrecorded or inapplicable; no empty value is filled with zero. JSON list/object columns retain structured data within a quoted CSV field. These are static exports; the bound JSON remains the authoritative complete record.

Column suffixes specify units: `_m3` is cubic metres; `_m` metres; `_mm` millimetres; `_px` source pixels; `_fraction` a dimensionless ratio, not a percentage; `_seconds` seconds; `_kib` KiB; `_bytes` bytes; `_usd` US dollars. `source_pixels_per_metre` is pixels/metre. Counts are integers. Timestamps ending `_utc` retain the recorded UTC offset and microseconds in the CSV. Import those columns as text when exact timestamps are needed: automatic spreadsheet date parsing can discard sub-millisecond precision. Hashes are SHA-256 hexadecimal strings.

`cohort` follows the retained expected label: candidate → supported_procedural; refuse → procedural_diagnostic; refuse_or_request_evidence → authentic_partial_no_3d_gold. Each row includes a retained Rust score JSON as the case metadata source, because pixel scores do not repeat family/convention/negative metadata. This identity join uses only existing score JSON, and all overlapping metadata fields are checked for equality. Original negative labels and the pre-outcome scope-ambiguity sensitivity are unchanged.

All-attempt, cohort, finalized-process, terminal-record, current-export, supported-attempt, supported-export, original-negative and sensitivity-negative denominators are explicit count columns. They are repeated context, not additive observations: do not sum denominator columns down the CSV. Four paired procedural families generate eight supported drawings. `arm_supported_distinct_families` counts sampled families; `arm_complete_paired_families_denominator` counts families with both conventions attempted. The assistant samples one convention of one family and therefore has zero complete paired families. Neither execution counts nor repeated conventions represent independent vessels.

`supported_full_pass` is populated only for supported CAD-capable attempts. A missing export retains false in that success field and has empty numeric geometry errors. Refusal fields apply only to diagnostic/authentic CAD attempts. A no-progress stop can be safe diagnostic nonacceptance without being an explicit correct refusal. Terminal state is retained separately from process exit and CAD availability. The derived pixel `evaluation_status` describes a finalized source-only prediction; its absent controller workflow/terminal fields stay empty.

`geometry_availability` explains blank 3D metrics. Pixel rows use only `pixel_*` metrics, and their CAD/refusal success fields stay empty. Pixel RMS/max are over resolved source rows, so coverage must accompany them. Authentic partial images have no complete 3D gold and no volume/section score. The scope-ambiguous diagnostic exports retain their separately measured selected-trace consistency, but receive no independent supported-geometry score. Trace agreement is not source contour identity.

`geometry_gate_checks_json` copies the retained checks; no gate is recomputed. Volume error is a fraction (multiply by 100 only for a percent display). Geometry, trace, workflow, diagnostics and success columns are copied, never reclassified. Worst-case station/elevation and physical/source-pixel errors are retained where measured. Selected-trace distances remain separate from source-reference errors.

Execution and queue wall values have their retained scope. Raw product defaults, concurrency and render counts differ, so this CSV is not a feature-equivalent latency comparison. RSS is the maximum individual waited-for descendant, not a summed process-tree peak. Missing resource counters remain empty. Recorded zero usage cost is not an invoice or subscription-cost claim. Assistant conversation tokens/cost are unmetered; task counters do not measure the assistant conversation.

## Initial intake ledger

The 30 rows comprise 24 procedural executions affected by fractional ROI bounds and six unchanged, intentionally incomplete authentic-partial executions. The schema-only admission check passed but missed the stricter engine integer-ROI intake requirement. The authentic cases' missing-input blocks/no-progress are not ROI format failures. `intake_group` is a cohort clarification, not a new accuracy label. The original status, last-observation error code and structured diagnostic kinds are retained separately. All rows have `included_in_92_primary=false` and `geometry_scored=false`.

The original summary's historical field `original_malformed_intake_attempts_separate: 30` remains byte-for-byte unchanged; the 24+6 clarification governs its interpretation. Archive members are read directly without extracting or modifying the archive. Receipt digests are checked against the committed attempt list, that list against the output lock, and status/domain/resource digests against each finalized receipt's inventory.

## Provenance and reproduction

`csv_derivation.json` binds the original summary, all 92 per-case score JSONs, the initial archive, every initial JSON member used, the exporter and the two CSV outputs. It records round-trip CSV readback and reconciliation to retained summary counts. Run `python benchmarks/v04_export_evaluation_csv.py` from the repository; no application, CAD worker, reference generator, network or provider is invoked. All input/ref/score/output seals remain unchanged.
"""
    (root / "csv_schema.md").write_text(schema, encoding="utf-8")
    manifest = {
        "schema_version": "marinaframe-v04-additive-csv-1",
        "purpose": "Exact static export of retained values; no inference, measurement, rescoring or gate changes",
        "summary": {"path": "scoring/summary.json", "sha256": SUMMARY_SHA256},
        "score_rows": score_sources,
        "initial_intake_archive": {"path": "intake_preflight_v1.tar.gz", "sha256": INTAKE_SHA256},
        "initial_intake_json_members": intake_sources,
        "initial_intake_groups": groups,
        "historical_summary_field_clarification": "The retained count of 30 is 24 fractional-ROI procedural executions plus six unchanged intentionally incomplete authentic-partial executions.",
        "exporter": {"path": "benchmarks/v04_export_evaluation_csv.py", "sha256": file_hash(Path(__file__))},
        "schema": {"path": "csv_schema.md", "sha256": file_hash(root / "csv_schema.md")},
        "outputs": outputs,
        "verification": {"csv_readback_exact": True, "unique_arm_case_identities": True,
                         "primary_rows": len(primary), "initial_intake_rows": len(intake),
                         "summary_reconciliation": reconciliation,
                         "numeric_rounding_or_zero_imputation": False,
                         "source_files_modified": False},
    }
    # Check the numeric score sources again after export before recording success.
    load(root / "scoring/summary.json", SUMMARY_SHA256)
    for source in score_sources:
        load(root / source["path"], source["sha256"])
    (root / "csv_derivation.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"outputs": {name: {k: v for k, v in item.items() if k != "columns"}
                                 for name, item in outputs.items()},
                      "derivation_sha256": file_hash(root / "csv_derivation.json")}, indent=2))


if __name__ == "__main__":
    main()
