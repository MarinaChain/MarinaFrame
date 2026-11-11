"""Load rule data from JSON, validate it, and run the executable checks.

The rule file is the source of truth for citations, units, applicability,
assumptions and status. The formulas are in ``formulas.py`` and are linked to
a rule by the ``check`` key. No network access, no randomness, no file writes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from .formulas import CHECKS
from .units import Quantity, UnitError, convert

SCHEMA_VERSION = "1"
STATUSES = ("encoded", "partial", "not_encoded")
CRITERION_KINDS = ("min", "max")
INPUT_ROLES = ("geometry", "provided")
ALL_SHIP_TYPES = ("tanker", "container_ship", "bulk_carrier")

DEFAULT_RULE_FILE = Path(__file__).resolve().parents[3] / "rules" / "abs_mvr_part3_midship_v1.json"


class RuleDataError(ValueError):
    """The rule file does not follow the schema."""


class MissingInputError(KeyError):
    """A required input value was not supplied."""


@dataclass(frozen=True)
class Result:
    """Outcome of one rule check for one design."""

    rule_id: str
    applicable: bool
    required: Optional[float]
    provided: Optional[float]
    passed: Optional[bool]
    unit: str
    margin: Optional[float]


@dataclass(frozen=True)
class Rule:
    data: Mapping[str, Any]

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def status(self) -> str:
        return self.data["status"]

    @property
    def midship_column(self) -> str:
        return self.data["midship_column"]

    def assumptions(self) -> Dict[str, float]:
        return {item["name"]: item["value"] for item in self.data["assumptions"]}

    def applies_to(self, ship_type: str) -> bool:
        return ship_type in self.data["applicability"]["ship_types"]

    def evaluate(self, inputs: Mapping[str, Union[float, Quantity]], ship_type: str,
                 strict: bool = False) -> Result:
        """Run the check. Floats are read in the unit the rule declares."""
        criterion = self.data["criterion"]
        unit = criterion["required_unit"]
        if not self.applies_to(ship_type):
            return Result(self.id, False, None, None, None, unit, None)
        if self.status == "not_encoded":
            raise RuleDataError(f"{self.id} is not encoded: {self.data['status_reason']}")
        values = self._converted_inputs(inputs, ship_type)
        required = CHECKS[self.data["check"]](values, self.assumptions(), strict)
        provided = values[criterion["provided_input"]]
        if criterion["kind"] == "min":
            margin = provided - required
        else:
            margin = required - provided
        return Result(self.id, True, required, provided, margin >= 0.0, unit, margin)

    def _converted_inputs(self, inputs, ship_type) -> Dict[str, float]:
        values: Dict[str, float] = {"is_tanker": 1.0 if ship_type == "tanker" else 0.0}
        for spec in self.data["inputs"]:
            name = spec["name"]
            if name == "is_tanker":
                continue
            if name not in inputs:
                raise MissingInputError(f"{self.id}: missing input {name}")
            raw = inputs[name]
            if isinstance(raw, Quantity):
                values[name] = raw.to(spec["unit"]).value
            else:
                values[name] = float(raw)
        # The hopper rule reads its own provided value as an applicability test.
        values["provided"] = values[self.data["criterion"]["provided_input"]]
        return values


@dataclass(frozen=True)
class RuleSet:
    data: Mapping[str, Any]
    rules: List[Rule]

    def by_id(self, rule_id: str) -> Rule:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        raise KeyError(rule_id)

    def by_column(self, column: str) -> Rule:
        for rule in self.rules:
            if rule.midship_column == column:
                return rule
        raise KeyError(column)


def load_rule_set(path: Union[str, Path] = DEFAULT_RULE_FILE) -> RuleSet:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(data)
    return RuleSet(data=data, rules=[Rule(item) for item in data["rules"]])


def validate(data: Mapping[str, Any]) -> None:
    """Raise ``RuleDataError`` if the rule file breaks the schema."""
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RuleDataError(f"schema_version must be {SCHEMA_VERSION!r}")
    sources = data.get("sources")
    if not sources:
        raise RuleDataError("sources is required")
    seen = set()
    for rule in data.get("rules", []):
        rule_id = rule.get("id", "<no id>")
        if rule_id in seen:
            raise RuleDataError(f"duplicate rule id {rule_id}")
        seen.add(rule_id)
        _validate_rule(rule, sources)
    if not seen:
        raise RuleDataError("rules is empty")


def _validate_rule(rule: Mapping[str, Any], sources: Mapping[str, Any]) -> None:
    rule_id = rule["id"]
    for key in ("midship_column", "title", "citations", "applicability", "inputs",
                "assumptions", "criterion", "check", "status", "status_reason"):
        if key not in rule:
            raise RuleDataError(f"{rule_id}: missing {key}")
    if rule["status"] not in STATUSES:
        raise RuleDataError(f"{rule_id}: bad status {rule['status']!r}")
    if not rule["citations"]:
        raise RuleDataError(f"{rule_id}: at least one citation is required")
    for cite in rule["citations"]:
        if cite["source"] not in sources:
            raise RuleDataError(f"{rule_id}: unknown source {cite['source']!r}")
        if not cite.get("ref") or not isinstance(cite.get("page"), int):
            raise RuleDataError(f"{rule_id}: citation needs ref and integer page")
    for ship_type in rule["applicability"].get("ship_types", []):
        if ship_type not in ALL_SHIP_TYPES:
            raise RuleDataError(f"{rule_id}: unknown ship type {ship_type!r}")
    criterion = rule["criterion"]
    if criterion.get("kind") not in CRITERION_KINDS:
        raise RuleDataError(f"{rule_id}: bad criterion kind")
    if rule["check"] not in CHECKS:
        raise RuleDataError(f"{rule_id}: unknown check {rule['check']!r}")
    names = set()
    provided = 0
    for spec in rule["inputs"]:
        if spec.get("role") not in INPUT_ROLES:
            raise RuleDataError(f"{rule_id}: input {spec.get('name')} needs a role")
        try:
            convert(1.0, spec["unit"], spec["unit"])
            convert(1.0, criterion["required_unit"], criterion["required_unit"])
        except UnitError as error:
            raise RuleDataError(f"{rule_id}: {error}") from None
        names.add(spec["name"])
        provided += spec["role"] == "provided"
    if provided != 1:
        raise RuleDataError(f"{rule_id}: exactly one provided input is required")
    if criterion["provided_input"] not in names:
        raise RuleDataError(f"{rule_id}: provided_input is not an input")
    provided_unit = next(s["unit"] for s in rule["inputs"] if s["role"] == "provided")
    if provided_unit != criterion["required_unit"]:
        # The comparison is made in one unit, so the two must be declared alike.
        raise RuleDataError(f"{rule_id}: provided unit must equal required_unit")
    if rule["status"] != "encoded" and not rule["status_reason"]:
        raise RuleDataError(f"{rule_id}: a status other than encoded needs a reason")
