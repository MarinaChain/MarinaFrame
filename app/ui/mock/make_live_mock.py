"""Add a live run (get_live_steps, get_hull_sections) to the UI mock fixtures.

The run follows the order, timing, wording and step shapes of two real live runs read
through `get_live_steps` (docs/APP_SPEC.md, "Live steps"):

- app/core/tests/fixtures/live-shipd/task (shipd-1-03915): listed strokes, read labels,
  repeated both 3 times, claimed a line, a refused click (repeated) and a refused corridor;
- work/w17/runs/w18d-corrected/dtmb5415-L0/task: first hull (155 s), scores, "Answer not
  usable", model-drawn sections that were not kept, then a kept one.

The geometry is moved onto the synthetic mock page and hull of make_mock.py, so marks fall
on the mock drawing's ink. No licensed drawing is used.

Run after make_mock.py:  python app/ui/mock/make_live_mock.py
"""

from __future__ import annotations

import json
import math

from make_mock import BEAM_M, DEPTH_M, HERE, STATIONS, section_curve, to_page

TASK = "/Users/demo/MarinaFrame/runs/2026-11-07-survey-launch"
STARTED_MS = 1_794_041_100_000
POINTS_PER_SECTION = 64

BOXES = {f"st{x:.0f}": box for x, box in STATIONS}
X_OF = {f"st{x:.0f}": x for x, _ in STATIONS}
BODY_VIEW_BOX = [80, 190, 1520, 850]
TITLE_BLOCK_BOX = [1180, 860, 1560, 960]


# ---------------------------------------------------------------- geometry

def resample(points: list[tuple[float, float]], count: int = POINTS_PER_SECTION) -> list[list[float]]:
    """Resample a polyline to `count` points spaced evenly by arc length."""
    lengths = [0.0]
    for (y0, z0), (y1, z1) in zip(points, points[1:]):
        lengths.append(lengths[-1] + math.hypot(y1 - y0, z1 - z0))
    total = lengths[-1]
    out = []
    segment = 0
    for i in range(count):
        target = total * i / (count - 1)
        while segment < len(points) - 2 and lengths[segment + 1] < target:
            segment += 1
        span = lengths[segment + 1] - lengths[segment] or 1.0
        t = (target - lengths[segment]) / span
        (y0, z0), (y1, z1) = points[segment], points[segment + 1]
        out.append([round(y0 + (y1 - y0) * t, 4), round(z0 + (z1 - z0) * t, 4)])
    return out


def curve(x_m: float, inset_m: float = 0.0) -> list[list[float]]:
    return resample(section_curve(x_m, inset_m, samples=200))


def blend(a: list[list[float]], b: list[list[float]], t: float = 0.5) -> list[list[float]]:
    return [[round(p[0] + (q[0] - p[0]) * t, 4), round(p[1] + (q[1] - p[1]) * t, 4)] for p, q in zip(a, b)]


def section(section_id, x_m, points, label, ink_rms_m=None):
    return {"id": section_id, "x_m": x_m, "points_yz_m": points, "source_label": label, "ink_rms_m": ink_rms_m}


def revision_sections(revision: str) -> list[dict]:
    """The section curves of one build. Seven sections: three drawn, four the build added."""
    st4_inner = curve(4.0, 0.18)
    st4_outer = curve(4.0)
    st12_bridge = blend(curve(4.0), curve(20.0))
    sections = [
        section("x01", 1.0, curve(1.0), "ai_inferred"),
        section("st4", 4.0, st4_inner, "repaired"),
        section("x08", 8.0, curve(8.0), "interpolated"),
        section("st12", 12.0, st12_bridge, "interpolated"),
        section("x16", 16.0, curve(16.0), "interpolated"),
        section("st20", 20.0, curve(20.0), "traced"),
        section("x23", 23.0, curve(23.0), "ai_inferred"),
    ]
    if revision in ("r0002", "r0003"):
        sections[1] = section("st4", 4.0, st4_outer, "traced")
    if revision == "r0003":
        # The model's blend near the deck edge, where the trace crossed a grid line.
        sections[1] = section("st4", 4.0, blend(st4_outer, curve(5.0), 0.35), "ai_corrected")
    return sections


INK_RMS = {
    "r0001": {"x01": None, "st4": 0.094, "x08": None, "st12": 0.061, "x16": None, "st20": 0.012, "x23": None},
    "r0002": {"x01": None, "st4": 0.031, "x08": None, "st12": 0.058, "x16": None, "st20": 0.012, "x23": None},
    "r0003": {"x01": None, "st4": 0.018, "x08": None, "st12": 0.057, "x16": None, "st20": 0.012, "x23": None},
}


def build_revision(revision: str, fit: float | None) -> dict:
    return {"id": revision, "path": f"domain/builds/{revision}", "fit": fit, "sections": revision_sections(revision)}


def score_revision(revision: str, fit: float) -> dict:
    """A score step carries the fit and ink RMS; the curves travelled with the build."""
    sections = [dict(s, points_yz_m=[], ink_rms_m=INK_RMS[revision][s["id"]]) for s in revision_sections(revision)]
    return {"id": revision, "path": f"domain/builds/{revision}", "fit": fit, "sections": sections}


def page_curve(section_id: str, points_yz_m: list[list[float]], every: int = 4) -> list[list[float]]:
    return [to_page(BOXES[section_id], y, z) for y, z in points_yz_m[::every]]


def box_mark(box, tone, label=None):
    mark = {"shape": "box", "tone": tone, "points_px": [[box[0], box[1]], [box[2], box[3]]]}
    if label:
        mark["label"] = label
    return mark


def union(*boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def pad(box, amount):
    return [box[0] - amount, box[1] - amount, box[2] + amount, box[3] + amount]


# ---------------------------------------------------------------- steps

def step(sequence, time_s, kind, actor, title, text, **fields):
    record = {
        "sequence": sequence,
        "last_sequence": sequence + 2 if actor == "model" else sequence + 1,
        "time_ms": int(time_s * 1000),
        "kind": kind,
        "actor": actor,
        "title": title,
        "text": text,
        "notes": None,
        "targets": [],
        "attention_px": None,
        "marks": [],
        "tool": None,
        "revision": None,
        "images": [],
        "model_ms": None,
        "cost_usd": None,
        "repeat_of": None,
        "count": 1,
    }
    record.update(fields)
    return record


def tool(name, duration_ms, state, text, **extra):
    return {"tool": name, "duration_ms": duration_ms, "state": state, "text": text, **extra}


def section_target(*ids):
    return [{"kind": "section", "id": i} for i in ids]


def steps() -> list[dict]:
    st4 = BOXES["st4"]
    st12 = BOXES["st12"]
    panels = [box_mark(BOXES[i], "panel", i) for i in ("st4", "st12", "st20")]
    stroke_tags = [
        ("st4-outer", page_curve("st4", curve(4.0))),
        ("st4-inner", page_curve("st4", curve(4.0, 0.18))),
        ("st4-waterline", [to_page(st4, 0.1, DEPTH_M * 0.6), to_page(st4, BEAM_M / 2 * 0.95, DEPTH_M * 0.6)]),
        ("st4-centreline", [to_page(st4, 0, 0), to_page(st4, 0, DEPTH_M * 1.08)]),
    ]
    strokes = [
        {"shape": "polyline", "tone": "stroke", "points_px": points, "tag": tag, "candidate_id": cid}
        for tag, (cid, points) in enumerate(stroke_tags, start=1)
    ]
    label_box = [st4[0] + 30, st4[1], st4[0] + 170, st4[1] + 40]
    st4_view = pad(st4, 10)
    click_point = to_page(st12, 1.15, 1.25)
    click_box = [click_point[0] - 150, click_point[1] - 150, click_point[0] + 150, click_point[1] + 150]
    corridor = [to_page(st12, y * 0.92 + 0.25, z) for y, z in curve(12.0)[4:60:6]]
    corridor_box = pad(union(*[[x, y, x, y] for x, y in corridor]), 40)
    proposed_st12 = page_curve("st12", blend(curve(4.0), curve(20.0), 0.4))
    proposed_st4 = page_curve("st4", revision_sections("r0003")[1]["points_yz_m"])
    refused_click = "Refused: The stroke at the point is followed for only 3 rows."
    refused_corridor = ("Refused: No supported ink line in the corridor (missing_curve): ink on 30 of 214 corridor "
                        "rows. Look at the attached image of your corridor and move it onto the curve.")
    plan = ("Plan: 3 stations st4, st12, st20 at x=4, 12, 20 m in one body view. First hull is valid but st4 "
            "follows the thin inner line and st12 has no line. Next: read the st4 panel, claim the heavy line, "
            "rebuild, then try st12; propose_section only where no ink can be traced.")
    plan_st12 = ("st4 is now the heavy outer line (guess, needs a person). st12 has no continuous ink: the click "
                 "and the corridor were refused. Try one blended section for st12; keep it only if the fit improves.")

    return [
        step(1, 0, "system", "code", "Run started", "The run started."),
        step(3, 0.07, "survey", "code", "Found the body plan with 3 panels",
             "Reading the sheet: one body view, three station panels and a title block.",
             attention_px=[0, 0, 1600, 1000],
             marks=[box_mark(BODY_VIEW_BOX, "view", "Body plan"), box_mark(TITLE_BLOCK_BOX, "view", "Title block"), *panels],
             tool=tool("survey_sheet", 2100, "ok", "1 view, 3 panels")),
        step(5, 2.6, "build", "code", "Built the first hull", "Building the first hull from the traced lines.",
             tool=tool("build_first_hull", 148_400, "ok", "Built; fit 0.81"),
             revision=build_revision("r0001", 0.81)),
        step(8, 151.0, "score", "code", "Compared the model with the drawing",
             "Cutting the model at each station and comparing it with the ink.",
             tool=tool("render_candidate", 52_300, "ok", "Fit 0.81"), revision=score_revision("r0001", 0.81)),
        step(10, 205.2, "system", "code", "Answer not usable", "The model's answer could not be read. It was asked again."),
        step(13, 212.4, "look", "model", "Read the candidate lines of 3 sections",
             "The first hull is too fine forward of midships, so I need to re-inspect the three station panels and "
             "their candidate traces before correcting sections.",
             notes=plan, targets=section_target("st4", "st12", "st20"),
             attention_px=union(*(BOXES[i] for i in ("st4", "st12", "st20"))), marks=panels,
             tool=tool("inspect_source", 193, "ok", "3 sections, 5 candidate lines"),
             images=["domain/inspections/crop-st4.png"], model_ms=5120, cost_usd=0.00184),
        step(16, 218.2, "strokes", "model", "Listed 4 strokes in the st4 panel",
             "Station 4 follows the thin inner line; enumerate its panel strokes to find the tagged curve "
             "carrying the ST 4 label.",
             targets=section_target("st4"), attention_px=st4_view, marks=strokes,
             tool=tool("enumerate_strokes", 1006, "ok", "4 strokes"),
             images=["domain/views/crop-st4.png"], model_ms=4233, cost_usd=0.00102),
        step(19, 222.7, "read", "model", "Read the labels",
             "I need to read the station label near the curve in its panel to identify which enumerated stroke "
             "carries it before assigning.",
             attention_px=st4_view, marks=[box_mark(label_box, "attention", "labels")],
             tool=tool("read_region", 242, "ok", "Saw a 1024 x 738 px view"),
             images=["domain/views/crop-st4.png"], model_ms=3324, cost_usd=0.00106),
        step(22, 226.9, "repeat_collapsed", "model", "Listed 4 strokes in the st4 panel (3 times)",
             "Station 4 follows the thin inner line; enumerate its panel strokes to find the tagged curve "
             "carrying the ST 4 label.",
             targets=section_target("st4"), attention_px=st4_view,
             tool=tool("enumerate_strokes", 1006, "ok", "4 strokes"), repeat_of=16, count=3,
             model_ms=4011, cost_usd=0.00098),
        step(25, 232.9, "repeat_collapsed", "model", "Read the labels (3 times)",
             "I need to read the station label near the curve in its panel to identify which enumerated stroke "
             "carries it before assigning.",
             attention_px=st4_view, tool=tool("read_region", 242, "ok", "Saw a 1024 x 738 px view"),
             repeat_of=19, count=3, model_ms=3410, cost_usd=0.00104),
        step(28, 254.7, "assign", "model", "Claimed a line is st4 (\"ST 4\")",
             "Assign the heavy outer curve (tag 1) to st4; the thin line inside it is the plating. Then build "
             "and render the draft.",
             targets=section_target("st4"), attention_px=st4_view,
             marks=[{"shape": "polyline", "tone": "accepted", "points_px": stroke_tags[0][1],
                     "label": "st4: \"ST 4\"", "candidate_id": "st4-outer"}],
             tool=tool("assign_station", 166, "ok", "Accepted as a guess for a person to confirm"),
             model_ms=4979, cost_usd=0.00119),
        step(31, 259.8, "build", "model", "Built a draft", "Every section has a line again; rebuild before checking.",
             tool=tool("build_draft", 38_200, "ok", "Built"), revision=build_revision("r0002", None),
             model_ms=3120, cost_usd=0.00091),
        step(34, 298.4, "score", "model", "Compared the body view with the drawing",
             "Check the rebuilt draft against the ink of all three panels.",
             tool=tool("render_candidate", 41_800, "ok", "Fit 0.86"), revision=score_revision("r0002", 0.86),
             images=["domain/renders/crop-st20.png"], model_ms=2870, cost_usd=0.00088),
        step(37, 345.6, "refused", "model", "Clicked on the ink at st12",
             "The st12 curve is the only real ink in its panel; clicking on the actual curve ink should yield a "
             "supported trace.",
             targets=section_target("st12"), attention_px=click_box,
             marks=[{"shape": "point", "tone": "refused", "points_px": [click_point], "label": refused_click}],
             tool=tool("trace_from_point", 238, "refused", refused_click),
             images=["domain/views/crop-st12.png"], model_ms=4528, cost_usd=0.00109),
        step(40, 350.1, "repeat_collapsed", "model", "Clicked on the ink at st12 (2 times)",
             "The st12 curve is the only real ink in its panel; clicking on the actual curve ink should yield a "
             "supported trace.",
             targets=section_target("st12"), attention_px=click_box,
             tool=tool("trace_from_point", 231, "refused", refused_click), repeat_of=37, count=2,
             model_ms=4390, cost_usd=0.00105),
        step(43, 356.3, "refused", "model", "Drew a corridor along st12",
             "The st12 curve runs from the keel up to the deck edge; trace the full ink path with a corridor "
             "instead of a single point.",
             notes=plan_st12, targets=section_target("st12"), attention_px=corridor_box,
             marks=[{"shape": "band", "tone": "refused", "points_px": corridor, "label": refused_corridor,
                     "half_width_px": 9.0}],
             tool=tool("trace_corridor", 244, "refused", refused_corridor),
             images=["domain/views/crop-st12.png"], model_ms=4691, cost_usd=0.00106),
        step(46, 363.0, "propose_section", "model", "Drew the section at st12",
             "No ink can be traced at st12; a blend of st4 and st20 should give a plausible midship section.",
             targets=section_target("st12"), attention_px=pad(st12, 10),
             marks=[{"shape": "polyline", "tone": "authored", "points_px": proposed_st12,
                     "label": "Blend of st4 and st20"}],
             tool=tool("propose_section", 683, "ok", "Not kept: fit 0.86 to 0.79", kept=False),
             model_ms=6340, cost_usd=0.00185),
        step(49, 369.8, "system", "code", "Notes shortened", "The model's notes were shortened to fit."),
        step(52, 377.2, "propose_section", "model", "Drew the section at st4",
             "The st4 trace crosses a grid line near the deck edge; blending its top with the next station "
             "should remove the kink while keeping the traced bilge.",
             targets=section_target("st4"), attention_px=st4_view,
             marks=[{"shape": "polyline", "tone": "authored", "points_px": proposed_st4,
                     "label": "Traced bilge, blended top"}],
             tool=tool("propose_section", 702, "ok", "Kept: fit 0.86 to 0.90", kept=True),
             model_ms=6120, cost_usd=0.00179),
        step(55, 384.0, "build", "model", "Built a draft", "Rebuild with the corrected st4.",
             tool=tool("build_draft", 37_900, "ok", "Built"), revision=build_revision("r0003", None),
             model_ms=2950, cost_usd=0.00090),
        step(58, 423.5, "score", "model", "Compared the plan view with the drawing",
             "Check the waterlines in plan against the corrected sections.",
             tool=tool("render_candidate", 40_100, "ok", "Fit 0.90"), revision=score_revision("r0003", 0.90),
             images=["domain/renders/crop-st12.png"], model_ms=3010, cost_usd=0.00093),
        step(61, 470.2, "finish", "model",
             "Finished: Draft built from traced ink on 2 of 3 stations; st4 corrected, st12 bridged",
             "st20 traced, st4 claimed and corrected near the deck, st12 has no readable line and stays "
             "interpolated. A person must confirm the two guesses.",
             model_ms=5230, cost_usd=0.00151),
        step(62, 470.3, "finish", "code", "Stopped with a draft to check", "The run stopped with a draft to check."),
    ]


def main() -> None:
    path = HERE / "fixtures.json"
    fixtures = json.loads(path.read_text())
    run_steps = steps()
    last = run_steps[-1]
    fixtures["live"] = {
        TASK: {
            "steps": run_steps,
            "last_sequence": last["last_sequence"],
            "started_ms": STARTED_MS,
            "elapsed_ms": last["time_ms"],
            "in_flight": None,
            "finished": True,
        }
    }
    fixtures["hull_sections"] = {
        TASK: {
            revision: {"revision": revision, "path": f"domain/builds/{revision}", "sections": revision_sections(revision)}
            for revision in ("r0001", "r0002", "r0003")
        }
    }
    # The run view shows the last kept build.
    view = fixtures["views"][TASK]
    view["revision"] = "r3"
    view["evidence"]["revision_id"] = "r3"
    path.write_text(json.dumps(fixtures, indent=1) + "\n")
    print("wrote", path, "with", len(run_steps), "live steps")


if __name__ == "__main__":
    main()
