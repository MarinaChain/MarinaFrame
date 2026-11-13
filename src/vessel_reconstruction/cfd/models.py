"""Lane-local SI inputs and record fragments."""
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class CaseInput:
    length_m: float
    speed_m_s: float
    wetted_area_m2: float
    sources: tuple[str, ...]
    density_kg_m3: float = 999.5
    viscosity_m2_s: float = 1.27e-6
    base_cells: int = 24
    refinement_level: int = 2
    iterations: int = 1000

    def __post_init__(self):
        for name in ('length_m', 'speed_m_s', 'wetted_area_m2', 'density_kg_m3', 'viscosity_m2_s'):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        for name, low, high in (('base_cells', 4, 256), ('refinement_level', 0, 5), ('iterations', 1, 1000000)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{name} outside supported range')
        if not self.sources or any(not isinstance(s, str) or not s.strip() for s in self.sources):
            raise ValueError('sources must contain provenance')

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ResistanceResult:
    resistance_n: float
    ct: float
    samples: int
    sources: tuple[str, ...]

    def to_record_fragment(self):
        def quantity(value, unit, reason):
            return dict(value=value, unit=unit, uncertainty={'reason': reason, 'band': None},
                        method='double_body_fixed_attitude_rans', method_version='1',
                        sources=list(self.sources), status='review_required')
        return dict(
            regime='double_body_fixed_attitude', engineering_approved=False,
            resistance=quantity(self.resistance_n, 'N', 'No physical validation or discretization band yet'),
            ct=quantity(self.ct, '1', 'Excludes free-surface wave resistance; no physical validation'),
            sinkage=quantity(None, 'm', 'Fixed-attitude calculation; sinkage not solved'),
            trim=quantity(None, 'rad', 'Fixed-attitude calculation; trim not solved'),
            samples=self.samples,
        )
