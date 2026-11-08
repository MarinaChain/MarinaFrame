"""Generate the UI mock fixtures: a synthetic body-plan PNG, a hull STL and JSON views.

Every drawing and shape here is synthetic. No licensed or downloaded drawing is used.
The JSON follows the shapes in docs/APP_SPEC.md exactly.

Run from anywhere:  python app/ui/mock/make_mock.py
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FILES = HERE / "files"

# Hull principal dimensions in metres. The hull frame is x aft-to-fore, y to port, z up.
LENGTH_M = 24.0
BEAM_M = 7.2
DEPTH_M = 3.4

# Body-plan page size in pixels.
PAGE_W = 1600
PAGE_H = 1000

# Each section region on the page: (x position in metres, region box in page pixels).
STATIONS = [
    (4.0, (120, 250, 560, 830)),
    (12.0, (580, 250, 1020, 830)),
    (20.0, (1040, 250, 1480, 830)),
]

# A fixed base time keeps the fixtures stable between runs (2026-11-07 09:00 UTC).
BASE_MS = 1_794_042_000_000

PAPER = (247, 245, 238)
INK = (34, 36, 40)
FAINT = (170, 172, 168)


def length_factor(x_m: float) -> float:
    """Fraction of full half-breadth at station x: fine at bow and stern, full amidships."""
    t = x_m / LENGTH_M
    return max(0.06, math.sin(math.pi * t) ** 0.55)


def half_breadth(x_m: float, z_m: float) -> float:
    """Half-breadth at height z for a rounded-bilge section."""
    rise = min(max(z_m / DEPTH_M, 0.0), 1.0)
    return (BEAM_M / 2) * length_factor(x_m) * rise ** 0.32


def section_curve(x_m: float, inset_m: float = 0.0, samples: int = 28) -> list[tuple[float, float]]:
    """Points (y, z) in metres from keel to deck edge for one section."""
    points = []
    for i in range(samples):
        z = DEPTH_M * (i / (samples - 1)) ** 1.4
        y = max(half_breadth(x_m, z) - inset_m, 0.0)
        points.append((y, z))
    return points


def to_page(box: tuple[int, int, int, int], y_m: float, z_m: float) -> list[float]:
    """Map section metres into page pixels inside a region box (centreline at left edge)."""
    x0, y0, x1, y1 = box
    margin = 40
    scale = min((x1 - x0 - 2 * margin) / (BEAM_M / 2), (y1 - y0 - 2 * margin) / DEPTH_M)
    px = x0 + margin + y_m * scale
    py = y1 - margin - z_m * scale
    return [round(px, 1), round(py, 1)]


def candidate_polyline(box, x_m, inset_m):
    return [to_page(box, y, z) for y, z in section_curve(x_m, inset_m)]


def draw_page(path: Path) -> None:
    image = Image.new("RGB", (PAGE_W, PAGE_H), PAPER)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=22)
    small = ImageFont.load_default(size=15)

    draw.rectangle((40, 40, PAGE_W - 40, PAGE_H - 40), outline=INK, width=3)
    draw.text((80, 80), "BODY PLAN  (synthetic test drawing)", fill=INK, font=font)
    draw.text((80, 116), "Scale 1:50   Dimensions in metres", fill=INK, font=small)

    for x_m, box in STATIONS:
        x0, y0, x1, y1 = box
        for k in range(1, 5):
            z = DEPTH_M * k / 5
            _, py = to_page(box, 0, z)
            draw.line((x0 + 30, py, x1 - 30, py), fill=FAINT, width=1)
        cx, _ = to_page(box, 0, 0)
        draw.line((cx, y0 + 20, cx, y1 - 20), fill=INK, width=2)
        outer = candidate_polyline(box, x_m, 0.0)
        inner = candidate_polyline(box, x_m, 0.18)
        draw.line([tuple(p) for p in outer], fill=INK, width=4)
        draw.line([tuple(p) for p in inner], fill=INK, width=2)
        draw.text((x0 + 40, y0 + 6), f"ST {x_m:.0f}", fill=INK, font=font)

    draw.rectangle((1180, 860, PAGE_W - 40, PAGE_H - 40), outline=INK, width=2)
    draw.text((1200, 880), "MOCK HULL A", fill=INK, font=font)
    draw.text((1200, 916), "Not a real vessel", fill=INK, font=small)
    image.save(path, optimize=True)

    for x_m, box in STATIONS:
        image.crop(box).resize((220, 290)).save(FILES / f"crop-st{x_m:.0f}.png", optimize=True)


def hull_mesh() -> np.ndarray:
    """Closed triangle mesh of the hull as an (n, 3, 3) array."""
    xs = np.linspace(0.15, LENGTH_M - 0.15, 64)
    rings = []
    for x in xs:
        starboard = [(-y, z) for y, z in reversed(section_curve(x, samples=18))]
        port = [(y, z) for y, z in section_curve(x, samples=18)]
        ring = starboard[:-1] + port  # keel to deck, both sides, shared keel point
        rings.append([(x, y, z) for y, z in ring])
    rings = np.array(rings)
    tris = []
    count = rings.shape[1]
    for a, b in zip(rings[:-1], rings[1:]):
        for j in range(count - 1):
            tris.append((a[j], b[j], b[j + 1]))
            tris.append((a[j], b[j + 1], a[j + 1]))
        # Deck: closes the loop from port deck edge back to starboard deck edge.
        tris.append((a[-1], b[-1], b[0]))
        tris.append((a[-1], b[0], a[0]))
    for ring, flip in ((rings[0], True), (rings[-1], False)):
        centre = ring.mean(axis=0)
        for j in range(count):
            p, q = ring[j], ring[(j + 1) % count]
            tris.append((centre, q, p) if flip else (centre, p, q))
    return np.array(tris)


def write_stl(path: Path, tris: np.ndarray) -> None:
    with path.open("wb") as out:
        out.write(b"MarinaFrame mock hull".ljust(80, b"\0"))
        out.write(struct.pack("<I", len(tris)))
        for t in tris:
            normal = np.cross(t[1] - t[0], t[2] - t[0])
            length = np.linalg.norm(normal) or 1.0
            out.write(struct.pack("<3f", *(normal / length)))
            for vertex in t:
                out.write(struct.pack("<3f", *vertex))
            out.write(b"\0\0")


def candidates(box, x_m, chosen, selectable_inner=True, declined=False):
    outer_why = "Follows the heavy outer line, which is the moulded hull surface on this drawing."
    inner_why = "Follows the thin line drawn inside the hull. It is most likely the inner face of the plating."
    if declined:
        outer_why = "Fits the drawn line, but the inner line fits equally well."
        inner_why = "Fits the drawn line, but the outer line fits equally well."
    return [
        {
            "id": f"st{x_m:.0f}-outer",
            "label": "Outer line",
            "chosen": chosen == "outer",
            "selectable": True,
            "why": outer_why,
            "polyline_px": candidate_polyline(box, x_m, 0.0),
        },
        {
            "id": f"st{x_m:.0f}-inner",
            "label": "Inner line",
            "chosen": chosen == "inner",
            "selectable": selectable_inner,
            "why": inner_why,
            "polyline_px": candidate_polyline(box, x_m, 0.18),
        },
        {
            "id": f"st{x_m:.0f}-waterline",
            "label": "Waterline mark",
            "chosen": False,
            "selectable": False,
            "why": "A straight horizontal mark. It is a waterline, not part of the hull.",
            "polyline_px": [to_page(box, 0.1, DEPTH_M * 0.6), to_page(box, BEAM_M / 2 * 0.95, DEPTH_M * 0.6)],
        },
    ]


def summary(slug, name, status, policy, minutes_ago, sections):
    return {
        "task": f"/Users/demo/MarinaFrame/runs/{slug}",
        "name": name,
        "status": status,
        "policy": policy,
        "updated_ms": BASE_MS - minutes_ago * 60_000,
        "sections": sections,
    }


APPROVAL_NOTICE = {
    "id": "engineering-approval",
    "tone": "info",
    "text": "Engineering approval is never automatic. A naval architect signs off outside this app.",
}

PAGE = {"path": "source/page-1.png", "width": PAGE_W, "height": PAGE_H}
MODEL = {
    "stl_path": "build/model.stl",
    "length_m": LENGTH_M,
    "beam_m": BEAM_M,
    "depth_m": DEPTH_M,
    "volume_m3": 341.7,
}

PASSING_CHECKS = [
    {"name": "Trace fidelity", "value": "0.86 mm", "limit": "1.1 mm", "result": "pass"},
    {"name": "Section spacing", "value": "8.0 m", "limit": "12.0 m", "result": "pass"},
    {"name": "Closed surface", "value": "Yes", "limit": None, "result": "pass"},
    {"name": "Length against title block", "value": "24.00 m", "limit": "± 0.05 m", "result": "pass"},
    {"name": "Displacement against drawing", "value": "Not given on the drawing", "limit": None, "result": "not_run"},
]


def evidence(revision):
    return {
        "revision_id": revision,
        "source_manifest_sha256": "9f2c6a41d0be8e57c3a1f0d27b4e6c5a8d913e0f72bc4a6d15e8f09c3b7a2d64",
        "event_head_sha256": "41be0c7d2f98a3e6b5c1d4f07a2e9b8c6d3f1e0a5b7c9d2e4f6a8b0c1d3e5f79",
        "contract": {"engineering_approved": False, "policy_version": 3, "trace_fidelity_mm": 0.86},
    }


def event(seq, minutes_ago, text, kind):
    return {"sequence": seq, "time_ms": BASE_MS - minutes_ago * 60_000, "text": text, "kind": kind}


def tug_task():
    sections = [
        {
            "id": f"st{x:.0f}",
            "x_m": x,
            "roi_px": list(box),
            "state": "chosen",
            "reason": "Picked the outer line. It is the heavy line and matches the hull edge.",
            "candidates": candidates(box, x, "outer"),
        }
        for x, box in STATIONS
    ]
    view = {
        "summary": summary("2026-11-07-harbour-tug", "Harbour tug, body plan", "needs_review", "deterministic", 12, 3),
        "revision": "r3",
        "source_page": PAGE,
        "sections": sections,
        "model": MODEL,
        "checks": PASSING_CHECKS,
        "provider": [],
        "notices": [APPROVAL_NOTICE],
        "evidence": evidence("r3"),
    }
    events = [
        event(1, 31, "Opened the drawing, page 1", "read"),
        event(2, 30, "Found 3 sections on the body plan", "read"),
        event(3, 28, "Section at 4.0 m: picked the outer line", "choose"),
        event(4, 27, "Section at 12.0 m: picked the outer line", "choose"),
        event(5, 26, "Section at 20.0 m: picked the outer line", "choose"),
        event(6, 22, "Built 3D model from 3 sections", "build"),
        event(7, 20, "Rendered side, plan and body views", "render"),
        event(8, 15, "Checked against the drawing: 4 checks pass, 1 not run", "check"),
        event(9, 12, "Finished. Ready for review", "finish"),
    ]
    return view, events


def ferry_task():
    sections = []
    for x, box in STATIONS:
        if x == 12.0:
            sections.append({
                "id": "st12",
                "x_m": x,
                "roi_px": list(box),
                "state": "declined",
                "reason": "The outer and inner lines fit equally well. The model could not tell them apart either.",
                "candidates": candidates(box, x, None, declined=True),
            })
        else:
            sections.append({
                "id": f"st{x:.0f}",
                "x_m": x,
                "roi_px": list(box),
                "state": "chosen",
                "reason": "Picked the outer line. It is the heavy line and matches the hull edge.",
                "candidates": candidates(box, x, "outer"),
            })
    view = {
        "summary": summary("2026-11-06-ferry-midship", "Passenger ferry, midship study", "declined", "live", 60 * 20, 3),
        "revision": "r2",
        "source_page": PAGE,
        "sections": sections,
        "model": dict(MODEL, volume_m3=None),
        "checks": [
            {"name": "Trace fidelity", "value": "1.42 mm", "limit": "1.1 mm", "result": "fail"},
            {"name": "Section spacing", "value": "16.0 m", "limit": "12.0 m", "result": "fail"},
            {"name": "Closed surface", "value": "Yes", "limit": None, "result": "pass"},
            {"name": "Length against title block", "value": "24.00 m", "limit": "± 0.05 m", "result": "pass"},
        ],
        "provider": [
            {
                "id": "call-0007",
                "state": "completed",
                "images": [
                    {"path": "provider/crop-st12.png", "label": "Section at 12.0 m"},
                    {"path": "provider/crop-st4.png", "label": "Section at 4.0 m, for comparison"},
                ],
                "answer": "Both lines are continuous from keel to deck. The heavier line is usually the moulded surface, but the inner line is drawn with the same weight above the waterline. I cannot tell which one is the hull.",
                "accepted": False,
                "prompt_tokens": 2412,
                "completion_tokens": 96,
                "cost_usd": 0.0031,
                "key_slot": 1,
            },
            {
                "id": "call-0006",
                "state": "completed",
                "images": [{"path": "provider/crop-st20.png", "label": "Section at 20.0 m"}],
                "answer": "The outer heavy line is the hull. The inner thin line is the plating.",
                "accepted": True,
                "prompt_tokens": 1980,
                "completion_tokens": 41,
                "cost_usd": 0.0024,
                "key_slot": 1,
            },
        ],
        "notices": [
            APPROVAL_NOTICE,
            {
                "id": "ferry-scale-title-block",
                "tone": "warning",
                "text": "The drawing has no scale bar. The scale 1:50 was read from the title block.",
            },
        ],
        "evidence": evidence("r2"),
    }
    events = [
        event(1, 60 * 20 + 14, "Opened the drawing, page 1", "read"),
        event(2, 60 * 20 + 13, "Found 3 sections on the body plan", "read"),
        event(3, 60 * 20 + 11, "Section at 4.0 m: picked the outer line", "choose"),
        event(4, 60 * 20 + 9, "Asked the model about the section at 20.0 m", "model"),
        event(5, 60 * 20 + 8, "Section at 20.0 m: picked the outer line, as the model answered", "choose"),
        event(6, 60 * 20 + 6, "Asked the model about the section at 12.0 m", "model"),
        event(7, 60 * 20 + 5, "Section at 12.0 m: declined. Two lines fit equally well", "choose"),
        event(8, 60 * 20 + 3, "Built 3D model from 2 sections", "build"),
        event(9, 60 * 20 + 1, "Checked against the drawing: 2 checks fail", "check"),
        event(10, 60 * 20, "Stopped. One section needs a person to choose", "finish"),
    ]
    return view, events


def pilot_task():
    x, box = STATIONS[0]
    sections = [
        {
            "id": "st4",
            "x_m": x,
            "roi_px": list(box),
            "state": "chosen",
            "reason": "Picked the outer line. It is the heavy line and matches the hull edge.",
            "candidates": candidates(box, x, "outer"),
        }
    ] + [
        {"id": f"st{x2:.0f}", "x_m": x2, "roi_px": list(b2), "state": "not_read", "reason": "Not read yet.", "candidates": []}
        for x2, b2 in STATIONS[1:]
    ]
    view = {
        "summary": summary("2026-11-07-pilot-boat", "Pilot boat, lines plan", "running", "deterministic", 0, 3),
        "revision": None,
        "source_page": PAGE,
        "sections": sections,
        "model": None,
        "checks": [],
        "provider": [],
        "notices": [APPROVAL_NOTICE],
        "evidence": {"revision_id": None, "contract": None},
    }
    events = [
        event(1, 2, "Opened the drawing, page 1", "read"),
        event(2, 1, "Found 3 sections on the lines plan", "read"),
        event(3, 0, "Section at 4.0 m: picked the outer line", "choose"),
    ]
    # Events the mock plays back over time to imitate a live run.
    pending = [
        {"text": "Section at 12.0 m: picked the outer line", "kind": "choose", "section": "st12"},
        {"text": "Section at 20.0 m: picked the outer line", "kind": "choose", "section": "st20"},
        {"text": "Built 3D model from 3 sections", "kind": "build", "section": None},
        {"text": "Checked against the drawing: 4 checks pass, 1 not run", "kind": "check", "section": None},
        {"text": "Finished. Ready for review", "kind": "finish", "section": None},
    ]
    return view, events, pending


def draft_banner(open_count, stuck_count):
    """Same text rules as the backend (app/core/src/view.rs, draft_notice)."""
    pickable = open_count - stuck_count
    noun = "guess" if open_count == 1 else "guesses"
    if stuck_count == 0:
        text = f"Draft: {open_count} {noun} to check. Confirm each guessed line or pick another. The app then rebuilds and checks the model."
    elif pickable == 0:
        text = f"Draft: {open_count} {noun} to check. No line could be read there, so there is nothing to pick and this run stays a draft."
    else:
        def has(n):
            return "has" if n == 1 else "have"
        text = (f"Draft: {open_count} {noun} to check. {pickable} {has(pickable)} a line to confirm or change. "
                f"{stuck_count} {has(stuck_count)} no readable line, so this run stays a draft.")
    return {"id": f"draft-guesses:{open_count}", "tone": "warning", "text": text}


def draft_task():
    """A draft: the 4 m section is a guessed line, the 12 m section has no readable line."""
    (x4, box4), (x12, box12), (x20, box20) = STATIONS
    guess4 = {
        "id": "guess-4m",
        "kind": "best_candidate",
        "x_range_m": None,
        "chosen_candidate_id": "st4-outer",
        "alternatives": ["st4-inner"],
        "score": 0.62,
        "reason": "2 lines found; took the best-supported one (score 0.62).",
    }
    guess12 = {
        "id": "guess-12m",
        "kind": "bridged_gap",
        "x_range_m": [4.0, 20.0],
        "chosen_candidate_id": None,
        "alternatives": [],
        "score": None,
        "reason": "No readable line at x=12 m; smoothed across x=4 to 20 m.",
    }
    cands4 = candidates(box4, x4, "outer")
    cands4[1]["why"] = "A thin line inside the heavy one. It is nearly as well supported."
    sections = [
        {
            "id": "st4", "x_m": x4, "roi_px": list(box4), "state": "guessed",
            "reason": guess4["reason"], "guess": guess4, "candidates": cands4,
        },
        {
            "id": "st12", "x_m": x12, "roi_px": list(box12), "state": "guessed",
            "reason": guess12["reason"], "guess": guess12, "candidates": [],
        },
        {
            "id": "st20", "x_m": x20, "roi_px": list(box20), "state": "chosen",
            "reason": "Picked the outer line. It is the heavy line and matches the hull edge.",
            "guess": None, "candidates": candidates(box20, x20, "outer"),
        },
    ]
    view = {
        "summary": summary("2026-11-07-survey-launch", "Survey launch, body plan", "draft", "live", 5, 3),
        "revision": "r2",
        "source_page": PAGE,
        "sections": sections,
        "model": MODEL,
        "checks": [{"name": "Checked against the drawing", "value": "Not run yet", "limit": None, "result": "not_run"}],
        "provider": [],
        "notices": [APPROVAL_NOTICE, draft_banner(2, 1)],
        "draft": {"status": "draft_not_verified", "guesses": [guess4, guess12], "resolved": []},
        "source_counts": [
            {"label": "traced", "count": 1},
            {"label": "interpolated", "count": 1},
            {"label": "ai_corrected", "count": 1},
        ],
        "warnings": [
            "At 12.0 m: Missing section interpolated from neighbouring profiles for draft CAD.",
            "At 4.0 m: Fairing moved the curve by up to 0.020 m.",
        ],
        "activity": {
            "steps": [
                {"sequence": 4, "tool": "inspect source", "reason": "Read all three sections before choosing lines."},
                {"sequence": 6, "tool": "propose section", "reason": "The 4 m trace crosses a grid line; wrote the curve from the neighbours."},
                {"sequence": 8, "tool": "build draft", "reason": "Every section has a curve."},
            ],
            "requests": 3,
            "prompt_tokens": 18420,
            "completion_tokens": 640,
            "list_cost_usd": 0.0121,
            "list_cost_complete": True,
        },
        "evidence": evidence("r2"),
    }
    events = [
        event(1, 9, "Run created", "other"),
        event(2, 8, "Read 3 sections", "read"),
        event(3, 7, "Picked lines on section st20", "choose"),
        event(4, 6, "Built a draft: 2 sections guessed", "build"),
    ]
    return view, events


def cancelled_task():
    view = {
        "summary": summary("2026-11-05-workboat", "Workboat, profile only", "cancelled", "deterministic", 60 * 46, 0),
        "revision": None,
        "source_page": None,
        "sections": [],
        "model": None,
        "checks": [],
        "provider": [],
        "notices": [],
        "evidence": {"revision_id": None, "contract": None},
    }
    events = [
        event(1, 60 * 46 + 3, "Opened the drawing, page 1", "read"),
        event(2, 60 * 46 + 2, "No body plan found on this page", "read"),
        event(3, 60 * 46, "Cancelled by the operator", "other"),
    ]
    return view, events


def main() -> None:
    FILES.mkdir(parents=True, exist_ok=True)
    draw_page(FILES / "page-1.png")
    write_stl(FILES / "model.stl", hull_mesh())

    tug, tug_events = tug_task()
    ferry, ferry_events = ferry_task()
    pilot, pilot_events, pilot_pending = pilot_task()
    workboat, workboat_events = cancelled_task()
    draft, draft_events = draft_task()
    views = [pilot, draft, tug, ferry, workboat]
    # Every section and view carries the draft fields of docs/APP_SPEC.md.
    for view in views:
        view.setdefault("draft", None)
        view.setdefault("source_counts", [])
        view.setdefault("warnings", [])
        view.setdefault("activity", None)
        for section in view["sections"]:
            section.setdefault("guess", None)
            section.setdefault("source", None)
    sources = {"st4": ("ai_corrected", "The trace crossed a grid line; the curve is a blend of the 0 m and 12 m sections."),
               "st12": ("interpolated", None), "st20": ("traced", None)}
    for section in draft["sections"]:
        label, basis = sources[section["id"]]
        section["source"] = {"label": label, "basis": basis}

    fixtures = {
        "tasks": [v["summary"] for v in views],
        "views": {v["summary"]["task"]: v for v in views},
        "events": {
            tug["summary"]["task"]: tug_events,
            ferry["summary"]["task"]: ferry_events,
            pilot["summary"]["task"]: pilot_events,
            workboat["summary"]["task"]: workboat_events,
            draft["summary"]["task"]: draft_events,
        },
        "playback": {"task": pilot["summary"]["task"], "events": pilot_pending, "finished_view": tug["summary"]["task"]},
        "settings": {
            "runs_folder": "/Users/demo/MarinaFrame/runs",
            "worker_python": "/Users/demo/MarinaFrame/.venv/bin/python",
            "theme": "system",
        },
        "datasets": [
            {"name": "ship-d-sample", "path": "/Users/demo/MarinaFrame/work/sources/ship-d-sample", "bytes": 48_211_968},
            {"name": "haer-sheets", "path": "/Users/demo/MarinaFrame/work/sources/haer-sheets", "bytes": 1_302_118_400},
        ],
    }
    (HERE / "fixtures.json").write_text(json.dumps(fixtures, indent=1) + "\n")
    print("wrote", HERE / "fixtures.json")


if __name__ == "__main__":
    main()
