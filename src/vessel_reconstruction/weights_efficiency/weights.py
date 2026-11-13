"""Watson-family preliminary weights with explicit coefficients and CG inputs.

Secondary equation source: public NTUA preliminary tanker thesis, sections
3.1.1.1 (steel), 3.1.2.3 (outfit), 3.1.3.2 (machinery remainder), printed
pp22–23,29–30. See lane plan for URL and limitations. No default K or CG
regression is claimed: coefficients require a justified parent-ship basis.
Engine mass is supplied from the selected engine, not a medium-speed formula.
"""
from dataclasses import dataclass, replace
import math

from . import Calculation, _positive, _quantity, _sources


@dataclass(frozen=True)
class WeightInput:
    length_m: float  # Lpp, consistent with coefficient source
    beam_m: float
    depth_m: float
    draft_m: float
    cb_at_80_depth: float  # evaluate on hull at 0.8D, not service-draft Cb
    narrow_house_lh_m2: float  # sum length*height, width < .92B
    wide_house_lh_m2: float  # sum length*height, width >= .92B
    steel_coefficient: float
    outfit_t_m2: float
    machinery_rest_coefficient: float  # kW-based .70 power law
    main_engine_mass_t: float
    mcr_kw: float
    displacement_t: float
    component_cg_m: tuple[tuple[float, float, float], ...]  # steel, outfit, machinery
    component_relative_bands: tuple[float, ...]  # same order; absolute relative half-widths
    band_basis: str
    sources: tuple[str, ...]


def estimate_weights(data: WeightInput) -> Calculation:
    """Return mass and CG in caller's common datum (x from AP, y CL, z baseline).

    Lightship band is the sum of absolute component bands (fully correlated
    worst case), not a statistical confidence interval. It excludes modelling
    bias outside the stated basis. No DWT/CG band without displacement/CG errors.
    """
    _sources(data.sources)
    for name in ("length_m", "beam_m", "depth_m", "draft_m", "steel_coefficient",
                 "outfit_t_m2", "machinery_rest_coefficient", "main_engine_mass_t", "mcr_kw", "displacement_t"):
        _positive(name, getattr(data, name))
    if not 0 < data.cb_at_80_depth <= 1 or data.draft_m > data.depth_m:
        raise ValueError("Cb must be in (0,1] and draft cannot exceed depth")
    for area in (data.narrow_house_lh_m2, data.wide_house_lh_m2):
        if not math.isfinite(area) or area < 0:
            raise ValueError("house length-height areas must be finite and nonnegative")
    if len(data.component_cg_m) != 3 or any(len(cg) != 3 or not all(math.isfinite(v) for v in cg) for cg in data.component_cg_m):
        raise ValueError("three component CG triples are required")
    if (len(data.component_relative_bands) != 3 or not data.band_basis.strip()
            or any(not math.isfinite(b) or not 0 <= b < 1 for b in data.component_relative_bands)):
        raise ValueError("three relative bands in [0,1) and their basis are required")
    equipment = (data.length_m*(data.beam_m+data.draft_m)
                 + .8*data.length_m*(data.depth_m-data.draft_m)
                 + .85*data.narrow_house_lh_m2 + .75*data.wide_house_lh_m2)
    masses = (data.steel_coefficient * equipment**1.36 * (1+.5*(data.cb_at_80_depth-.7)),
              data.outfit_t_m2 * data.length_m*data.beam_m,
              data.main_engine_mass_t + data.machinery_rest_coefficient*data.mcr_kw**.70)
    lightship = sum(masses)
    if lightship >= data.displacement_t:
        raise ValueError("predicted lightship leaves no positive deadweight")
    sources = data.sources + ("NTUA tanker thesis sections 3.1.1.1, 3.1.2.3, 3.1.3.2",)
    quantities = {}
    for name, mass, band in zip(("steel_t", "outfit_t", "machinery_t"), masses, data.component_relative_bands):
        q = _quantity(mass, "t", "watson_family_explicit_coefficients", sources)
        quantities[name] = replace(q, uncertainty={"absolute_band": mass*band, "unit": "t", "basis": data.band_basis})
    total_band = sum(m*b for m, b in zip(masses, data.component_relative_bands))
    quantities["lightship_t"] = replace(_quantity(lightship, "t", "component_mass_sum", sources),
                                        uncertainty={"absolute_band": total_band, "unit": "t", "basis": "Conservative sum: " + data.band_basis})
    quantities["deadweight_t"] = _quantity(data.displacement_t-lightship, "t", "displacement_minus_lightship", sources)
    for axis, index in (("x", 0), ("y", 1), ("z", 2)):
        cg = sum(m*position[index] for m, position in zip(masses, data.component_cg_m))/lightship
        quantities[f"lightship_{axis}_m"] = _quantity(cg, "m", "mass_weighted_component_cg", sources)
    return Calculation(quantities, "Preliminary explicit-coefficient weights; uncalibrated. CG inputs use AP/CL/baseline datum; no stability claim.")
