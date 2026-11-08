"""One label-free fit score for a whole-vessel table, and its per-view scoreboard.

Whole-vessel design (docs/plans/2026-11-08-whole-vessel-design.md), section 5:

- per cell: the residual of each view (m and % of the half-beam B/2), its
  confidence and status (``view_measure`` makes the cells);
- per station (body plan), per waterline (plan) and per profile line (keel,
  top, stem, stern): RMS, max, coverage and the worst range;
- combined fit = per view, the confidence-weighted mean of
  ``1 - min(1, |residual| / (5 % B/2))`` over the measured cells; the views are
  weighted by their share of measured cells (no view tuning). Cells with no
  ink are gaps: counted, not scored. A station that the table lacks while
  its body-plan panel exists scores 0 on every waterline.

Body-plan-only drawings: the combined fit is the body fit; the table's own
x-fairness (D1, the "virtual plan view") is reported as warnings only.

The score uses no truth. ``keep_edit`` is the F4 keep rule on two scoreboards.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# A residual of this fraction of B/2 (or more) scores 0; a residual of 0 scores 1.
FULL_SCORE_FRACTION = 0.05
# Keep rule (F4): an edit is kept when the combined fit rises by at least this ...
KEEP_MIN_IMPROVEMENT = 0.002
# ... or when it only fills gaps and no measured cell gets worse by more than
# this fraction of B/2.
GAP_FILL_MAX_WORSENING_FRACTION = 0.005
# Residuals of at least this fraction of the group's worst one make its worst range.
WORST_RANGE_FRACTION = 0.5
# Lines in the summary's "worst" list.
WORST_COUNT = 3
VIEW_SHORT_NAMES = {"body_plan": "body", "half_breadth_plan": "plan", "profile": "profile"}


def cell_score(residual_m: float, half_beam_m: float) -> float:
    """1 for a residual of 0, falling linearly to 0 at 5 % of B/2."""
    return 1.0 - min(1.0, abs(residual_m) / (FULL_SCORE_FRACTION * half_beam_m))


def _scored(cells: list[dict], half_beam_m: float) -> list[tuple[dict, float, float]]:
    """(cell, score, weight) for every cell that counts in the fit."""
    result = []
    for cell in cells:
        if cell.get("status") == "measured":
            result.append((cell, cell_score(cell["residual_m"], half_beam_m), float(cell["confidence"])))
        elif cell.get("status") == "table_missing":
            result.append((cell, 0.0, 1.0))
    return result


def group_key(cell: dict) -> str:
    """Scoreboard group of a cell: station (body), waterline or deck (plan), profile line."""
    if cell["view"] == "body_plan":
        return cell["station_id"]
    if cell["view"] == "half_breadth_plan":
        return cell["waterline_id"]
    return cell["target"]


def _range_text(cells: list[dict], view: str) -> str | None:
    values = [c["z_m"] if view == "body_plan" or c["target"] in ("stem", "stern") else c["x_m"] for c in cells]
    values = [v for v in values if v is not None]
    if not values:
        return None
    axis = "z" if view == "body_plan" or cells[0]["target"] in ("stem", "stern") else "x"
    low, high = min(values), max(values)
    return f"{axis} {low:.3g} m" if low == high else f"{axis} {low:.3g}-{high:.3g} m"


def group_stats(cells: list[dict], half_beam_m: float) -> dict:
    """RMS, max, coverage and worst range of one scoreboard group."""
    view = cells[0]["view"]
    measured = [c for c in cells if c["status"] == "measured"]
    gaps = sum(1 for c in cells if c["status"] == "no_ink")
    missing = sum(1 for c in cells if c["status"] == "table_missing")
    stats = {"view": view, "cells": len(cells), "measured": len(measured), "gaps": gaps, "table_missing": missing,
             "coverage": round(len(measured) / max(1, len(measured) + gaps), 4)}
    scored = _scored(cells, half_beam_m)
    weight = sum(w for _, _, w in scored)
    stats["fit"] = round(sum(s * w for _, s, w in scored) / weight, 4) if weight > 0 else None
    if measured:
        residuals = np.array([c["residual_m"] for c in measured])
        worst_index = int(np.argmax(np.abs(residuals)))
        worst = float(residuals[worst_index])
        band = [c for c in measured if abs(c["residual_m"]) >= WORST_RANGE_FRACTION * abs(worst)]
        stats.update(rms_m=round(float(np.sqrt(np.mean(residuals ** 2))), 4),
                     rms_pct_half_beam=round(100 * float(np.sqrt(np.mean(residuals ** 2))) / half_beam_m, 3),
                     max_abs_m=round(abs(worst), 4), signed_at_max_m=round(worst, 4),
                     worst_range=_range_text(band, view))
    return stats


def scoreboard(cells: list[dict], half_beam_m: float, *, fairness: dict | None = None,
               revision: str | None = None) -> dict:
    """Combined fit, per-view and per-group scores, worst targets and a one-line summary."""
    views = sorted({c["view"] for c in cells}, key=lambda v: list(VIEW_SHORT_NAMES).index(v))
    mode = "three_view" if any(v != "body_plan" for v in views) else "body_only"
    per_view, fits, counts = {}, {}, {}
    for view in views:
        members = [c for c in cells if c["view"] == view]
        per_view[view] = group_stats(members, half_beam_m)
        scored = _scored(members, half_beam_m)
        weight = sum(w for _, _, w in scored)
        if weight > 0:
            fits[view] = sum(s * w for _, s, w in scored) / weight
            counts[view] = len(scored)
    total = sum(counts.values())
    combined = sum(fits[v] * counts[v] / total for v in fits) if total else None
    groups = {}
    for cell in cells:
        groups.setdefault((cell["view"], group_key(cell)), []).append(cell)
    group_rows = []
    for (view, key), members in sorted(groups.items(), key=lambda item: (views.index(item[0][0]), item[0][1])):
        group_rows.append({"group": key, **group_stats(members, half_beam_m)})
    ranked = sorted((g for g in group_rows if g.get("rms_m") is not None or g["table_missing"]),
                    key=lambda g: (-g["table_missing"], -(g.get("rms_m") or 0.0)))
    worst = [_worst_text(g) for g in ranked[:WORST_COUNT]]
    board = {"method": "whole_vessel_fit_v1", "mode": mode, "revision": revision,
             "half_beam_m": round(half_beam_m, 4), "combined_fit": None if combined is None else round(combined, 4),
             "views": per_view, "groups": group_rows, "worst": worst,
             "measured_cells": sum(v["measured"] for v in per_view.values()),
             "gap_cells": sum(v["gaps"] for v in per_view.values()),
             "table_missing_cells": sum(v["table_missing"] for v in per_view.values()),
             "full_score_residual_m": round(FULL_SCORE_FRACTION * half_beam_m, 4),
             "label_free": True}
    if fairness is not None:
        board["fairness"] = {"status": fairness.get("status"), "outliers": fairness.get("outliers", []),
                             "warnings": [s["reason"] for s in fairness.get("sections", []) if s.get("flagged")]}
    board["summary_line"] = summary_line(board)
    return board


def _worst_text(group: dict) -> str:
    view = VIEW_SHORT_NAMES[group["view"]]
    if group["table_missing"]:
        return f"{group['group']} {view}: not in the table ({group['table_missing']} cells)"
    text = f"{group['group']} {view} {group['signed_at_max_m']:+.2f} m"
    return f"{text} {group['worst_range']}" if group.get("worst_range") else text


def summary_line(board: dict) -> str:
    """The progress-observation lines of design section 5."""
    head = [f"draft {board['revision'] or '-'}", f"fit {board['combined_fit']}" if board["combined_fit"] is not None
            else "fit -"]
    for view, stats in board["views"].items():
        if stats.get("rms_m") is not None:
            head.append(f"{VIEW_SHORT_NAMES[view]} {stats['rms_m']:.3f} m")
    measured, gaps = board["measured_cells"], board["gap_cells"]
    head.append(f"coverage {100 * measured / max(1, measured + gaps):.0f} %")
    lines = ["  ".join(head)]
    if board["worst"]:
        lines.append("worst: " + " | ".join(board["worst"]))
    if board.get("fairness") is not None:
        outliers = board["fairness"]["outliers"]
        lines.append(f"fairness: {len(outliers)} warning(s)" + (f" ({', '.join(outliers)})" if outliers else ""))
    return "\n".join(lines)


def keep_edit(before: dict, after: dict, before_cells: list[dict] | None = None,
              after_cells: list[dict] | None = None, *, gap_fill_only: bool = False) -> dict:
    """F4 keep rule: keep an edit when the combined fit improves, or when it only fills gaps.

    A rejected edit is not a refusal: the decision says why, with the numbers.
    """
    old, new = before.get("combined_fit"), after.get("combined_fit")
    if old is None or (new is not None and new >= old + KEEP_MIN_IMPROVEMENT):
        return {"keep": True, "reason": "combined fit improved", "fit_before": old, "fit_after": new}
    if gap_fill_only and before_cells is not None and after_cells is not None:
        limit = GAP_FILL_MAX_WORSENING_FRACTION * before["half_beam_m"]
        worsening = _max_worsening(before_cells, after_cells)
        if worsening <= limit:
            return {"keep": True, "reason": "gap fill; no measured cell worse by more than 0.5 % B/2",
                    "fit_before": old, "fit_after": new, "max_worsening_m": round(worsening, 4)}
    return {"keep": False, "reason": f"combined fit {old} -> {new}: needs +{KEEP_MIN_IMPROVEMENT}",
            "fit_before": old, "fit_after": new}


def _max_worsening(before_cells: list[dict], after_cells: list[dict]) -> float:
    def key(cell):
        return cell["view"], cell["target"], cell.get("station_id"), cell.get("waterline_id")

    before = {key(c): abs(c["residual_m"]) for c in before_cells if c.get("status") == "measured"}
    worst = 0.0
    for cell in after_cells:
        if cell.get("status") == "measured" and key(cell) in before:
            worst = max(worst, abs(cell["residual_m"]) - before[key(cell)])
    return worst


def table_fairness(table) -> dict:
    """D1 fairness of the table's station curves (the body-only "virtual plan view"); warnings only."""
    from .fairness import check_fairness
    sections = [{"id": sid, "x_m": float(table.x_m[i]), "points_yz_m": table.row(i).tolist()}
                for i, sid in enumerate(table.station_ids) if table.row(i) is not None]
    return check_fairness(sections)


def score_table(table, views: dict, grey: np.ndarray, *, out: Path | None = None, revision: str | None = None,
                half_beam_m: float | None = None, overlays: bool = True) -> dict:
    """Measure the table in every view, score it, and (with ``out``) write cells, scoreboard and overlays."""
    from .view_measure import draw_overlays, measure_views, station_ink_fits, write_cells
    half_beam = float(half_beam_m or table.half_beam_m() or 1.0)
    cells = measure_views(table, views, grey, half_beam_m=half_beam)
    fairness = table_fairness(table) if set(views) == {"body_plan"} else None
    board = scoreboard(cells, half_beam, fairness=fairness, revision=revision)
    board["station_ink_fit"] = station_ink_fits(table, views, grey)
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        write_cells(cells, out / "view-cells.jsonl")
        if overlays:
            board["artifacts"] = draw_overlays(table, views, grey, cells, half_beam, out)
        (out / "whole-vessel-scoreboard.json").write_text(json.dumps(board, indent=2))
    return {**board, "cells": cells}
