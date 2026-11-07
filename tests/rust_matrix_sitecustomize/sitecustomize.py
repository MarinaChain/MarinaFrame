"""Loosen the native CAD approximation bound in the native build subprocess only.

tests/rust_matrix_worker.py puts this directory on PYTHONPATH of the isolated build
worker when a test asks for `loose_cad_bound`. The real engine then simplifies each
section with a 10 mm instead of a 1 mm bound, so the exported STEP genuinely
deviates from the measured drawing and the real audit fails trace fidelity.
Nothing here touches the audit, the run record or the controller.
"""
import os

if os.environ.get("MARINAFRAME_MATRIX_LOOSE_CAD") == "1":
    from vessel_reconstruction import geometry

    LOOSE_BOUND_M = 0.01  # the largest value the engine accepts
    geometry.normalize_sections.__kwdefaults__["max_deviation_m"] = LOOSE_BOUND_M
    geometry.build_hull.__kwdefaults__["max_deviation_m"] = LOOSE_BOUND_M
