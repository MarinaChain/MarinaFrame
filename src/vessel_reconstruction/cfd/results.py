"""Strict OpenCFD forces.dat reader; no empirical resistance substitution."""
import json
import math
from pathlib import Path
import re

from .models import CaseInput, ResistanceResult

NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
VECTOR = rf'\(\s*({NUMBER})\s+({NUMBER})\s+({NUMBER})\s*\)'
# OpenCFD writes pressure, viscous, porous vectors for both force and moment.
ROW = re.compile(rf'^\s*({NUMBER})\s+\(\s*{VECTOR}\s*{VECTOR}\s*{VECTOR}\s*\)\s+\(\s*{VECTOR}\s*{VECTOR}\s*{VECTOR}\s*\)\s*$')


def read_forces(path: Path, inputs: CaseInput, *, start_time: float, force_multiplier=0.5,
                run_receipt: Path | None = None):
    """Mean samples from start_time onward; caller must first check run completion.

    Use multiplier 0.5 for the case writer's reflected double body, or 2 for a
    symmetry-half force file. Reference area always belongs to the real hull.
    No absolute value: signed axial force must remain visible to catch axes errors.
    """
    if run_receipt is not None:
        receipt = json.loads(Path(run_receipt).read_text())
        if receipt.get('state') != 'completed' or receipt.get('exit_code') != 0:
            raise ValueError('Force results require a completed run')
    if force_multiplier not in (0.5, 1., 2.) or not math.isfinite(start_time):
        raise ValueError('Invalid averaging window or geometry multiplier')
    forces = []
    previous = -math.inf
    with Path(path).open() as stream:
        for line in stream:
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            match = ROW.fullmatch(line)
            if not match:
                raise ValueError('Malformed OpenCFD force row')
            values = [float(v) for v in match.groups()]
            if not all(math.isfinite(v) for v in values) or values[0] <= previous:
                raise ValueError('Nonfinite or non-increasing force data')
            previous = values[0]
            if values[0] >= start_time:
                forces.append((values[1] + values[4] + values[7]) * force_multiplier)
    if not forces:
        raise ValueError('No samples in averaging window')
    force = math.fsum(forces) / len(forces)
    ct = force / (0.5 * inputs.density_kg_m3 * inputs.speed_m_s**2 * inputs.wetted_area_m2)
    return ResistanceResult(force, ct, len(forces), tuple(inputs.sources) + (str(path),))
