"""Minimal unit layer for rule inputs.

Each unit maps to a physical dimension and a factor to the SI base unit of
that dimension. A conversion between units of different dimensions raises
``UnitError``. The layer is small on purpose: it covers the units that appear
in hull scantling rules, not a general unit system.
"""
from __future__ import annotations

from dataclasses import dataclass


class UnitError(ValueError):
    """Raised for an unknown unit or a conversion between unlike dimensions."""


# unit name -> (dimension, factor to the SI base unit of that dimension)
_UNITS = {
    "m": ("length", 1.0),
    "mm": ("length", 1.0e-3),
    "cm3": ("section_modulus", 1.0e-6),
    "m3": ("section_modulus", 1.0),
    "kN": ("force", 1.0e3),
    "N": ("force", 1.0),
    "dimensionless": ("dimensionless", 1.0),
}


@dataclass(frozen=True)
class Quantity:
    """A number with a unit."""

    value: float
    unit: str

    def to(self, unit: str) -> "Quantity":
        return Quantity(convert(self.value, self.unit, unit), unit)


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert ``value`` between two units of the same dimension."""
    from_dim, from_factor = _lookup(from_unit)
    to_dim, to_factor = _lookup(to_unit)
    if from_dim != to_dim:
        raise UnitError(f"cannot convert {from_unit} ({from_dim}) to {to_unit} ({to_dim})")
    return value * from_factor / to_factor


def _lookup(unit: str):
    try:
        return _UNITS[unit]
    except KeyError:
        raise UnitError(f"unknown unit: {unit!r}") from None
