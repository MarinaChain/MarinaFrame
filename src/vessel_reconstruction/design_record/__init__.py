"""Strict versioned design records. Install the project's ``data`` extra.

Loading and saving preserve the declared version. Migration is an explicit pure
transform followed by target-schema validation. Unknown fields are never dropped.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sysconfig
from typing import Any

# Keep the existing builder default stable; new callers select 1.1.0 explicitly.
SCHEMA_VERSION = "1.0.0"
SCHEMA_FILES = {
    "1.0.0": "design-record-v1.schema.json",
    "1.1.0": "design-record-v1.1.schema.json",
}


def _schema_path(version: str) -> Path:
    if not isinstance(version, str) or version not in SCHEMA_FILES:
        raise ValueError(f"Unsupported design record schema version: {version!r}")
    name = SCHEMA_FILES[version]
    path = Path(__file__).resolve().parents[3] / "schemas" / name
    if not path.is_file():
        path = Path(sysconfig.get_path("data")) / "share/marinaframe/schemas" / name
    return path


SCHEMA_PATH = _schema_path(SCHEMA_VERSION)


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Record numbers must be finite")
    if isinstance(value, dict):
        for child in value.values():
            _finite(child)
    elif isinstance(value, list):
        for child in value:
            _finite(child)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class DesignRecord:
    """Validated snapshot; accessors return copies so callers cannot bypass checks."""

    _data: dict

    def __post_init__(self):
        from jsonschema import Draft202012Validator, ValidationError

        data = deepcopy(self._data)
        _finite(data)
        if not isinstance(data, dict):
            raise ValueError("Design record must be an object")
        schema_path = _schema_path(data.get("schema_version"))
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator(schema).validate(data)
        except ValidationError as error:
            raise ValueError(f"Invalid design record at {list(error.absolute_path)}: {error.message}") from error
        speed = data["requirements"]["service_speed"]
        if speed is not None and not math.isclose(speed["m_s"]["value"], speed["kn"]["value"] * 1852 / 3600, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("Speed kn and m/s must agree")
        object.__setattr__(self, "_data", data)

    @classmethod
    def from_dict(cls, data: dict) -> "DesignRecord":
        return cls(data)

    @classmethod
    def loads(cls, text: str) -> "DesignRecord":
        return cls(json.loads(text, object_pairs_hook=_unique_object))

    @classmethod
    def load(cls, path: Path) -> "DesignRecord":
        return cls.loads(Path(path).read_text(encoding="utf-8"))

    def to_dict(self) -> dict:
        return deepcopy(self._data)

    def to_json(self) -> str:
        # Recheck even private-field mutations before a record crosses storage.
        checked = DesignRecord.from_dict(self._data)
        return json.dumps(checked._data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"

    def save(self, path: Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")


def migrate_v1_0_0_to_v1_1_0(data: dict) -> dict:
    """Validate v1, copy it, and validate v1.1 without modifying the input.

    Only the version changes. The new units become available for subsequent edits;
    this function does not convert quantities or repair invalid source records.
    """
    source = DesignRecord.from_dict(data).to_dict()
    if source["schema_version"] != "1.0.0":
        raise ValueError("Migration requires a 1.0.0 design record")
    source["schema_version"] = "1.1.0"
    return DesignRecord.from_dict(source).to_dict()


def capture_result(value: Any, *, units: dict[str, str], method: str,
                   method_version: str, sources: list[str], field: str = "") -> dict:
    """Capture full solver evidence. Numeric fields require an explicit unit map.

    Arrays inherit their field's unit. Uncertainty is explicitly unknown: this
    adapter does not invent an accuracy band for an existing solver.
    """
    arguments = dict(units=units, method=method, method_version=method_version, sources=sources)
    if value is None:
        return {"kind": "missing", "value": None}
    if isinstance(value, bool):
        return {"kind": "flag", "value": value}
    if isinstance(value, str):
        return {"kind": "text", "value": value}
    if isinstance(value, (int, float)):
        _finite(value)
        if field not in units:
            raise ValueError(f"Missing unit for numeric result field {field!r}")
        return {"kind": "quantity", "value": quantity(value, units[field], method=method, method_version=method_version, sources=sources)}
    if isinstance(value, (list, tuple)):
        return {"kind": "list", "value": [capture_result(child, field=field, **arguments) for child in value]}
    if isinstance(value, dict):
        return {"kind": "object", "value": {key: capture_result(child, field=key, **arguments) for key, child in value.items()}}
    raise ValueError(f"Unsupported result type: {type(value).__name__}")


def quantity(value: float, unit: str, *, method: str, method_version: str,
             sources: list[str]) -> dict:
    return dict(value=float(value), unit=unit, uncertainty=None,
                uncertainty_reason="No uncertainty band supplied by the source calculation.",
                method=method, method_version=method_version, sources=list(sources), status="draft")


def restore_result(evidence: dict) -> Any:
    """Recover the source JSON value from validated tagged evidence."""
    kind, value = evidence["kind"], evidence["value"]
    if kind == "quantity":
        return value["value"]
    if kind == "object":
        return {key: restore_result(child) for key, child in value.items()}
    if kind == "list":
        return [restore_result(child) for child in value]
    return value
