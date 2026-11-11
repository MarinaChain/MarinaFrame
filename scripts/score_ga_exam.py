"""Score GA readings against answers: the GA exam of the internal 23-ship pack.

Protocol: docs/plans/2026-11-12-ga-commercial.md ("Scoring"). The evaluator lane
runs this once on the frozen code's holdout outputs; development lanes test it
on synthetic fixtures only.

Usage:
    python scripts/score_ga_exam.py --predictions DIR_OR_JSON --answers JSON_OR_CSV [--out score.json]

Predictions: a directory with ``<case>/ga_reading.json`` (the output of
``python -m vessel_reconstruction.ga_commercial read``), or one JSON object
``{case: {field: value or null}}``.

Answers: JSON ``{case: {field: value or null}}`` (or ``{"cases": {...}}``), or
CSV with a ``case`` column and one column per field. Field names may use the
aliases below (LOA, LBP/LPP, B/beam, D, holds, hatches, cranes). In answers:

- a field that is absent (or an empty CSV cell) is not scored for that case;
- a field that is null, "null", "unreadable" or "-" expects an abstention.

Rules (fixed before any holdout run):

- particulars LOA, LBP, breadth, depth in metres: correct when
  |prediction - answer| <= 0.005 m; the printed value is the truth.
- counts (cargo holds, cargo hatches, cargo cranes): correct only when equal.
  0 is a valid count.
- a null prediction is an abstention. Wrong answers and abstentions are
  reported separately; an abstention is never counted as wrong, and an answer
  where an abstention was expected is wrong.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys

TOLERANCE_M = 0.005
PARTICULARS = ("loa_m", "lbp_m", "breadth_m", "depth_m")
COUNTS = ("cargo_holds", "cargo_hatches", "cargo_cranes")
FIELDS = PARTICULARS + COUNTS
ALIASES = {
    "loa": "loa_m", "loa_m": "loa_m", "length_overall": "loa_m",
    "lbp": "lbp_m", "lbp_m": "lbp_m", "lpp": "lbp_m", "lpp_m": "lbp_m",
    "b": "breadth_m", "breadth": "breadth_m", "breadth_m": "breadth_m", "beam": "breadth_m", "beam_m": "breadth_m",
    "d": "depth_m", "depth": "depth_m", "depth_m": "depth_m",
    "holds": "cargo_holds", "cargo_holds": "cargo_holds", "hold_count": "cargo_holds",
    "hatches": "cargo_hatches", "cargo_hatches": "cargo_hatches", "hatch_count": "cargo_hatches",
    "cranes": "cargo_cranes", "cargo_cranes": "cargo_cranes", "crane_count": "cargo_cranes",
}
NULL_WORDS = {"null", "none", "unreadable", "-", "n/a"}


def _key(name: str) -> str | None:
    return ALIASES.get(name.strip().lower().replace(" ", "_").replace(".", ""))


def _value(raw):
    """A number, or None for an expected abstention."""
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if text.lower() in NULL_WORDS:
            return None
        raw = float(text)
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"not a finite number: {raw!r}")
    return value


def _normalise(table: dict) -> dict[str, dict[str, float | None]]:
    out = {}
    for case, fields in table.items():
        row = {}
        for name, raw in (fields or {}).items():
            key = _key(name)
            if key is not None:
                row[key] = _value(raw)
        out[str(case)] = row
    return out


def load_answers(path: Path) -> dict[str, dict[str, float | None]]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        table = {}
        for row in rows:
            case = row.pop("case", None) or row.pop("Case", None)
            # An empty cell means "not scored"; it is dropped here.
            table[case] = {k: v for k, v in row.items() if v is not None and v.strip() != ""}
        return _normalise(table)
    data = json.loads(path.read_text())
    return _normalise(data.get("cases", data))


def _from_reading(reading: dict) -> dict[str, float | None]:
    """The exam answers of one reading: printed particulars and counts.

    Only a particular with status ``read`` (printed on the drawing) is an answer. A value
    measured with the frame scale (``measured`` block, status ``measured_from_scale``) is
    never an exam answer, also when a file carries it under ``particulars``.
    """
    printed = reading.get("particulars", {})
    row = {field: printed.get(field, {}).get("value") if printed.get(field, {}).get("status", "read") == "read"
           else None for field in PARTICULARS}
    row.update({field: reading.get("counts", {}).get(field, {}).get("value") for field in COUNTS})
    return row


def load_predictions(path: Path) -> dict[str, dict[str, float | None]]:
    path = Path(path)
    if path.is_dir():
        return {child.name: _from_reading(json.loads((child / "ga_reading.json").read_text()))
                for child in sorted(path.iterdir()) if (child / "ga_reading.json").is_file()}
    return _normalise(json.loads(path.read_text()))


def judge(field: str, predicted, expected) -> str:
    """One of correct, wrong, abstained, correct_abstention."""
    if expected is None:
        return "correct_abstention" if predicted is None else "wrong"
    if predicted is None:
        return "abstained"
    if field in PARTICULARS:
        return "correct" if abs(float(predicted) - expected) <= TOLERANCE_M + 1e-9 else "wrong"
    return "correct" if float(predicted) == expected else "wrong"


def _tally(outcomes: list[str]) -> dict:
    counts = {k: outcomes.count(k) for k in ("correct", "wrong", "abstained", "correct_abstention")}
    scored = len(outcomes)
    answered = counts["correct"] + counts["wrong"]
    counts.update(scored=scored, answered=answered,
                  accuracy_when_answered=round(counts["correct"] / answered, 4) if answered else None,
                  correct_share=round((counts["correct"] + counts["correct_abstention"]) / scored, 4) if scored else None)
    return counts


def score(predictions: dict, answers: dict) -> dict:
    per_field = {field: [] for field in FIELDS}
    per_case = {}
    for case, truth in sorted(answers.items()):
        predicted = predictions.get(case)
        case_result = {}
        for field, expected in truth.items():
            outcome = judge(field, None if predicted is None else predicted.get(field), expected)
            per_field[field].append(outcome)
            case_result[field] = outcome
        per_case[case] = {"has_prediction": predicted is not None, "fields": case_result}
    groups = {"particulars": [o for f in PARTICULARS for o in per_field[f]],
              "counts": [o for f in COUNTS for o in per_field[f]]}
    return {"schema": "marinaframe.ga_exam_score.v1", "tolerance_m": TOLERANCE_M,
            "cases_scored": len(answers), "cases_without_prediction": sorted(
                c for c in answers if c not in predictions),
            "fields": {f: _tally(o) for f, o in per_field.items() if o},
            "groups": {g: _tally(o) for g, o in groups.items()},
            "per_case": per_case, "engineering_approved": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--answers", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--summary-only", action="store_true", help="Leave per-case outcomes out of the output.")
    args = parser.parse_args(argv)
    result = score(load_predictions(args.predictions), load_answers(args.answers))
    if args.summary_only:
        result.pop("per_case")
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
