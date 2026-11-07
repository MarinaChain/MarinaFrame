"""Render the completed independent evaluation's public tables and figures."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts/v04/evaluation"
ARMS = ["frozen_02_deterministic", "frozen_03_deterministic", "new_python_deterministic",
        "new_rust_deterministic", "live_deepseek"]
LABELS = dict(zip(ARMS, ["Published 0.2", "Exact published 0.3", "0.4 Python deterministic",
                         "0.4 Rust deterministic", "0.4 live DeepSeek"]))
ORDER = ["q_87c132d9", "q_04e5b3a1", "q_6fa9d080", "q_912adc37",
         "q_3bd4178e", "q_7c1052f4", "q_ef943ab2", "q_15a6d9c0"]
NAMES = dict(zip(ORDER, ["A clean", "A grid", "B clean", "B grid", "C clean", "C grid", "D clean", "D grid"]))
read = lambda p: json.loads(Path(p).read_text())


def format_number(value, decimals=3):
    return "—" if value is None else f"{value:.{decimals}f}"


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"]*len(headers)) + " |"]
                     + ["| " + " | ".join(str(v) for v in row) + " |" for row in rows])


def plot(scores, destination):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    fig, axes = plt.subplots(3, 1, figsize=(11.4, 9.1), sharex=True)
    properties = [("volume_relative_error", 100., 3., "Absolute volume error (%)"),
                  ("section_rms_px_resolved_only", 1., 2., "Section RMS error (source pixels)"),
                  ("section_max_px_resolved_only", 1., 4., "Worst local error (source pixels)")]
    colors = ["#737373", "#2675ac", "#4d9561", "#a55c1b", "#7553a6"]
    markers = ["s", "o", "^", "D", "x"]
    short = ["0.2 (4 exports)", "0.3 (8)", "0.4 Python (8)", "0.4 Rust (8)", "Live DeepSeek (8)"]
    for ax, (field, scale, gate, label) in zip(axes, properties):
        for j, arm in enumerate(ARMS):
            xs, ys = [], []
            for i, cid in enumerate(ORDER):
                g = scores[(arm, cid)]["geometry"]
                if g:
                    xs.append(i+(j-2)*.115); ys.append(g[field]*scale)
            ax.scatter(xs, ys, label=short[j], color=colors[j], marker=markers[j], s=39, alpha=.94)
        ax.axhline(gate, color="#a93d39", linestyle="--", linewidth=1.15)
        ax.text(7.35, gate+.025*gate, f"Fixed gate: {gate:g}", ha="right", va="bottom", color="#8c2f2d", fontsize=9)
        ax.set_ylim(0, gate*1.17); ax.set_xlim(-.5, 7.5); ax.set_ylabel(label)
        ax.grid(axis="y", alpha=.18); ax.spines[["top", "right"]].set_visible(False)
        for x in [1.5, 3.5, 5.5]: ax.axvline(x, color="#dddddd", linewidth=.7)
    axes[-1].set_xticks(range(8), [NAMES[c] for c in ORDER]); axes[-1].set_xlabel("Four procedural families, each drawn in two conventions")
    fig.suptitle("Independent errors of the actual exported STEP envelopes", x=.09, ha="left", fontsize=15, fontweight="bold")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=5, bbox_to_anchor=(.51, .055), frameon=False, fontsize=9)
    fig.text(.09, .025, "Missing exports remain failures in the attempted-case denominator; they have no numeric error point.\nCalibration is supplied. These drawing-resolution gates do not grant engineering approval.", fontsize=9, color="#444444")
    fig.subplots_adjust(left=.13, right=.97, top=.93, bottom=.16, hspace=.24)
    fig.savefig(destination, dpi=170); plt.close(fig)


def run(scoring):
    summary = read(scoring / "summary.json")
    scores = {(r["arm"], r["case_id"]): read(scoring / r["arm"] / r["case_id"] / "score.json")
              for r in summary["all_per_case_scores"]}
    a = summary["arms"]
    rust = a["new_rust_deterministic"]
    live = read(EVIDENCE / "v04_live_resources.json")
    assistant = read(EVIDENCE / "v04_assistant_resources.json")
    figure = EVIDENCE / "visual/supported_geometry_errors.png"
    plot(scores, figure)
    metric_rows = []
    for arm in ARMS:
        for cid in ORDER:
            r = scores[(arm, cid)]; g = r["geometry"]
            metric_rows.append([LABELS[arm], NAMES[cid], cid, "pass" if r["full_supported_pass"] else r["workflow_status"],
                format_number(g["volume_relative_error"]*100 if g else None, 6),
                format_number(g["section_rms_px_resolved_only"] if g else None, 6),
                format_number(g["section_max_px_resolved_only"] if g else None, 6),
                format_number(r["selected_trace"]["max_error_mm"] if r["selected_trace"] else None, 6),
                g["unresolved_ordinates"] if g else "no export"])
    full_table = "# All supported primary case measurements\n\nEvery row is an attempted input. Missing exports remain in the denominator. All numerical errors use the exported and independently reimported STEP. Source RMS is pooled over the 20,485 required ordinates per case. The trace check is a separate nearest-boundary consistency check.\n\n"
    full_table += table(["Arm", "Family / convention", "Case", "Outcome", "Volume error %", "RMS px", "Max px", "Trace max mm", "Unresolved ordinates"], metric_rows)
    full_table += "\n\n[Machine summary](scoring/summary.json) links every per-case JSON, which retains exact status, structured diagnostics, resource evidence, worst station/elevation, and acceptance components.\n"
    (EVIDENCE / "all_supported_case_measurements.md").write_text(full_table)
    result = ["## Completed results", ""]
    result.append("The frozen 0.4 Python, Rust and live DeepSeek arms each pass **8/8 supported drawing attempts, covering 4/4 paired design families**. Exact published 0.3 also passes 8/8; published 0.2 passes the four clean drawings and refuses the four grid variants. This cohort shows no supported-geometry success advantage for 0.4 over 0.3, or for the live policy over current deterministic operation. It does show different terminal handling of missing inputs and ambiguous source evidence. All candidates remain provisional and require human semantic review; engineering approval is false.")
    result.append("")
    aggregate_rows = []
    for arm in ARMS:
        s = a[arm]
        aggregate_rows.append([LABELS[arm], s["all"]["attempted"], s["all"]["terminal_records"],
            f'{s["supported"]["full_supported_pass"]}/8', f'{s["paired_families_all_correct"]}/4',
            f'{s["negative_original_four"]["explicit_correct_refusals"]}/4',
            f'{s["negative_original_four"]["safe_diagnostic_nonacceptance"]}/4',
            s["all"]["no_progress"]])
    result.append(table(["CAD-capable automated arm", "Attempted", "Terminal records", "Supported full pass", "Both conventions pass", "Explicit refusal: original negatives", "Safe diagnostic nonacceptance", "No-progress stops"], aggregate_rows))
    result += ["", "The original negative set contains one scope-ambiguous interior-loop case. Its original refusal label is retained in the table, with a separate sensitivity analysis below. A no-progress stop with a relevant gap is counted as safe diagnostic nonacceptance, but not as an explicit correct refusal. A terminal record, successful process exit, CAD export, trace agreement and independent correctness are distinct outcomes. [Full machine results](../artifacts/v04/evaluation/scoring/summary.json)", ""]
    result += ["The per-case exports contain [all 92 primary rows](../artifacts/v04/evaluation/primary_attempts.csv) and a [separate 30-row initial intake ledger](../artifacts/v04/evaluation/initial_intake_attempts.csv). They retain explicit units, cohort and completion denominators, recorded status, applicable accuracy/refusal fields, and empty values for unavailable or inapplicable measurements. These are exact derivations of the retained JSON, with no rescoring or gate change. [CSV definitions](../artifacts/v04/evaluation/csv_schema.md) and [source/output hash bindings](../artifacts/v04/evaluation/csv_derivation.json) document the mapping and verification.", ""]
    result.append("The primary inventory has **92 executions**: 75 automated CAD-capable attempts, 15 source-only pixel predictions, and two separately reported assistant-operated attempts. The 30 initial legacy intake-preflight attempts comprise **24 procedural executions affected by fractional ROI bounds and six unchanged, intentionally incomplete authentic-partial executions**. Those 30 attempts remain additional retained evidence, for **122 launched case executions in this evaluation**, not 122 vessels. The six authentic-partial attempts encountered their expected missing-input diagnostics, not the ROI format defect. The failed launcher preflight before them launched zero cases. All five CAD-capable automated arms produced terminal records for all 15 inputs; there were no inference watchdog interruptions, execution failures or resource-limit terminations in these primary runs. [Attempt inventory](../artifacts/v04/evaluation/scoring/attempt_index.json)")
    result += ["", "### Supported geometry, every declared station", ""]
    rs = []
    for cid in ORDER:
        r = scores[("new_rust_deterministic", cid)]; g = r["geometry"]
        rs.append([NAMES[cid], f'`{cid}`', g["source_pixels_per_metre"],
            format_number(g["volume_relative_error"]*100), format_number(g["section_rms_px_resolved_only"]),
            format_number(g["section_max_px_resolved_only"]), format_number(r["selected_trace"]["max_error_mm"]),
            g["unresolved_ordinates"]])
    result.append(table(["Family / convention", "Case", "px/m supplied", "Volume error %", "RMS px", "Max px", "Trace max mm", "Unresolved"], rs))
    worst = rust["metrics_supported_exports_only"]["worst_case"]
    values = rust["metrics_supported_exports_only"]
    result += ["", f"For the Rust arm, the worst local independent error is **{worst['error_px']:.6f} pixels ({worst['error_mm']:.3f} mm)** at `{worst['case_id']}`, section `{worst['section_id']}`, x={worst['x_m']:.3f} m and z={worst['z_m']:.6f} m. The largest volume error is {values['volume_relative_error']['max']*100:.6f}%, the largest per-case pooled RMS is {values['section_rms_px']['max']:.6f} pixels, and the largest selected-trace distance is {values['selected_trace_max_mm']['max']:.6f} mm. The independent gates remain 3%, 2 pixels RMS and 4 pixels maximum; selected-trace consistency remains separately limited to 1.1 mm.", ""]
    result.append("Every measured supported candidate is a valid single solid and resolves all five station cuts, including the exact terminal planes, at 4,097 elevations per station. Errors for absent exports are not assigned zero or included in success-only means. The four missing 0.2 grid exports remain reconstruction failures. [All 40 supported attempted-arm rows](../artifacts/v04/evaluation/all_supported_case_measurements.md)")
    result += ["", "![Independent STEP errors and fixed gates](../artifacts/v04/evaluation/visual/supported_geometry_errors.png)", ""]
    result.append("The current Python, Rust and live outputs have identical selected-trace coordinates and identical raw STEP DATA sections on all eight supported inputs. This establishes output identity for these runs, not equal operation counts or general performance equivalence. Full STEP file hashes differ because headers differ. The exact 0.3 outputs are separately measured, with no claim of byte identity. [Output identity checks](../artifacts/v04/evaluation/output_geometry_identity.json)")
    result += ["", "### Refusals, ambiguity and authentic partial sheets", ""]
    negatives = [("q_40bc6a8d", "Missing declared pixel scale"), ("q_68de09f5", "Two equal competing contours"),
                 ("q_b970f41e", "Interior loops: scope-ambiguous*"), ("q_a2538ce6", "Missing middle trace interval"),
                 ("r_73b91d2a", "Balclutha Frame 108: no 3D gold"), ("r_85ac0f61", "Monitor: no 3D gold"),
                 ("r_09d3ea47", "Wapama: no 3D gold")]
    diagnostic_rows = []
    for cid, label in negatives:
        vals = []
        for arm in ARMS:
            r = scores[(arm, cid)]
            vals.append("ready*" if r["ready_for_review"] else "no_progress + gap" if r["no_progress"] else r["workflow_status"])
        diagnostic_rows.append([label, f'`{cid}`', *vals])
    result.append(table(["Diagnostic", "Case", "0.2", "0.3", "0.4 Python", "0.4 Rust", "Live"], diagnostic_rows))
    result += ["", "Both Python harnesses stop with `no_progress` on the missing-scale specification and the three incomplete authentic specifications, while preserving relevant input-gap diagnostics. Rust and live terminate those four inputs explicitly as blocked. The three source-evidence diagnostics terminate with an explicit block or abstention under Rust/live. The terminal classifications come from recorded states and exact structured gap kinds, not exit-zero status or broad keyword matching.", ""]
    result.append("**Scope qualification committed before outcome review:** `q_b970f41e` was authored and sealed as unsupported topology, but the actual image places small closed loops inside an otherwise continuous exterior profile. For an exterior-envelope task, accepting the outer contour is not established to be wrong hull geometry. The evaluator documented that defect at 22:20:42 UTC, before new deterministic execution and before reference scoring, and retained the original reference/label unchanged. The original refusal expectation is violated by the 0.3 and current Python ready candidates. In the sensitivity set excluding that one case, 0.2, Rust and live explicitly refuse 3/3; both Python harnesses explicitly refuse 2/3 and safely stop with a relevant missing-scale gap on the remaining case. Their safe diagnostic nonacceptance is therefore 3/3. [Pre-outcome note](../artifacts/v04/evaluation/source_label_quality_note.json) · [Earlier hash commitment](../artifacts/v04/evaluation/source_audit_note_commitment.json)")
    result += ["", "The calibration negative removes `pixels_per_metre` from the deployment specification even though a scale bar remains visible in its image. It tests the required supplied-calibration contract, not automatic calibration or OCR. The authentic images also omit required units, station correspondence, scale and symmetry commitments. All arms avoid an unsupported ready hull on all three authentic inputs, but the Python harnesses reach no-progress rather than explicit refusal. These are principally intake-contract results: they do not demonstrate that a model visually inferred the historical sheets' limitations, and no 3D or volume correctness score is assigned.", ""]
    result += ["### Source-only pixel baseline", ""]
    pixel_rows = []
    for cid in ORDER:
        r = scores[("simple_pixel_baseline", cid)]
        pixel_rows.append([NAMES[cid], f'{r["resolved_rows"]}/{r["required_rows"]}', format_number(r["resolved_coverage"]*100, 3),
                           format_number(r["section_rms_px_resolved_only"]), format_number(r["section_max_px_resolved_only"])])
    result.append(table(["Family / convention", "Resolved / required rows", "Coverage %", "RMS on resolved rows, px", "Max on resolved rows, px"], pixel_rows))
    result += ["", "The fixed threshold/row-median method resolves **10,451/10,460 rows (99.914%)** across the eight supported images. Its small source errors show that these well-calibrated single-trace drawings are also tractable for a simple pixel method. The nine unresolved rows remain visible in coverage. It ran on all 15 inputs and has no CAD, closed-solid, volume, or 3D success claim. This baseline does not establish robustness to arbitrary archival drawing conventions. [Pixel per-case index in the machine summary](../artifacts/v04/evaluation/scoring/summary.json)", ""]
    result += ["### Live provider and source-blind assistant operation", ""]
    result.append("The live arm used the frozen optimized Rust application and the already authorized OpenCode Go `deepseek-v4.1-flash` provider. It completed **74/74 actual provider requests**, with no failed, unknown or not-sent requests and no provider retries or no-progress stops. Receipts record **752,723 prompt tokens and 5,590 completion tokens**. Usage reports record $0 observed cost on every request; nominal `list_cost` totals $0.11304483 and is recorded separately, while invoice or subscription cost is unknown. This is live evidence, not replay. No other provider or purchase was introduced. Zero runtime operator interventions excludes preparation of the supplied scale, centreline, baseline, ROIs, station positions, symmetry and closure metadata. [Independent live resource accounting](../artifacts/v04/evaluation/v04_live_resources.json)")
    result += ["", "Eight live tasks became ready for human review, three abstained, and four were blocked at input admission. Each supported live task used one geometry build, so this sealed cohort demonstrates no geometry-repair success or accuracy uplift over current deterministic operation. The live evidence includes 16 render operations and actual STEP-derived pixels on 27 completed provider requests. Three finish attempts were rejected for missing current-pixel review; those attempts remain counted. The 19 validation operations include 11 explicit reuses, so they are not 19 distinct new geometric audits. The live capture-and-transfer workflow intentionally adds a recorded pause after initialization, before provider inference. Concurrency was two provider tasks with one serialized native operation, and there was no aggregate request ceiling.", ""]
    assist_score = scores[("assistant_operated", "q_04e5b3a1")]
    result.append(f"The fresh, reference-blind assistant operated two new tasks selected by the precommitted rule. Its scanned supported case passes {'1/1' if assist_score['full_supported_pass'] else '0/1'} independently; its equal-contour case correctly abstains. The supported task required five explicit interventions—selection, two renders, validation and finish—and the ambiguous task required one finish/abstain intervention: **six interventions, two primary attempts, no extra attempts**. This is assistant operation, not a human or naval-architect comparison, and it is not pooled with autonomous results.")
    result += ["", "The assistant session lasted **554.012 seconds**, including 35.464 seconds of measured subprocess wait; the 518.547-second remainder is a collaboration-effort proxy containing image viewing, orchestration and context handling, not measured human labor or pure model inference time. Its tasks made zero external provider requests, but the assistant conversation's tokens and cost are unmetered here. Both tasks had valid pre-seal verification. Original sealed tasks remain read-only; the publication copy changes only empty `controller.lock` modes to permit verification, with every file byte preserved. [Assistant accounting](../artifacts/v04/evaluation/v04_assistant_resources.json) · [Transport record](../artifacts/v04/evaluation/assistant-transport.json)", ""]
    result += ["### Resources and interpretation", ""]
    rr = []
    for arm in ARMS:
        r = a[arm]["resources_all_attempts"]
        rss = r["cli_descendant_max_rss_kib"]["max"]
        rr.append([LABELS[arm], format_number(r["execution_wall_seconds"]["median"]),
            format_number(r["native_queue_wait_seconds"]["sum"]),
            format_number(r["cli_cpu_seconds"]["sum"]) if r["cli_cpu_seconds"]["n"] else "not collected by this wrapper",
            format_number(rss/1024 if rss is not None else None, 1),
            format_number(r["task_disk_bytes"]["sum"]/2**20, 1)])
    result.append(table(["Arm, all 15 attempts", "Median CLI/task wall, s", "Sum native queue, s", "CLI waited CPU sum, s", "Max descendant RSS, MiB", "Retained task bytes, MiB"], rr))
    result += ["", "These are observed product-default workloads under a shared serialized native queue. Python holds an outer whole-task lock, so its recorded CLI execution excludes that outer queue; Rust's task wall includes its separately logged per-operation waits. Python defaults render oblique, Rust defaults render body plus oblique, and live adds provider latency, the capture pause and repeated validation/review operations. These numbers are not an identical-operation speed comparison. RSS is a maximum individual waited-for process, not a summed concurrent process-tree peak. Native evaluator measurements are separate and are excluded from inference resources. [Controlled identical-operation study](CONTROL_PLANE_PARITY_V04.md)", ""]
    result.append("The live worker ledger records 86 completed operations, 426.517 seconds of admission waits and 251.325 seconds of supervised worker execution; overlapping task durations must not be interpreted as campaign elapsed time. Per-case logs retain all requests, rejections, operation receipts and resource fields. The current deterministic wrapper's 900-second watchdog was an external evaluation bound; it was not triggered and is not described as a product default.")
    result += ["", "### Independent instrument review and pixel review", ""]
    result.append("The original measurement code and its first box/frustum calibration are preserved. A separate reviewer, reading only generic excerpts, identified unsafe near-horizontal extrapolation, ambiguity hidden by an outermost-hit selector, and insufficient binding of measured files to finalized attempts. The revised instrument clamps tolerance-admitted queries to segment endpoints, explicitly measures the nonnegative outer envelope, records competing/interior-horizontal intersections, and binds case, specification, selected trace and STEP bytes to a finalized attempt. Exact terminal planes are never moved inward.")
    result += ["", "The expanded generic calibration covers a box, a ruled frustum and an internal tunnel over 45,067 required ordinates. It resolves all ordinates, exposes 6,147 competing interior ordinates and six interior horizontal overlaps in the tunnel, and rejects wrong case/spec/unlisted-STEP probes. The trace extension independently queries nearest distance to the actual OCCT section boundary at every retained source-centre sample; known distances of 0, 0.5 and 1.2 mm verify both the numerical result and the unchanged 1.1 mm threshold. A further generic review required exact finite full-span monotone grids, equal array lengths, unique station IDs and exact blocking-diagnostic kinds; all synthetic contract probes pass. No application or gate was changed by these instrument corrections. [Instrument results](../artifacts/v04/evaluation/instrument_calibration_v3.json) · [Preserved review and calibration bundle](../artifacts/v04/evaluation/instrument_evidence.tar.gz)", ""]
    result.append("Cut edges request 0.01 mm geometric sampling deflection. The generic ruled-shape calibration's maximum half-breadth error is below 10⁻⁶ mm, but requested deflection is not a separately certified y-ordinate error bound near arbitrary horizontal tangencies. The measured envelopes here have large margins to the 2/4-pixel source gates. Outer-envelope coverage does not prove that arbitrary multivalued or internal topology has been reconstructed correctly. The nearest-boundary trace metric is separately evaluated on actual OCCT geometry.")
    result += ["", "The evaluator viewed all 14 unique source images, verified the missing-calibration image's exact duplicate identity, and viewed one original actual-STEP render per design family before consulting numerical source errors. Original source/CAD hashes and observations are in the [visual review ledger](../artifacts/v04/evaluation/visual_review_ledger.json). A [post-score supplement](../artifacts/v04/evaluation/visual_review_postscore.json) records body/oblique views of the worst current supported case and the accepted 0.3 exterior envelope for the scope-ambiguous interior-loop diagnostic. These are assistant observations and do not replace qualified semantic or professional review.", "", "![Actual STEP body view, rounded-bilge grid case](../artifacts/v04/evaluation/visual/q_912adc37-rust-body.png)", "", "### Evidence and reproducibility", ""]
    result.append("The [public input/reference publication ledger](../artifacts/v04/evaluation/input_reference_publication.json) binds exact-byte copies of both input versions, the independently authored renderer, sealed mathematical references, the pre-outcome scope note and the assistant sampling rule. References were released only after all automated and assistant outputs locked. All original attempts remain intact. The terminal [0.2/0.3 archive](../artifacts/v04/evaluation/legacy_outputs_v2.tar.gz), [new Python archive](../artifacts/v04/evaluation/new_python_outputs_v2.tar.gz), [new Rust archive](../artifacts/v04/evaluation/new_rust_outputs_v2.tar.gz), [pixel archive](../artifacts/v04/evaluation/pixel_predictions_v2.tar.gz), and [original intake-preflight archive](../artifacts/v04/evaluation/intake_preflight_v1.tar.gz) each have an archive ledger and byte-for-byte verification. The live and assistant original output locks remain separately preserved.")
    result += ["", "Execution records deliberately retain their original absolute paths; archive manifests identify the corresponding member roots. Published inputs and all numerical reference/measurement arrays are sufficient to inspect the scoring independently. Re-execution needs the recorded native environment and appropriate path mapping; it is a new known-data run, not another untouched holdout. The full inference image/spec tree remains separate from the reference tree. The cohort is small, calibrated and procedurally authored; it provides no measured success rate for complete historical vessel reconstruction, automatic scale/station inference, unobserved bow/stern completion or engineering approval.", ""]
    result += ["### Requirements not measured by this cohort", "",
        "- **Complete authentic-vessel accuracy:** the three public sheets have no complete independent 3D gold. Their blocked intake does not validate full interpretation of those drawings.",
        "- **Automatic drawing setup:** supported-case ROIs, scale, centreline, baseline, station positions, symmetry and closure convention are supplied. Rotation, perspective distortion, severe degradation and multi-sheet station matching are not tested.",
        "- **Disconnected exterior topology:** the originally labelled topology diagnostic contains interior loops and does not establish a valid negative for disconnected outer hulls. That capability remains unmeasured here.",
        "- **Geometry repair or assistance advantage:** supported live cases use one build, and current automatic arms produce identical geometry. The two-case assistant sample is neither a human comparison nor a population estimate.",
        "- **Naval or structural validity:** volume means the declared closed envelope, not automatically displacement or steel volume. The tests do not establish unseen bow/stern form, hydrostatics, structural adequacy, professional semantic approval or safety certification.", ""]
    document = ROOT / "docs/INDEPENDENT_EVALUATION_V04.md"
    old = document.read_text()
    start = old.index("## Predeclared protocol")
    end = old.find("\n## Status", start)
    if end < 0:
        end = old.find("\n## Final execution", start)
    protocol = old[start:end if end >= 0 else len(old)]
    protocol = protocol.replace("## Predeclared protocol — results pending", "## Predeclared protocol and execution record")
    protocol = protocol.replace("unsupported separate topology and missing source intervals", "the originally labelled unsupported-topology diagnostic and missing source intervals; see the pre-outcome scope qualification above")
    final = "# Independent evaluation of MarinaFrame 0.4\n\n" + "\n".join(result) + "\n" + protocol
    final += "## Final execution and scoring status\n\nAll selected inference arms completed and locked before references were used for scoring. The final assistant lock is dated 2026-11-06 at 22:56:27 UTC; the coordinator then authorized scoring. Separate generic instrument reviews and calibration were completed before the first accuracy scores. No production tuning followed outcome review. The v1/v2 protocol commitments remain immutable historical copies, and all scorer revisions/admission records are retained.\n"
    document.write_text(final)
    return {"report": str(document), "figure": str(figure), "table": str(EVIDENCE / "all_supported_case_measurements.md"),
            "report_sha256": hashlib.sha256(document.read_bytes()).hexdigest()}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--scoring", required=True, type=Path)
    print(json.dumps(run(p.parse_args().scoring), sort_keys=True))
