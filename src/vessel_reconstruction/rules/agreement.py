"""Agreement between the rule checks and the MiDShip constraint evaluations.

Two comparisons are made:

* ``compare_tables`` covers every retained design in a subset. Rule inputs are
  rebuilt from the parameter row. The member value that the rule compares
  against is read from the MiDShip value table, so this run tests the rule
  side: required values and pass/fail.
* ``compare_bom`` covers the designs that have a bill of materials. Both the
  required value and the member value are computed here, from the BOM.

A constraint passes when ``value >= threshold`` (MiDShip convention).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from . import midship
from .engine import RuleSet, MissingInputError

# subset -> (table directory, table prefix, parameter file, BOM file stem prefix)
SUBSETS = {
    "Random": ("Random_Structures/batch_0005", "random_test_design_",
               "random_test_design_Parameters_All.csv", "random_test_design_"),
    "Repaired": ("Repaired_Structures/batch_0000", "repaired_random_design_",
                 "repaired_random_design_Parameters_Updated.csv", "repaired_random_design_design_"),
    "SGLD": ("SGLD_Gen_Structures", "sgld_", "sgld_design_parameters_Updated.csv", "sgld_design_"),
}

RELATIVE_TOLERANCE = 1.0e-4
ABSOLUTE_TOLERANCE = 1.0e-6

# Rules whose required value depends on a spacing that the MiDShip evaluator
# measures with exact-float uniqueness. See docs/RULES_V1.md.
FLOAT_UNIQUENESS_RULES = frozenset({
    "Bulkhead_Thickness", "Trans_Bulkhead_Horizontal_Stiffener_SM",
    "Trans_Bulkhead_Vertical_Stiffener_SM", "Deck_Trans_Stiff_SM", "Deck_Beam_SM",
    "Deck_Beam_Depth", "Deck_Thickness", "Hopper_Stiffener_SM",
})


@dataclass
class SubsetTables:
    name: str
    parameters: List[Dict[str, float]]
    properties: List[Dict[str, float]]
    values: List[Dict[str, float]]
    thresholds: List[Dict[str, float]]

    def retained(self) -> List[int]:
        """Rows with a complete structural-property row and complete constraint rows."""
        keep = []
        count = min(len(self.parameters), len(self.properties), len(self.values), len(self.thresholds))
        for index in range(count):
            rows = (self.properties[index], self.values[index], self.thresholds[index])
            if all(math.isfinite(v) for row in rows for v in row.values()):
                keep.append(index)
        return keep


def load_tables(root: Path, name: str) -> SubsetTables:
    directory, prefix, parameter_file, _ = SUBSETS[name]
    base = Path(root) / directory
    read = midship.read_float_table
    return SubsetTables(
        name=name,
        parameters=read(base / parameter_file),
        properties=read(base / f"{prefix}Structural_Properties.csv"),
        values=read(base / f"{prefix}Constraint_Values.csv"),
        thresholds=read(base / f"{prefix}Constraint_Thresholds.csv"),
    )


def stored_sign(column: str) -> float:
    """The maximum-spacing constraint is stored with both numbers negated."""
    return -1.0 if column == midship.SPACING_COLUMN else 1.0


def close(a: float, b: float) -> bool:
    return abs(a - b) <= max(ABSOLUTE_TOLERANCE, RELATIVE_TOLERANCE * max(abs(a), abs(b)))


@dataclass
class Comparison:
    subset: str
    index: int
    ship_type: str
    column: str
    required: float          # computed here, in the MiDShip stored convention
    provided: float          # member value used, in the MiDShip stored convention
    ms_threshold: float
    ms_value: float
    mine_pass: bool
    ms_pass: bool
    threshold_match: bool
    cause: str = ""


def classify(comparison: Comparison, strict: bool = False) -> str:
    """Name the most likely cause of a threshold mismatch.

    The labels are heuristics. They are verified on the BOM designs, where the
    dataset evaluator can be reproduced exactly (see ``compare_bom``).
    """
    if comparison.threshold_match:
        # Same required value, different member value: only possible when the
        # member value is computed here (BOM comparison). The dataset evaluator
        # measures hopper stiffener spacing with exact-float uniqueness.
        return "" if comparison.mine_pass == comparison.ms_pass else "evaluator_member_value_artifact"
    if comparison.column in FLOAT_UNIQUENESS_RULES and comparison.ms_threshold < comparison.required:
        return "evaluator_float_uniqueness"
    if strict:
        # The strict option applies text requirements that MiDShip leaves out.
        return "text_scope_difference"
    return "unexplained"


def compare_design(rule_set: RuleSet, subset: str, index: int, ship_type: str,
                   inputs: "midship.DesignInputs", ms_values: Mapping[str, float],
                   ms_thresholds: Mapping[str, float], strict: bool = False,
                   use_ms_values: bool = True) -> List[Comparison]:
    results: List[Comparison] = []
    for rule in rule_set.rules:
        column = rule.midship_column
        if not rule.applies_to(ship_type):
            continue
        sign = stored_sign(column)
        provided_stored = (ms_values[column] if use_ms_values
                           else sign * inputs.provided[column])
        provided = sign * provided_stored
        values = dict(inputs.geometry)
        values[rule.data["criterion"]["provided_input"]] = provided
        try:
            result = rule.evaluate(values, ship_type, strict=strict)
        except MissingInputError:
            continue
        required_stored = sign * result.required
        comparison = Comparison(
            subset=subset, index=index, ship_type=ship_type, column=column,
            required=required_stored, provided=provided_stored,
            ms_threshold=ms_thresholds[column], ms_value=ms_values[column],
            mine_pass=midship.midship_pass(provided_stored, required_stored),
            ms_pass=midship.midship_pass(ms_values[column], ms_thresholds[column]),
            threshold_match=close(required_stored, ms_thresholds[column]),
        )
        comparison.cause = classify(comparison, strict)
        results.append(comparison)
    return results


def compare_tables(rule_set: RuleSet, tables: SubsetTables, strict: bool = False) -> List[Comparison]:
    out: List[Comparison] = []
    for index in tables.retained():
        row = tables.parameters[index]
        ship_type = midship.ship_type_of(row)
        if ship_type is None:
            continue
        inputs = midship.inputs_from_parameters(row, ship_type)
        out.extend(compare_design(rule_set, tables.name, index, ship_type, inputs,
                                  tables.values[index], tables.thresholds[index], strict))
    return out


def compare_bom(rule_set: RuleSet, tables: SubsetTables, index: int, bom_path: Path,
                strict: bool = False, legacy_unique: bool = False) -> List[Comparison]:
    ship_type = midship.ship_type_of(tables.parameters[index])
    rows = midship.read_structural_elements(bom_path)
    inputs = midship.inputs_from_structural_elements(rows, ship_type, legacy_unique=legacy_unique)
    return compare_design(rule_set, tables.name, index, ship_type, inputs,
                          tables.values[index], tables.thresholds[index], strict,
                          use_ms_values=False)


def summarize(comparisons: Iterable[Comparison]) -> Dict[str, Dict[str, object]]:
    """Per-rule agreement figures."""
    groups: Dict[str, List[Comparison]] = defaultdict(list)
    for item in comparisons:
        groups[item.column].append(item)
    summary: Dict[str, Dict[str, object]] = {}
    for column, items in groups.items():
        # A constraint with a zero threshold and zero value is not applicable
        # (for example hopper members on a tanker); it is counted apart.
        active = [c for c in items if not (c.ms_threshold == 0.0 and c.ms_value == 0.0
                                           and c.required == 0.0)]
        confusion = Counter((c.mine_pass, c.ms_pass) for c in active)
        n = len(active)
        agree = sum(c.mine_pass == c.ms_pass for c in active)
        summary[column] = {
            "n": n,
            "not_applicable": len(items) - n,
            "threshold_match": sum(c.threshold_match for c in active),
            "threshold_match_rate": _rate(sum(c.threshold_match for c in active), n),
            "pass_agreement": agree,
            "pass_agreement_rate": _rate(agree, n),
            "ms_pass_rate": _rate(sum(c.ms_pass for c in active), n),
            "confusion": {
                "both_pass": confusion[(True, True)],
                "both_fail": confusion[(False, False)],
                "mine_pass_ms_fail": confusion[(True, False)],
                "mine_fail_ms_pass": confusion[(False, True)],
            },
            "causes": dict(Counter(c.cause for c in active if c.cause)),
        }
    return summary


def _rate(count: int, total: int) -> Optional[float]:
    return round(count / total, 6) if total else None
