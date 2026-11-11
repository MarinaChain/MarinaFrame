"""Compare a built hull with explicit, even-keel printed hydrostatics.

The JSON contract and starting tolerances are in docs/BOOKLET_CHECK.md. Values
are converted to metres and tonnes once on input. Missing values stay absent.
"""
from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Quantity:
    unit: str
    relative_limit: float = 0
    absolute_floor: float = 0
    length_fraction: float = 0

    def tolerance(self, printed: float, length: float) -> float:
        return max(abs(printed) * self.relative_limit, self.absolute_floor, length * self.length_fraction)


# Starting reconstruction limits, not class or stability acceptance criteria.
QUANTITIES = {
    "volume": Quantity("m3", .02), "displacement": Quantity("t", .02),
    "lcb": Quantity("m", absolute_floor=.5, length_fraction=.01),
    "vcb": Quantity("m", .01, .05), "kmt": Quantity("m", .01, .05),
    "waterplane_area": Quantity("m2", .02),
    "lcf": Quantity("m", absolute_floor=.5, length_fraction=.01),
    "tpc": Quantity("t/cm", .02), "mct": Quantity("t*m/cm", .02),
}
LENGTH_UNITS = {"m": 1, "mm": .001, "ft": .3048}
UNIT_FACTORS = {
    "m": LENGTH_UNITS, "m3": {"m3": 1, "ft3": .3048**3}, "t": {"t": 1, "kg": .001},
    "m2": {"m2": 1, "ft2": .3048**2}, "t/cm": {"t/cm": 1, "kg/cm": .001},
    "t*m/cm": {"t*m/cm": 1, "kN*m/cm": 1 / 9.80665},
    "t/m3": {"t/m3": 1, "kg/m3": .001},
}


@dataclass(frozen=True)
class BookletRow:
    draft_m: float  # height above the booklet vertical datum
    printed: dict[str, float | None]


@dataclass(frozen=True)
class Booklet:
    title: str
    density: float  # t/m3
    trim: str
    trim_m: float
    heel_deg: float
    x_origin_m: float  # position of the booklet origin in model coordinates
    x_direction: float  # +1 forward in model x, or -1
    z_origin_m: float
    trim_length_m: float | None
    mct_basis: str
    rows: tuple[BookletRow, ...]


@dataclass(frozen=True)
class Comparison:
    row: int  # one-based printed row, so repeated drafts remain distinct
    draft_m: float
    waterline_z_m: float
    quantity: str
    unit: str
    printed: float | None
    computed: float | None
    error: float | None
    relative_error_percent: float | None
    tolerance: float | None
    label: str
    reason: str
    method: str


@dataclass
class BookletCheck:
    booklet: Booklet
    comparisons: list[Comparison]
    warnings: list[str]

    @property
    def summary(self) -> dict[str, int]:
        within = sum(c.label == "within tolerance" for c in self.comparisons)
        outside = sum(c.label == "outside tolerance" for c in self.comparisons)
        return {"within": within, "outside": outside, "not_comparable": len(self.comparisons) - within - outside,
                "comparable": within + outside, "total": len(self.comparisons)}

    def as_dict(self) -> dict:
        return {"schema_version": 1, "booklet": asdict(self.booklet), "summary": self.summary,
                "comparisons": [asdict(c) for c in self.comparisons], "warnings": self.warnings,
                "engineering_approved": False}


def _number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _converted(value, unit: str, canonical: str, name: str) -> float:
    if not isinstance(unit, str) or unit not in UNIT_FACTORS[canonical]:
        raise ValueError(f"Unsupported unit for {name}: {unit!r}")
    return _number(value, name) * UNIT_FACTORS[canonical][unit]


def parse_booklet(data: dict) -> Booklet:
    """Validate a version-1 JSON object; no inferred units, density or datums."""
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("booklet schema_version must be 1")
    allowed = {"schema_version", "title", "trim", "trim_m", "heel_deg", "density", "units", "datum",
               "mct_basis", "trim_length_m", "rows"}
    if data.keys() - allowed:
        raise ValueError(f"Unknown booklet fields: {sorted(data.keys() - allowed)}")
    density, units, datum = (data.get(k) for k in ("density", "units", "datum"))
    if not all(isinstance(value, dict) for value in (density, units, datum)):
        raise ValueError("booklet density, units and datum objects are required")
    rho = _converted(density.get("value"), density.get("unit"), "t/m3", "density")
    if rho <= 0:
        raise ValueError("density must be positive")
    x_origin = _number(datum.get("x_origin_m"), "datum.x_origin_m")
    x_direction = _number(datum.get("x_direction"), "datum.x_direction")
    z_origin = _number(datum.get("z_origin_m"), "datum.z_origin_m")
    if x_direction not in (-1, 1):
        raise ValueError("datum.x_direction must be 1 or -1")
    trim = data.get("trim")
    if trim not in ("even_keel", "trimmed", "unknown"):
        raise ValueError("trim must be even_keel, trimmed or unknown")
    basis = data.get("mct_basis", "unknown")
    if basis not in ("hydrostatic", "stability", "unknown"):
        raise ValueError("mct_basis must be hydrostatic, stability or unknown")
    trim_length = data.get("trim_length_m")
    if trim_length is not None:
        trim_length = _number(trim_length, "trim_length_m")
        if trim_length <= 0:
            raise ValueError("trim_length_m must be positive")
    if not isinstance(data.get("title", "Booklet"), str):
        raise ValueError("title must be text")
    if not isinstance(data.get("rows"), list) or not data["rows"]:
        raise ValueError("rows must be a non-empty list")
    # Check declared units too, even if their column happens to be blank.
    for key, unit in units.items():
        if key not in {"draft", *QUANTITIES}:
            raise ValueError(f"Unknown unit column: {key}")
        _converted(0, unit, "m" if key == "draft" else QUANTITIES[key].unit, key)
    rows = []
    for index, row in enumerate(data["rows"], 1):
        if not isinstance(row, dict) or row.keys() - {"draft", *QUANTITIES}:
            raise ValueError(f"Unknown quantity or invalid row {index}")
        draft = _converted(row.get("draft"), units.get("draft"), "m", f"row {index} draft")
        printed = {}
        for key, quantity in QUANTITIES.items():
            value = row.get(key)
            printed[key] = None if value is None else _converted(value, units.get(key), quantity.unit, key)
        rows.append(BookletRow(draft, printed))
    return Booklet(data.get("title", "Booklet"), rho, trim, _number(data.get("trim_m", 0), "trim_m"),
                   _number(data.get("heel_deg", 0), "heel_deg"), x_origin, x_direction, z_origin,
                   trim_length, basis, tuple(rows))


def load_booklet(source: Path | str) -> Booklet:
    """Read a Path, or parse JSON text. Use Path for a file name."""
    text = source.read_text(encoding="utf-8") if isinstance(source, Path) else source
    try:
        return parse_booklet(json.loads(text))
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid booklet JSON: {error}") from error


def _computed_values(h, booklet: Booklet) -> dict[str, float | None]:
    return {"volume": h.volume_m3, "displacement": h.displacement_t,
            "lcb": (h.lcb_m - booklet.x_origin_m) * booklet.x_direction if h.lcb_m is not None else None,
            "vcb": h.vcb_m - booklet.z_origin_m if h.vcb_m is not None else None,
            "kmt": h.kb_m + h.bmt_m if h.kb_m is not None and h.bmt_m is not None else None,
            "waterplane_area": h.waterplane_area_m2,
            "lcf": (h.lcf_m - booklet.x_origin_m) * booklet.x_direction if h.lcf_m is not None else None,
            "tpc": booklet.density * h.waterplane_area_m2 / 100,
            "mct": booklet.density * h.bml_m * h.volume_m3 / (100 * booklet.trim_length_m)
            if h.bml_m is not None and booklet.trim_length_m and booklet.mct_basis == "hydrostatic" else None}


def compare_booklet(booklet: Booklet, *, triangles: np.ndarray | None = None,
                    sections: list[dict] | None = None) -> BookletCheck:
    """Run the export engine at each printed draft. Supply one built geometry form."""
    # Local imports avoid the exports package's public API import cycle.
    from .exports.hydrostatics import mesh_hydrostatics, table_hydrostatics
    from .exports.offsets import section_curves

    if (triangles is None) == (sections is None):
        raise ValueError("Supply exactly one of triangles or sections")
    if triangles is not None:
        triangles = np.asarray(triangles, dtype=float)
        if triangles.ndim != 3 or triangles.shape[1:] != (3, 3) or not len(triangles):
            raise ValueError("triangles must have shape (n, 3, 3), n > 0")
        coordinates = triangles.reshape(-1, 3)
    else:
        coordinates = np.array([[float(s["x_m"]), float(y), float(z)]
                                for s in sections for c in section_curves(s) for y, z in c])
        if not len(coordinates):
            raise ValueError("sections must contain built curves")
    if not np.isfinite(coordinates).all():
        raise ValueError("Built geometry must be finite")
    keel, top = float(coordinates[:, 2].min()), float(coordinates[:, 2].max())
    length = float(np.ptp(coordinates[:, 0]))
    comparisons, warnings = [], []
    for index, row in enumerate(booklet.rows, 1):
        level = row.draft_m + booklet.z_origin_m
        reason, method, computed = "", "", {}
        if booklet.trim != "even_keel" or booklet.trim_m != 0 or booklet.heel_deg != 0:
            reason = "Booklet is not upright and even keel"
        elif level <= keel or level > top:
            reason = f"Draft outside immersed hull range: {keel:g} < model z <= {top:g} m"
        else:
            try:
                if triangles is not None:
                    h = mesh_hydrostatics(triangles, level, "printed booklet draft", density=booklet.density)
                else:
                    h = table_hydrostatics(sections, level, "printed booklet draft", density=booklet.density)
                computed, method = _computed_values(h, booklet), h.method
                warnings.extend(w for w in h.warnings if w not in warnings)
            except (ValueError, ArithmeticError) as error:
                reason = f"Hydrostatics not computed: {error}"
        for key, quantity in QUANTITIES.items():
            printed, value = row.printed[key], computed.get(key)
            cell_reason = reason
            if not cell_reason and printed is None:
                cell_reason = "Quantity not printed"
            if not cell_reason and value is None:
                cell_reason = ("MCT needs hydrostatic basis and trim_length_m" if key == "mct"
                               else "Quantity not computed")
            if value is not None and not math.isfinite(value):
                value, cell_reason = None, "Computed value is not finite"
            error = value - printed if value is not None and printed is not None and not cell_reason else None
            tolerance = quantity.tolerance(printed, length) if printed is not None else None
            label = "not comparable"
            if error is not None:
                # Allow floating-point roundoff at the inclusive tolerance boundary.
                within = abs(error) <= tolerance or math.isclose(abs(error), tolerance, rel_tol=1e-12, abs_tol=1e-12)
                label = "within tolerance" if within else "outside tolerance"
            comparisons.append(Comparison(index, row.draft_m, level, key, quantity.unit, printed, value, error,
                                          error / abs(printed) * 100 if error is not None and printed != 0 else None,
                                          tolerance, label, cell_reason, method))
    return BookletCheck(booklet, comparisons, warnings)


def write_comparison_csv(check: BookletCheck, path: Path, stamp_lines: Sequence[str] = ()) -> None:
    """Write every quantity cell, including unavailable values and their reasons."""
    from .exports.csv_safety import safe_text_cell

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        metadata = [*stamp_lines, f"Booklet: {check.booklet.title}",
                    f"Density: {check.booklet.density:g} t/m3; trim: {check.booklet.trim}",
                    f"Datum: x_origin_m={check.booklet.x_origin_m:g}, x_direction={check.booklet.x_direction:g}, "
                    f"z_origin_m={check.booklet.z_origin_m:g}; KMT is above the built keel",
                    f"MCT basis: {check.booklet.mct_basis}; trim_length_m={check.booklet.trim_length_m}",
                    *check.warnings]
        for line in metadata:
            writer.writerow([safe_text_cell(f"# {line}")])
        writer.writerow(list(Comparison.__dataclass_fields__))
        for cell in check.comparisons:
            writer.writerow([safe_text_cell(v) if isinstance(v, str) else v for v in asdict(cell).values()])
