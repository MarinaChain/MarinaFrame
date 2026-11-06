"""Build the human-readable release report from retained machine evidence."""
from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pct(value):
    return "—" if value is None else f"{value * 100:.3f}%"


def mean(values):
    return statistics.mean(values) if values else None


def inline(text):
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"\[([^\]]+)\]\((https?://[^ )]+)\)", r'<a href="\2">\1</a>', text)


def render_markdown(markdown):
    """Render the small, known Markdown subset used by this generated report."""
    lines = markdown.splitlines()
    output = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("```"):
            code = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                code.append(lines[index]); index += 1
            output.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
            index += 1
            continue
        if line.startswith("|"):
            rows = []
            while index < len(lines) and lines[index].startswith("|"):
                values = [v.strip() for v in lines[index].strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", v) for v in values):
                    rows.append(values)
                index += 1
            table = '<div class="table-wrap"><table><thead><tr>'
            table += "".join("<th>" + inline(v) + "</th>" for v in rows[0])
            table += "</tr></thead><tbody>"
            for row in rows[1:]:
                table += "<tr>" + "".join("<td>" + inline(v) + "</td>" for v in row) + "</tr>"
            output.append(table + "</tbody></table></div>")
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            output.append(f"<h{level}>" + inline(line[level:].strip()) + f"</h{level}>")
            index += 1
            continue
        if line.startswith("- "):
            items = []
            while index < len(lines) and lines[index].startswith("- "):
                items.append("<li>" + inline(lines[index][2:]) + "</li>"); index += 1
            output.append("<ul>" + "".join(items) + "</ul>")
            continue
        paragraph = [line]
        index += 1
        while index < len(lines) and lines[index].strip() and not lines[index].startswith(("#", "|", "- ", "```")):
            paragraph.append(lines[index]); index += 1
        output.append("<p>" + inline(" ".join(paragraph)) + "</p>")
    return "\n".join(output)


def main():
    final_path = ROOT / "data/generated/confirmation_v2_evaluation/report.json"
    initial_path = ROOT / "data/generated/holdout_evaluation/report.json"
    report = json.loads(final_path.read_text())
    initial = json.loads(initial_path.read_text())
    assert report["all_predeclared_numeric_gates_met"] is True
    records = report["records"]
    assert len(records) == report["attempted_cases"] == report["total_cases_in_frozen_suite"] == 47
    assert len({r["case_id"] for r in records}) == 47
    checkpoint = [json.loads(s) for s in final_path.with_name("cases.jsonl").read_text().splitlines()]
    assert records == checkpoint
    numeric = [r for r in records if r["category"] in {"clean", "degraded", "external"}]
    successful = [r for r in numeric if r["score"]["passed"]]
    tests = ET.parse(ROOT / "artifacts/validation/pytest.xml").getroot().find("testsuite")
    assert tests is not None
    assert int(tests.get("failures", 0)) == int(tests.get("errors", 0)) == 0
    test_count = int(tests.get("tests"))
    test_seconds = float(tests.get("time"))
    audit_tests_path = ROOT / "artifacts/validation/step-audit-pytest.xml"
    audit_test_count = 0
    if audit_tests_path.exists():
        audit_tests = ET.parse(audit_tests_path).getroot().find("testsuite")
        assert audit_tests is not None
        assert int(audit_tests.get("failures", 0)) == int(audit_tests.get("errors", 0)) == 0
        audit_test_count = int(audit_tests.get("tests"))
    groups = {}
    for category in ("clean", "degraded", "external"):
        attempted = [r for r in numeric if r["category"] == category]
        passed = [r for r in attempted if r["score"]["passed"]]
        groups[category] = {
            "attempted": len(attempted), "passed": len(passed),
            "mean_volume_error": mean([r["score"]["relative_volume_error"] for r in passed]),
            "max_volume_error": max([r["score"]["relative_volume_error"] for r in passed], default=None),
            "mean_extracted_rms_over_beam": mean([r["score"]["rms_section_error_over_beam"] for r in passed]),
            "max_extracted_rms_over_beam": max([r["score"]["rms_section_error_over_beam"] for r in passed], default=None),
            "paired_baseline_rms_over_beam": mean([r["baseline"]["accuracy"]["rms_section_error_over_beam"] for r in passed]),
            "paired_baseline_volume_error": mean([r["baseline"]["accuracy"]["relative_volume_error"] for r in passed]),
        }
    step_path = ROOT / "artifacts/validation/step_section_audit_v2.json"
    step = json.loads(step_path.read_text()) if step_path.exists() else None
    summary = {"all_original_gates_met": report["all_predeclared_numeric_gates_met"],
        "numeric_attempted": len(numeric), "numeric_passed": len(successful),
        "correct_information_blocks": sum(r["score"].get("correct_abstention", False) for r in records),
        "groups_success_filtered": groups, "full_suite_tests_passed": test_count,
        "additional_step_audit_tests_passed": audit_test_count,
        "test_wall_seconds": test_seconds, "evaluation_wall_seconds": report["total_wall_seconds"],
        "report_sha256": digest(final_path), "initial_report_sha256": digest(initial_path),
        "suite_manifest_sha256": report["suite_manifest_sha256"],
        "successful_model_mean_volume_error": mean([r["score"]["relative_volume_error"] for r in successful]),
        "successful_model_max_volume_error": max(r["score"]["relative_volume_error"] for r in successful),
        "successful_model_mean_extracted_rms_over_beam": mean([r["score"]["rms_section_error_over_beam"] for r in successful]),
        "successful_model_max_extracted_rms_over_beam": max(r["score"]["rms_section_error_over_beam"] for r in successful),
        "step_section_audit": step}
    evidence_path = ROOT / "artifacts/validation/release_summary.json"
    evidence_path.write_text(json.dumps(summary, indent=2) + "\n")

    rows = []
    for name, label in (("clean", "Clean drafting drawings"), ("degraded", "Moderately degraded drawings"), ("external", "External DTMB CAD-derived drawings")):
        g = groups[name]
        rows.append(f"| {label} | {g['passed']}/{g['attempted']} | {pct(g['mean_volume_error'])} | {pct(g['max_volume_error'])} | {pct(g['mean_extracted_rms_over_beam'])} | {pct(g['max_extracted_rms_over_beam'])} |")
    failures = []
    for r in numeric:
        if not r["score"]["passed"]:
            gap = r["gaps"][0]
            failures.append(f"- `{r['case_id']}`: {gap['message']} No CAD was published.")
    baseline_rows = []
    for name in ("clean", "degraded", "external"):
        g = groups[name]
        baseline_rows.append(f"| {name} | {g['passed']} | {pct(g['mean_extracted_rms_over_beam'])} | {pct(g['paired_baseline_rms_over_beam'])} | {pct(g['mean_volume_error'])} | {pct(g['paired_baseline_volume_error'])} |")
    case_rows = []
    for r in records:
        score = r["score"]
        is_numeric_success = score["passed"] and r["category"] in {"clean", "degraded", "external"}
        outcome = "CAD pass" if is_numeric_success else ("Correct information block" if score.get("correct_abstention") else "Reconstruction failed / blocked")
        case_rows.append(f"| `{r['case_id']}` | {outcome} | {pct(score.get('relative_volume_error'))} | {pct(score.get('rms_section_error_over_beam')) if is_numeric_success else '—'} |")
    step_text = "The additional actual-STEP boundary diagnostic is not included in this report version. The frozen section RMS measures extracted image curves; it is not a measurement of every point on the final CAD surface."
    if step:
        step_rows = []
        for item in step["cases"]:
            sections = item["sections"]
            compared = sum(s.get("compared_ordinates", 0) for s in sections)
            absent = sum(s.get("absent_ordinates", 0) for s in sections)
            ambiguous = sum(s.get("ambiguous_ordinates", 0) for s in sections)
            step_rows.append(f"| `{item['case_id']}` | {compared} | {absent} | {ambiguous} | {pct(item.get('rms_section_error_over_beam'))} |")
        step_text = """A supplemental diagnostic independently cuts the **actual exported STEP** at nine interior drawing stations per selected case, with 129 elevations per station. The four cases were selected before this audit: first clean/degraded multichine and clean/degraded external DTMB. It does not rerun inference or alter the frozen gates.

| Actual STEP case | Compared ordinates | Missing | Ambiguous | Actual STEP RMS / full beam |
|---|---:|---:|---:|---:|
""" + "\n".join(step_rows) + """

The original diagnostic had strict endpoint comparisons that missed a few ordinates at floating-point gaps between shared edge endpoints. Its unchanged inconclusive results and exact source are retained. The corrected comparator uses a recorded fixed endpoint tolerance and records tolerance-assisted intersections; its analytic fixtures are retained. This check establishes sampled CAD-boundary agreement at those stations, not accuracy between every station, at end caps, or over all ships.
"""
    text = f"""# Vessel Reconstruction Foundation — validation report

## Outcome and proven scope

**All original acceptance gates were met on the complete fresh confirmation evaluation.** The system produced {len(successful)} passing CAD reconstructions from {len(numeric)} numerical drawing cases, with {len(numeric)-len(successful)} explicit blocks. It also correctly blocked all four invalid-input cases and one unannotated historical sheet. These information-related blocks do not count as reconstructed vessels.

The proof concerns **calibrated, isolated hull-section drawings with disclosed operator assistance**. It covers pixels to measured curves, real CAD construction, STEP export/reload, evidence preservation, review status, and an offline workbench. It does not establish arbitrary full-ship plan interpretation, fabrication readiness or equivalence to Forge Shipyards' complete product.

No project-specific neural model was trained. Curve extraction is deterministic image analysis; CAD uses CadQuery/OpenCascade. The experimental table reader uses existing pretrained Tesseract LSTM weights. No LLM service, Blender automation or GPU is required for the proven curve workflow.

## Fresh confirmation results

Errors below are calculated **only over completed, passing models**, with the pass/attempt denominator shown. Every failed case remains in the case log. Clean and degraded views share 20 hulls, so they are 40 images of 20 geometries, not 40 independent ships. The two external views share one DTMB reference hull crop.

| Test group | Passing / attempted | Mean envelope-volume error | Worst envelope-volume error | Mean extracted-curve RMS / beam | Worst extracted-curve RMS / beam |
|---|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

Across all {len(successful)} completed numeric models, mean volume error was **{pct(summary['successful_model_mean_volume_error'])}**, worst **{pct(summary['successful_model_max_volume_error'])}**. Mean extracted-curve RMS/full beam was **{pct(summary['successful_model_mean_extracted_rms_over_beam'])}**, worst **{pct(summary['successful_model_max_extracted_rms_over_beam'])}**. These figures are conditional on successful reconstruction; the three blocked inputs are not discarded from the reported pass rate.

Each passing case recovered every required section, produced one valid positive-volume CAD solid and completed STEP export/reload. Exported STEP volume and length/beam/depth had to agree within 1e-6 relative tolerance. JSON meshes and reporting use metres; STEP/STL use millimetres.

The full 47-case evaluation took **{report['total_wall_seconds']:.2f} seconds** with two inference workers. Procedural clean-case median wall time was **{report['groups']['clean']['wall_seconds']['median']:.2f} seconds** including process startup and exports. These are measurements on this execution environment, not throughput promises for other machines.

## Gates fixed before scoring

- Clean: at least 90% of cases must have envelope-volume error ≤ 3% and extracted-section RMS/full beam ≤ 1%, plus complete valid CAD.
- Moderate degradation: at least 80% must have volume error ≤ 5% and RMS/full beam ≤ 2%, plus complete valid CAD.
- External geometry: at least one passing CAD case under 5% volume and 2% RMS/full-beam limits.
- Missing-information cases: 100% must block without published geometry.

The original gates were retained after implementation defects were found. Confirmation uses 20 fresh procedural seeds frozen before inference, with no overlap with the original 20. The two procedural families and rendering distributions remain the same. DTMB geometry is reused as an external regression repeat and is not claimed as a new unseen vessel in confirmation.

## Remaining failed confirmation cases

{chr(10).join(failures)}

All three are degraded inputs. Conservative curve-support checks rejected an interrupted trace at one required station. The system did not fill those segments by reading evaluation labels or guessing a hull family. These cases constrain the reliability claim to 17/20 moderately degraded inputs in this test.

## The original evaluation failed, and is retained

The first frozen implementation passed **0/20 clean**, **10/20 degraded** and **2/2 external** numeric cases: **12/42 numerical reconstructions**. Four degraded cases blocked during CAD and six timed out; all clean cases blocked. All five information-related blocks were correct. The original clean/degraded gates failed.

Two general defects were repaired using dedicated fixtures. First, inconsistent threshold quantization and light-grid selection caused false competing-contour detections. Second, whole closed-wire lofting guessed correspondence between profiles with different bottom-edge counts. The final method separates ink contrast tiers and constructs explicitly corresponding ruled CAD panels. It adds no target geometry or minimum-width epsilon. Original code, failed runs and the diagnostic replay remain in `artifacts/algorithm_history/` and `data/generated/holdout_evaluation/`.

The original evaluation's incomplete append checkpoint was recovered from its complete in-memory final report without rerunning or rescoring cases. The original checkpoint and recovery receipt are preserved. Confirmation publishes atomic, read-back-verified checkpoints; its 47 unique records agree exactly across report and checkpoint.

## Comparison with a simple pixel baseline

The baseline selects the rightmost pixel darker than 120 at each sampled row, using exactly the same operator calibration. It estimates sections and volume; it does not produce CAD or establish safe abstention. For a paired comparison, the table uses the same successful main-method cases for both methods.

| Group | Paired cases | Main extracted RMS / beam | Baseline RMS / beam | Main CAD volume error | Baseline estimated-volume error |
|---|---:|---:|---:|---:|---:|
{chr(10).join(baseline_rows)}

The baseline is competitive on clean images and has lower mean volume error in these paired groups. The continuity-based parser has substantially smaller local curve errors under noise. Local errors can cancel in a volume estimate; neither a small volume error nor a plausible-looking mesh proves that every hull region is correct.

## Actual exported CAD boundary diagnostic

{step_text}

## Original historical drawings: a harder, unsuccessful task

The original Balclutha frame 108 scan was actually tested. The v1 curve heuristic accepted 129 measured/interpolated samples with 100% row coverage and quality score about 0.897. AI visual review found switches onto internal deck brackets and rejected the trace. No CAD was exported. There was no human naval-architect signoff. Continuous ink and a high heuristic quality score did not establish one physical surface's identity.

Two real table-reading attempts used 114 unchanged cells from the original sheet 7 drawing, with source-supported nonuniform station positions from sheet 3. The first pretrained OCR model accepted 43 cells and blocked 71. The separately pinned larger model accepted 57 and blocked 57 under the same confidence/agreement rules. Neither completed the required stations, so both full pipelines blocked with zero CAD exports. Separate AI visual checks found no disagreement in the accepted literals; that is not validation of mapping, survey accuracy or geometry.

The table describes an inner hull surface, and the attempted 4–24 ft height range would be a cropped envelope with assumed closures. No half-breadth answers were typed into the source specification, no confidence threshold was relaxed and no uncertain numeral was silently repaired. The unannotated historical-sheet block in the numerical suite is only a missing-input check, not a successful archival reconstruction.

## Test and application verification

The full core/application/harness suite passed **{test_count} tests** in **{test_seconds:.2f} seconds**, recorded in `artifacts/validation/pytest.xml` and `pytest.txt`. The subsequently added STEP-comparator suite passed **{audit_test_count} additional tests**, recorded separately in `step-audit-pytest.xml`: **{test_count + audit_test_count} passing automated tests across the two suites**. They cover independent analytic volumes, dimensional scaling, valid CAD and STEP round trips, independently loaded watertight STL, missing-frame and dimensional-conflict blocks, source changes versus unrelated reference-label changes, extreme/nonfinite numeric inputs, OCR conversion and uncertainty, dataset/scorer integrity, review records, uploaded-source preservation, server confinement, and distinction between floating-point endpoint gaps and actual missing CAD boundaries.

Browser checks exercised actual 21-section upload/reconstruction and interactive calibration to a new three-section CAD result. Packaged assets were tested from a separately installed wheel outside the source repository. Offline snapshots, section/source overlays, a software-rendering fallback and 390 px layout were exercised with no JavaScript errors. Final snapshot-specific evidence is retained under `artifacts/validation/workbench/`; browser screenshots are not part of the deliverable.

The supplied portable DTMB workbench contains the actual final 41-section model, original drawing, evidence and CAD downloads. It can be inspected offline; new reconstruction requires the local server. The server is a localhost development application, not a deployed multi-user service.

## Data provenance and assistance

- External CAD: [mathLab WaveBEMapp DTMB5415](https://github.com/mathLab/WaveBEMapp-DTMB-5415), pinned commit `afad0f04a2ce5ee03f37dcefbe697a5281bc0168`, retained MIT notice. Original x=[-2.5,2.9]m is cropped to one connected half-section representation, mirrored and capped. Newly rendered drawings are used for inference; the source IGES is never an inference input.
- Real archival scans: [Library of Congress Balclutha HAER survey](https://www.loc.gov/resource/hhh.ca1493.sheet/), sheets 3, 7 and 48, with documented official NPS public-domain notices and exact original-file hashes.
- Training/reference pairs: generated images and separate private labels. Procedural reference volume uses 801 stations × 1,025 elevations. External reference uses 241 dense stations. These numerical targets are decoded after inference completes.
- Operator assistance: station identification and x position, single-contour panel/cell regions, scale and datum for curve inputs, elevation ranges, symmetry and closure. These are supplied facts, not automatically recovered capabilities.

The source/spec-only subprocess boundary is auditable data separation, not an operating-system sandbox. File hashes detect changes relative to retained manifests; they are not externally signed certification. New runs preserve exact inference Python files, environment versions and original source bytes.

## What has not been established

The work does not prove automatic interpretation of arbitrary overlapping plans, dimension conventions, revisions, old handwriting, stains, rotation, perspective distortion or all faint competing strokes. Synthetic degradation is the documented blur/noise/speckle/JPEG/gradient process. Forty procedural images do not represent the distribution of real shipyards.

The model is a hull envelope. It does not infer plating thickness, steel volume, material, structural frames, decks, piping, machinery or current as-built condition. Envelope volume is not automatically displacement. Top, lower and terminal closures and between-station interpolation are modeling assumptions. Successful outputs remain review-required and no automated or local review entry produces engineering approval.

The deliverable is a usable, measured foundation for a broader system. The historical failures identify the next technical bottleneck: semantic line identity and reliable extraction of measurement evidence.

## Reproduce and inspect

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install -e '.[test,documents]'
python -m pytest -q
python -m vessel_reconstruction serve --artifacts artifacts --port 8765
python -m benchmarks.evaluate data/generated/confirmation_v2 --out artifacts/new-evaluation --jobs 2 --timeout 90
```

Full commands, input schema, source rights and modeling choices are in `README.md`, `CONTRACT.md`, `DATA_SOURCES.md` and `ARCHITECTURE.md`. Each run requires a fresh output directory so prior evidence is retained. Both initial and final suites, all acquired source data, licenses, trained OCR weights, scripts, tests, frozen code, failure records and CAD exports are in the source bundle.

Confirmation input manifest SHA-256: `{report['suite_manifest_sha256']}`.

Confirmation numerical report SHA-256: `{digest(final_path)}`.

Original numerical report SHA-256: `{digest(initial_path)}`.

## Complete confirmation case inventory

RMS is displayed here only for complete passing reconstructions. Raw reports retain partial extraction diagnostics for failed cases. Information blocks have no numeric reconstruction score.

| Case | Outcome | Envelope-volume error | Extracted-curve RMS / beam |
|---|---|---:|---:|
{chr(10).join(case_rows)}
"""
    (ROOT / "VALIDATION.md").write_text(text)
    css = """body{margin:0;background:#eff3f6;color:#172b3a;font:16px/1.6 system-ui,sans-serif}main{max-width:1120px;margin:36px auto;padding:44px 56px;background:#fff;border:1px solid #dbe3e9;border-radius:16px}h1{font-size:32px;line-height:1.2;margin:0 0 32px;color:#102b40}h2{font-size:24px;line-height:1.3;margin:42px 0 16px;border-top:1px solid #dde5ec;padding-top:28px}p,li{max-width:90ch}a{color:#006b86}code{font:0.88em ui-monospace,monospace;overflow-wrap:anywhere}pre{background:#142c40;color:#ecf6fa;padding:22px;overflow:auto;border-radius:8px}pre code{white-space:pre;overflow-wrap:normal}.table-wrap{overflow-x:auto;margin:22px 0}table{border-collapse:collapse;font-size:14px;width:100%}th,td{text-align:left;padding:12px 13px;border-bottom:1px solid #dce4eb;vertical-align:top}th{background:#14354c;color:white}tr:nth-child(even){background:#f5f8fa}td:first-child{min-width:180px}td code{font-size:12px;overflow-wrap:normal}strong{font-weight:680}@media(max-width:650px){main{margin:0;padding:24px 18px;border:0;border-radius:0}h1{font-size:26px}h2{font-size:21px}}@media print{body{background:white}main{border:0;margin:0;padding:0}h2{break-after:avoid}tr{break-inside:avoid}}"""
    document = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Vessel Reconstruction — Validation</title><style>' + css + '</style></head><body><main>' + render_markdown(text) + '</main></body></html>'
    (ROOT / "artifacts/validation-report.html").write_text(document)
    print(json.dumps({"summary": str(evidence_path), "numeric_passed": len(successful), "numeric_attempted": len(numeric), "tests": test_count, "step_audit_included": bool(step)}, indent=2))


if __name__ == "__main__":
    main()
