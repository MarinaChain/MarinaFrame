"""Read a commercial ship's general arrangement (GA): particulars, counts and spaces.

Plan and protocol: docs/plans/2026-11-12-ga-commercial.md.

Division of work:

- Code prepares the images (a reduced whole sheet plus higher-resolution tiles,
  within the provider's 2,048 px / 1 Mpx image limit), maps every model box
  back to sheet pixels, checks that each box holds ink, parses printed
  particulars with their units (``particulars._LENGTH``), refuses implausible
  or ambiguous values, checks counts against the labelled items, and writes a
  ``source-record/v1`` record for every value and space.
- The model (Claude Sonnet 5.5 through the Claude subscription, purpose
  ``ga_reading`` of ``marinaframe vision-request``) reads the labels and
  judges what each drawn space is. Every request is receipted by the Rust
  controller. This module never contacts a provider itself.

Every value is ``read``, ``guessed`` or ``unknown`` (null). Nothing is
approved; ``engineering_approved`` is always false."""
from __future__ import annotations

from .ga_commercial_cli import (
    main,
)
from .ga_commercial_settings import (
    MAX_REQUESTS_PER_SHIP,
    MODEL,
)
from .ga_counts import (
    drop_fragments,
)
from .ga_images import (
    prepare,
)
from .ga_interpretation import (
    interpret,
)
from .ga_provider import (
    add_usage,
    call_model,
    usage_of,
)
from .ga_reading_output import (
    write_app_run,
)
from .provenance import write_json
from pathlib import Path
import json


def read_one(ga: Path | None, particulars: Path | None, out: Path, binary: Path, basis: str,
             model: str = MODEL, app_task: Path | None = None, fine: bool = True,
             measure: bool = False, case_id: str | None = None,
             max_requests: int = MAX_REQUESTS_PER_SHIP, definitions: dict | None = None) -> dict:
    """Coarse request, interpretation, the fine pass and the frame-scale pass; writes ``out/ga_reading.json``.

    With ``measure`` the frame-scale pass (``ga_scale``, up to seven more requests) adds ``frames``,
    ``measured`` and the extent of each space, and writes ``out/ga_arrangement_input.json``.

    ``result["passes"]`` records per ship the requests and crops each pass needed.
    """
    from .ga_labels import fine_pass
    out = Path(out).resolve()
    prepare(ga, out / "request", particulars, definitions)
    binary = Path(binary).resolve()
    reading = call_model(binary, out / "request", out / "provider", basis, model)
    sources_dir = Path(ga or particulars).resolve().parent
    result = interpret(reading, out / "request", sources_dir)
    result["case_id"] = case_id or out.name
    images = len(json.loads((out / "request" / "request.json").read_text())["images"])
    result["passes"] = {"coarse": {"requests": result["usage"]["requests"], "images": images}}
    if fine and ga is not None and reading.get("reply") is not None:
        readings = []

        def call(request_dir: Path, provider_dir: Path) -> dict:
            readings.append(call_model(binary, request_dir, provider_dir, basis, model))
            return readings[-1]

        # The coarse request is one of the ship's requests; the fine pass gets the rest.
        stats = fine_pass(result, Path(ga).resolve(), out / "fine", call, max_requests - 1)
        for fine_reading in readings:
            result["usage"] = add_usage(result["usage"], usage_of(fine_reading))
        result["passes"]["fine"] = stats
    if reading.get("reply") is not None:
        dropped: list = []
        result["passes"]["fragments_dropped"] = drop_fragments(result, dropped)
        fine_stats = result["passes"].get("fine") or {}
        left = max_requests - 1 - fine_stats.get("requests", 0)
        crops_path = out / "fine" / "crops.json"
        if fine and ga is not None and left > 0 and crops_path.exists():
            # Labels dropped as cut are read once more from wider crops, only with the requests
            # the ship has left (the ceiling and the exam budget are unchanged).
            reread_readings = []

            def reread_call(request_dir: Path, provider_dir: Path) -> dict:
                reread_readings.append(call_model(binary, request_dir, provider_dir, basis, model))
                return reread_readings[-1]

            from .ga_labels import reread_cut_labels
            stats = reread_cut_labels(result, dropped, Path(ga).resolve(), out / "reread", reread_call, left,
                                      json.loads(crops_path.read_text())["crops"])
            for extra in reread_readings:
                result["usage"] = add_usage(result["usage"], usage_of(extra))
            result["passes"]["reread"] = stats
            if stats["requests"]:
                result["passes"]["fragments_dropped"] += drop_fragments(result)
    if measure and ga is not None and reading.get("reply") is not None:
        measure_one(result, Path(ga).resolve(), out, binary, basis, model, case_id or out.name)
    write_json(out / "ga_reading.json", result)
    if app_task:
        write_app_run(result, sources_dir, app_task, out.name)
    return result


def measure_one(result: dict, ga: Path, out: Path, binary: Path, basis: str, model: str, case_id: str) -> dict:
    """The frame-scale pass on a reading: ``frames``, ``measured`` and space extents (up to seven requests).

    Measured values are kept apart from the printed particulars; ``out/ga_arrangement_input.json``
    is the file for the arrangement step (see ``ga_scale``).
    """
    from . import ga_scale
    from .ga_scale_arrangement import arrangement_input
    readings = []
    result["case_id"] = case_id

    def call(request_dir: Path, provider_dir: Path) -> dict:
        readings.append(call_model(binary, request_dir, provider_dir, basis, model))
        return readings[-1]

    result.setdefault("passes", {})["scale"] = ga_scale.scale_pass(result, ga, Path(out) / "scale", call)
    for reading in readings:
        result["usage"] = add_usage(result["usage"], usage_of(reading))
    write_json(Path(out) / "ga_arrangement_input.json", arrangement_input(result, case_id))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
