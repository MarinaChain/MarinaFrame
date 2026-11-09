"""One short accuracy line per output (hull, tanks, steel) for a run.

The line joins two things: the measured error bands of other ships (``accuracy_bands``) and the
run's own facts (share of values by source label, open check items, fit score, which path built
the hull, hull type when known). It never says a result is approved or verified: the bands are
measurements on other sheets, not a check of this run.

Facts are a plain dict, so the app (``app/ui/js/accuracy.js``, a port of this module) and the PDF
report use the same inputs. ``tests/fixtures/accuracy_summary_cases.json`` holds cases that both
test suites run.

    {"hull": {"path": "model_reading" | "scanned_body_plan" | "vector_drawing",
              "hull_type": None | "round_bilge" | "hard_chine",
              "labels": {"traced": 9, "interpolated": 1, ...}, "to_check": 2, "fit": 0.86 or None},
     "tanks": None | {"built": 22, "total": 24, "path": None | "vector_plan" | "raster_plan",
                      "volume_labels": {"traced": 20, "read": 0, "guessed": 2} or None},
     "steel": None | {"thickness_labels": {"printed": 40, "guessed": 10} or None}}

``to_check`` and ``fit`` may be None when the caller does not know them.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path

from .accuracy_bands import Band, band, bands_for

DRAFT_NOTE = "Draft only. engineering_approved stays false; a naval architect decides what to trust."
SCOPE_NOTE = ("Bands are measured on other ships and sheets, not on this run. "
              "Where a band says not measured, nothing is known.")

HULL_DETAIL_IDS = {
    "model_reading": ("hull.model_reading_clean",),
    "scanned_body_plan": ("hull.scanned_bue_girl", "hull.scanned_bumble_bee", "hull.scanned_thayer",
                          "hull.scanned_pardon_me"),
    "vector_drawing": ("hull.vector_gunnerus",),
}
HULL_HEAD_IDS = {
    ("scanned_body_plan", "round_bilge"): ("hull.scanned_bue_girl", "hull.scanned_bumble_bee"),
    ("scanned_body_plan", "hard_chine"): ("hull.scanned_pardon_me",),
    ("scanned_body_plan", None): ("hull.scanned_bue_girl", "hull.scanned_pardon_me"),
}
TANK_HEAD_IDS = {
    "vector_plan": ("tanks.vector_gunnerus",),
    "raster_plan": ("tanks.raster_dev", "tanks.raster_holdout"),
    None: ("tanks.vector_gunnerus", "tanks.raster_holdout"),
}
STEEL_HEAD_IDS = ("steel.positions", "steel.weight")
NOT_PRESENT = {"tanks": "Tanks: none in this run.", "steel": "Steel: none in this run."}


@dataclass(frozen=True)
class OutputSummary:
    """The accuracy summary of one output."""

    output: str
    present: bool
    line: str
    chip: str  # a few characters for a compact indicator; "" when not present
    caution: bool  # true when the line carries a miss, a mixed result, a guess or an open check
    head_ids: tuple[str, ...]  # bands the line quotes
    detail_ids: tuple[str, ...]  # bands the tooltip and the report list


def _count(labels: dict | None, *names: str) -> int:
    return sum(int((labels or {}).get(name, 0) or 0) for name in names)


def _bands(ids: tuple[str, ...]) -> list[Band]:
    return [band(i) for i in ids]


def _chip(bands: list[Band]) -> str:
    return " / ".join(b.chip for b in bands)


def _weak(bands: list[Band]) -> bool:
    return any(b.outcome in ("missed", "mixed", "not measured") for b in bands)


def _hull(facts: dict) -> OutputSummary:
    path = facts.get("path") or "model_reading"
    if path not in HULL_DETAIL_IDS:
        path = "model_reading"
    hull_type = facts.get("hull_type")
    head_ids = HULL_HEAD_IDS.get((path, hull_type if path == "scanned_body_plan" else None)) or HULL_DETAIL_IDS[path]
    head = _bands(head_ids)
    text = "; ".join(b.short for b in head)
    if path == "scanned_body_plan" and hull_type is None:
        text += " (hull type not known)"
    parts = [f"Hull: {text}"]
    labels = facts.get("labels") or {}
    total = sum(int(v or 0) for v in labels.values())
    if total:
        traced = _count(labels, "traced", "repaired")
        extras = [(_count(labels, "interpolated"), "interpolated"),
                  (_count(labels, "ai_inferred", "ai_corrected"), "by AI"),
                  (_count(labels, "omitted"), "not modelled")]
        parts.append(f"{traced} of {total} sections traced" + "".join(f", {n} {word}" for n, word in extras if n))
    to_check = facts.get("to_check")
    if to_check is not None:
        parts.append(f"{to_check} to check" if to_check else "no open check items")
    fit = facts.get("fit")
    if fit is not None:
        parts.append(f"fit score {fit:.2f}")
    caution = _weak(head) or bool(to_check) or total > _count(labels, "traced", "repaired")
    return OutputSummary("hull", True, "; ".join(parts) + ".", _chip(head), caution, head_ids, HULL_DETAIL_IDS[path])


def _tanks(facts: dict | None) -> OutputSummary:
    detail_ids = tuple(b.id for b in bands_for("tanks"))
    if not facts:
        return OutputSummary("tanks", False, NOT_PRESENT["tanks"], "", False, (), ())
    head_ids = TANK_HEAD_IDS.get(facts.get("path"), TANK_HEAD_IDS[None])
    head = _bands(head_ids)
    parts = ["Tanks: " + "; ".join(b.short for b in head)]
    labels = facts.get("volume_labels")
    total = sum(int(v or 0) for v in (labels or {}).values())
    guessed = _count(labels, "guessed")
    if total:
        parts.append(f"{total - guessed} of {total} volumes traced or read" + (f", {guessed} guessed" if guessed else ""))
    missing = int(facts.get("total") or 0) - int(facts.get("built") or 0)
    if missing > 0:
        parts.append(f"{missing} not built")
    return OutputSummary("tanks", True, "; ".join(parts) + ".", _chip(head),
                         _weak(head) or guessed > 0 or missing > 0, head_ids, detail_ids)


def _steel(facts: dict | None) -> OutputSummary:
    detail_ids = tuple(b.id for b in bands_for("steel"))
    if not facts:
        return OutputSummary("steel", False, NOT_PRESENT["steel"], "", False, (), ())
    head = _bands(STEEL_HEAD_IDS)
    parts = ["Steel: " + "; ".join(b.short for b in head)]
    labels = facts.get("thickness_labels")
    total = sum(int(v or 0) for v in (labels or {}).values())
    if total:
        printed = _count(labels, "printed")
        parts.append(f"{printed} of {total} thicknesses printed, {total - printed} guessed or missing")
    return OutputSummary("steel", True, "; ".join(parts) + ".", _chip(head), True, STEEL_HEAD_IDS, detail_ids)


def summarise(facts: dict) -> dict[str, OutputSummary]:
    """The summary of every output, by output name, from a run's facts."""
    return {"hull": _hull(facts.get("hull") or {}), "tanks": _tanks(facts.get("tanks")),
            "steel": _steel(facts.get("steel"))}


# ---------------------------------------------------------------- facts of an exported draft


def hull_path_of(domain: Path) -> str:
    """``scanned_body_plan`` when the body-plan reader's stations were used, else the model path."""
    check = Path(domain) / "body-plan-check.json"
    try:
        if json.loads(check.read_text(encoding="utf-8")).get("used") is True:
            return "scanned_body_plan"
    except (OSError, ValueError):
        pass
    return "model_reading"


def steel_facts(structure_dir: Path | None) -> dict | None:
    """Steel facts from a structure folder's members table; None when the folder has none."""
    if not structure_dir:
        return None
    tables = sorted(Path(structure_dir).glob("*_steel_members.csv"))
    if not tables:
        return None
    lines = tables[0].read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("member_id,")), None)
    labels: dict[str, int] = {}
    if start is not None:
        for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
            source = row.get("thickness_source") or "none"
            labels[source] = labels.get(source, 0) + 1
    return {"thickness_labels": labels or None}


def tank_facts(capacity_rows: list[dict] | None) -> dict | None:
    """Tank facts from the capacity plan rows (``tanks.capacity_plan``); None without tanks."""
    if not capacity_rows:
        return None
    labels: dict[str, int] = {}
    for row in capacity_rows:
        if row.get("built"):
            source = (row.get("source_labels") or row.get("sources") or {}).get("volume") or "guessed"
            labels[source] = labels.get(source, 0) + 1
    return {"built": sum(1 for r in capacity_rows if r.get("built")), "total": len(capacity_rows), "path": None,
            "volume_labels": labels or None}


def facts_from_build(build, capacity_rows: list[dict] | None = None, structure_dir: Path | None = None) -> dict:
    """Facts of an exported draft (``exports.source.DraftBuild``)."""
    from .exports.source import domain_root, read_json, select_build

    domain = domain_root(build.task_dir)
    fit = None
    try:
        entry = select_build(read_json(domain / "state.json"), build.revision_id)
        fit = entry.get("combined_fit")
    except Exception:  # The fit score is optional; a missing or odd state file leaves it out.
        pass
    labels: dict[str, int] = {}
    for section in build.sections:
        label = str(section.get("source_label", "omitted"))
        labels[label] = labels.get(label, 0) + 1
    return {"hull": {"path": hull_path_of(domain), "hull_type": None, "labels": labels,
                     "to_check": sum(1 for g in build.guesses if g.get("status") == "open"), "fit": fit},
            "tanks": tank_facts(capacity_rows), "steel": steel_facts(structure_dir)}
