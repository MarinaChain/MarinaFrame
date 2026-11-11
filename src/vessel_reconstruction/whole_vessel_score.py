"""One label-free fit score for a whole-vessel table, and its per-view scoreboard.

Whole-vessel design (docs/plans/2026-11-08-whole-vessel-design.md), section 5:

- per cell: the residual of each view (m and % of the half-beam B/2), its
  confidence and status (``view_measure`` makes the cells);
- per station (body plan), per waterline (plan) and per profile line (keel,
  top, stem, stern): RMS, max, coverage and the worst range;
- combined fit = per view, the confidence-weighted mean of ``cell_score``
  over the measured cells; the views are weighted by their share of measured
  cells (no view tuning). Cells with no ink are gaps: counted, not scored. A
  station that the table lacks while its body-plan panel exists scores 0 on
  every waterline.

W19b2 changes, measured against truth on perturbed development hulls
(``benchmarks/score_alignment.py``): ``cell_score`` keeps a slow tail past
5 % of B/2 (no saturation); a body-plan cell whose station breaks the
waterline order along x (it sits on another station's line) is capped by
that order break; keel and top cells weigh as many cells as the waterline
spacings they are off by (``span_cells``).

Body-plan-only drawings: the combined fit is the body fit; the table's own
x-fairness (D1, the "virtual plan view") is reported as warnings only.

The score uses no truth. ``keep_edit`` is the F4 keep rule on two scoreboards.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# A residual of 0 scores 1; the steep part of the score ends at this fraction of B/2.
FULL_SCORE_FRACTION = 0.05
# Share of the cell score that falls more slowly, to 0 at TAIL_ZERO_FRACTION of B/2.
TAIL_SCORE = 0.2
TAIL_ZERO_FRACTION = 0.3
# Keep rule (F4): an edit is kept when the combined fit rises by at least this ...
KEEP_MIN_IMPROVEMENT = 0.002
# ... or when it only fills gaps and no measured cell gets worse by more than
# this fraction of B/2.
GAP_FILL_MAX_WORSENING_FRACTION = 0.005
# ... and an edit is not kept when it abandons drawn station ink: a body-plan
# station cell that the old curve followed (within the score's steep part,
# FULL_SCORE_FRACTION of B/2) ends past the score's zero point
# (TAIL_ZERO_FRACTION of B/2), where the cell no longer relates to that ink.
# A smaller move can be the repair of a trace that sat on another line
# (shipd-1-09867-3v-L0 Sonnet live: off a grid ruler by 0.75 m, truth 7.6 -> 3.9 %).
# Residuals of at least this fraction of the group's worst one make its worst range.
WORST_RANGE_FRACTION = 0.5
# Lines in the summary's "worst" list.
WORST_COUNT = 3
VIEW_SHORT_NAMES = {"body_plan": "body", "half_breadth_plan": "plan", "profile": "profile"}
# Station order (W19b2). Along each waterline the table's half-breadths over x
# rise to the widest station and fall again (unimodal). A station that breaks
# this order by more than this fraction of B/2 sits on another station's ink:
# its body-plan cells then score no better than its order residual allows.
# Development truths break the order by at most 1.1 % of B/2, except 3.3 % on a
# few waterlines of shipd-1-00045 (a small, local penalty there).
ORDER_TOLERANCE_FRACTION = 0.02


def cell_score(residual_m: float, half_beam_m: float) -> float:
    """1 for a residual of 0, falling linearly to TAIL_SCORE at 5 % of B/2, then to 0 at 30 % of B/2.

    The tail keeps ranking hulls whose stations are far off (W19b2: without
    it every residual past 5 % of B/2 scored the same, so the score could not
    tell a bad hull from a worse one).
    """
    near = 1.0 - min(1.0, abs(residual_m) / (FULL_SCORE_FRACTION * half_beam_m))
    far = 1.0 - min(1.0, abs(residual_m) / (TAIL_ZERO_FRACTION * half_beam_m))
    return (1.0 - TAIL_SCORE) * near + TAIL_SCORE * far


def order_excess_m(cell: dict, half_beam_m: float) -> float:
    """How far (m) a cell's station breaks the waterline order beyond the tolerance; 0 when it keeps it."""
    return max(0.0, abs(cell.get("order_residual_m") or 0.0) - ORDER_TOLERANCE_FRACTION * half_beam_m)


def _scored(cells: list[dict], half_beam_m: float) -> list[tuple[dict, float, float]]:
    """(cell, score, weight) for every cell that counts in the fit.

    A body-plan cell whose station breaks the waterline order scores no more
    than ``cell_score`` of the excess: ink found there may be another station's.
    """
    result = []
    for cell in cells:
        if cell.get("status") == "measured":
            score = cell_score(cell["residual_m"], half_beam_m)
            excess = order_excess_m(cell, half_beam_m)
            if excess > 0:
                # No tail here: ink found on another station's line earns nothing.
                score = min(score, 1.0 - min(1.0, excess / (FULL_SCORE_FRACTION * half_beam_m)))
            result.append((cell, score, float(cell["confidence"]) * float(cell.get("span_cells", 1.0))))
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
              after_cells: list[dict] | None = None, *, gap_fill_only: bool = False,
              fit_key: str = "combined_fit") -> dict:
    """F4 keep rule: keep an edit when the fit improves, or when it only fills gaps.

    ``fit_key`` names the fit in ``before`` and ``after`` that must rise:
    ``combined_fit`` (body plan) or ``draft_fit`` (draft_fit.py, all three
    views in one frame measured by code). The cell checks below always use the
    body-plan cells.

    With the cells of both scoreboards, an edit that leaves more drawn ink
    unexplained (more ``ink_unexplained`` cells) is not kept even when the fit
    rises: the edited curve has left its own line, usually for another
    station's (W19b2: this removed about a third of the truth harm of kept edits).

    A rejected edit is not a refusal: the decision says why, with the numbers.
    """
    old, new = before.get(fit_key), after.get(fit_key)
    if old is not None and before_cells is not None and after_cells is not None:
        unexplained_before, unexplained_after = _unexplained_count(before_cells), _unexplained_count(after_cells)
        if unexplained_after > unexplained_before:
            return {"keep": False, "fit_before": old, "fit_after": new,
                    "reason": (f"drawn ink left unexplained: {unexplained_before} -> {unexplained_after} cells "
                               "(the curve left its own line)")}
    if old is not None and before_cells is not None and after_cells is not None and not gap_fill_only:
        # A curve that leaves the drawn station ink it followed contradicts the
        # drawing, whatever else the edit gains (shipd-1-09867-3v-L0 DeepSeek
        # live: a fixed top cell raised the fit while the curve left its ink
        # at WL1 by 4.4 m; truth RMS 7 -> 38 % at that station).
        abandoned = _abandoned_station_ink(before_cells, after_cells, before["half_beam_m"])
        if abandoned:
            where, residual = abandoned
            return {"keep": False, "fit_before": old, "fit_after": new, "abandoned_cell": where,
                    "reason": (f"the curve left the station ink it followed at {where} ({residual:+.2f} m, past "
                               f"{100 * TAIL_ZERO_FRACTION:g} % of B/2); follow the ink there")}
    if old is None or (new is not None and new >= old + KEEP_MIN_IMPROVEMENT):
        return {"keep": True, "reason": f"{fit_key.replace('_', ' ')} improved", "fit_before": old,
                "fit_after": new, "fit_key": fit_key}
    if gap_fill_only and before_cells is not None and after_cells is not None:
        limit = GAP_FILL_MAX_WORSENING_FRACTION * before["half_beam_m"]
        worsening = _max_worsening(before_cells, after_cells)
        if worsening <= limit:
            return {"keep": True, "reason": "gap fill; no measured cell worse by more than 0.5 % B/2",
                    "fit_before": old, "fit_after": new, "max_worsening_m": round(worsening, 4)}
    return {"keep": False, "reason": f"{fit_key.replace('_', ' ')} {old} -> {new}: needs +{KEEP_MIN_IMPROVEMENT}",
            "fit_before": old, "fit_after": new, "fit_key": fit_key}


def _abandoned_station_ink(before_cells: list[dict], after_cells: list[dict], half_beam_m: float):
    """The first body-plan station cell that the old curve followed and the new one abandons.

    Returns ``("<station> <waterline>", new residual)`` or None.
    """
    def key(cell):
        return cell.get("station_id"), cell.get("waterline_id")

    followed = {key(c) for c in before_cells if c.get("target") == "station" and c.get("status") == "measured"
                and abs(c["residual_m"]) <= FULL_SCORE_FRACTION * half_beam_m}
    for cell in after_cells:
        if (cell.get("target") == "station" and cell.get("status") == "measured" and key(cell) in followed
                and abs(cell["residual_m"]) > TAIL_ZERO_FRACTION * half_beam_m):
            return f"{cell.get('station_id')} {cell.get('waterline_id')}", cell["residual_m"]
    return None


def _unexplained_count(cells: list[dict]) -> int:
    return sum(1 for cell in cells if cell.get("target") == "ink_unexplained" and cell.get("status") == "measured")


def _max_worsening(before_cells: list[dict], after_cells: list[dict]) -> float:
    def key(cell):
        return cell["view"], cell["target"], cell.get("station_id"), cell.get("waterline_id")

    before = {key(c): abs(c["residual_m"]) for c in before_cells if c.get("status") == "measured"}
    worst = 0.0
    for cell in after_cells:
        if cell.get("status") == "measured" and key(cell) in before:
            worst = max(worst, abs(cell["residual_m"]) - before[key(cell)])
    return worst


def increasing_fit(values: np.ndarray) -> np.ndarray:
    """Least-squares non-decreasing fit (pool adjacent violators)."""
    blocks = []  # [mean, count]
    for value in values:
        blocks.append([float(value), 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            mean2, count2 = blocks.pop()
            mean1, count1 = blocks.pop()
            blocks.append([(mean1 * count1 + mean2 * count2) / (count1 + count2), count1 + count2])
    return np.concatenate([np.full(count, mean) for mean, count in blocks]) if blocks else np.zeros(0)


def unimodal_fit(values: np.ndarray) -> np.ndarray:
    """Least-squares fit that rises, then falls (best over every peak position)."""
    values = np.asarray(values, dtype=float)
    best, best_error = values, float("inf")
    for peak in range(len(values) + 1):
        rising = increasing_fit(values[:peak])
        falling = increasing_fit(values[peak:][::-1])[::-1]
        fit = np.concatenate([rising, falling])
        error = float(np.sum((fit - values) ** 2))
        if error < best_error:
            best, best_error = fit, error
    return best


def order_residuals(table) -> np.ndarray:
    """Table half-breadth minus its unimodal fit along x, per (station, waterline); NaN where undefined."""
    hb = np.asarray(table.hb_m, dtype=float)
    order = np.argsort(np.asarray(table.x_m, dtype=float), kind="stable")
    result = np.full(hb.shape, np.nan)
    for j in range(hb.shape[1]):
        column = hb[order, j]
        known = np.isfinite(column)
        if known.sum() < 3:
            continue
        residual = np.full(len(column), np.nan)
        residual[known] = column[known] - unimodal_fit(column[known])
        result[order, j] = residual
    return result


def add_order_residuals(cells: list[dict], table) -> None:
    """Attach each body-plan station cell's waterline-order residual (``order_residual_m``)."""
    residuals = order_residuals(table)
    rows = {sid: i for i, sid in enumerate(table.station_ids)}
    columns = {wid: j for j, wid in enumerate(table.waterline_ids)}
    for cell in cells:
        if cell["view"] == "body_plan" and cell["target"] == "station" and cell.get("status") == "measured":
            value = residuals[rows[cell["station_id"]], columns[cell["waterline_id"]]]
            if np.isfinite(value):
                cell["order_residual_m"] = round(float(value), 4)


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
    add_order_residuals(cells, table)
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
