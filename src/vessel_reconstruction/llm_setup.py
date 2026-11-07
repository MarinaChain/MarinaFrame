"""Evidence-bound sheet setup. Python checks pixels; only Rust calls the provider.

Run: python -m vessel_reconstruction.llm_setup run --source SHEET --out NEW_DIR
     --binary target/release/marinaframe --provider-transfer-basis TEXT

A consistent proposal is not proof of text or hull-line identity. A setup is not
an engineering approval. This module does not invent longitudinal positions,
closure assumptions, or elevation ranges when the sheet does not print them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# The default Pillow font has proportional figures; use it only for ruler labels.

SCALE_RELATIVE_TOLERANCE = 0.05
LINE_SUPPORT_MIN = 0.55
INK_THRESHOLD = 150
RULER_MARGIN = 36
MAX_IMAGE_PIXELS = 900_000
MAX_IMAGE_SIDE = 2000
UNIT_METRES = {"m": 1.0, "mm": 0.001, "ft": 0.3048, "ft_in": 0.3048}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def seen(reading):
    if not isinstance(reading, dict) or not str(reading.get("evidence", "")).strip():
        return None
    return reading.get("value")


def field(value, checked: bool, evidence=None, **details):
    return {"value": value, "model_proposed": True, "checked": bool(checked),
            "evidence": evidence, **details}


def _support(ink, box, coordinate, vertical):
    if coordinate is None or not isinstance(coordinate, (int, float)) or not math.isfinite(coordinate):
        return 0.0
    left, top, right, bottom = map(int, box)
    at = round(coordinate)
    if vertical:
        if not left <= at < right:
            return 0.0
        strip = ink[top:bottom, max(left, at - 2):min(right, at + 3)]
        return float(strip.any(axis=1).mean()) if strip.size else 0.0
    if not top <= at < bottom:
        return 0.0
    strip = ink[max(top, at - 2):min(bottom, at + 3), left:right]
    return float(strip.any(axis=0).mean()) if strip.size else 0.0


def _scale(mark, centre, baseline):
    value = mark.get("value")
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value == 0:
        return None
    kind = mark.get("kind")
    if kind == "waterline_label" and baseline is not None:
        distance = abs(baseline - mark["y_px"])
        identity = (kind, round(mark["y_px"], 1))
    elif kind == "buttock_label" and centre is not None:
        distance = abs(mark["x_px"] - centre)
        identity = (kind, round(mark["x_px"], 1))
    elif kind in {"scale_bar", "dimension"}:
        distance = math.hypot(mark["x2_px"] - mark["x_px"], mark["y2_px"] - mark["y_px"])
        identity = ("span", *sorted([(round(mark["x_px"], 1), round(mark["y_px"], 1)),
                                     (round(mark["x2_px"], 1), round(mark["y2_px"], 1))]))
    else:
        return None
    return distance / abs(value), identity


def check_setup(image: Image.Image, overview: dict, panels: dict) -> dict:
    """Cross-check a proposal without filling any absent model value.

    Scale agreement is 5% relative to the mean, with distinct physical marks.
    Axes need ink within two pixels along at least 55% of the declared panel.
    Station label evidence must contain the label; numeric labels and positions
    must both strictly increase in the model's reading order.
    """
    ink = np.asarray(image.convert("L")) < INK_THRESHOLD
    failures = []
    result = {"schema_version": "marinaframe.setup_checks.v1", "engineering_approved": False,
              "panels": {}, "values": {}, "failures": failures,
              "scale_relative_tolerance": SCALE_RELATIVE_TOLERANCE}

    def fail(kind, name):
        failures.append({"kind": kind, "field": name})

    for name in ["layout", "units", "symmetry", "vertical_datum"]:
        reading = overview.get(name)
        value = seen(reading)
        if value is None:
            fail(f"{name}_missing", name)
        result["values"][name] = field(value, value is not None, reading,
                                      check="bounded model evidence; semantic truth needs human review")
    units = seen(overview.get("units"))
    if units is not None and units not in UNIT_METRES:
        fail("units_unsupported", "units")
    stations = overview.get("stations", [])
    if not stations:
        fail("stations_missing", "stations")
    previous_position = previous_label = None
    for index, station in enumerate(stations):
        name = f"stations[{index}]"
        if station.get("panel_id") not in {p["panel_id"] for p in overview.get("panels", [])}:
            fail("station_panel_missing", name)
        label = station.get("label", "")
        evidence = station.get("evidence", "")
        if not label or not re.search(r"(?<![\w.])" + re.escape(label) + r"(?![\w.])", evidence):
            fail("station_label_evidence", name)
        position = seen(station.get("position"))
        if position is None:
            fail("station_position_missing", name)
        elif not isinstance(position, (int, float)) or not math.isfinite(position):
            fail("station_position_invalid", name)
        else:
            if previous_position is not None and position <= previous_position:
                fail("station_order", name)
            previous_position = position
        numeric = re.fullmatch(r"(?:No\.?\s*)?([0-9]+(?:\.[0-9]+)?)", label)
        if numeric:
            number = float(numeric.group(1))
            if previous_label is not None and number <= previous_label:
                fail("station_label_order", name)
            previous_label = number
    result["values"]["stations"] = field(stations, not any(f["field"].startswith("stations") for f in failures),
                                              check="printed-label evidence and strict order; no OCR truth claim")
    boxes = overview.get("panels", [])
    if not boxes:
        fail("panels_missing", "panels")
    for entry in boxes:
        panel_id = entry["panel_id"]
        box = entry["box_px"]
        left, top, right, bottom = box
        valid_box = (all(isinstance(v, (int, float)) and math.isfinite(v) for v in box)
                     and 0 <= left < right <= image.width and 0 <= top < bottom <= image.height)
        if not valid_box:
            fail("panel_outside_sheet", panel_id)
            continue
        crop = ink[int(top):int(bottom), int(left):int(right)]
        has_ink = crop.size > 0 and float(crop.mean()) >= 0.002
        if not has_ink:
            fail("panel_no_ink", panel_id)
        output = {"box_px": field(box, has_ink, entry.get("evidence"))}
        result["panels"][panel_id] = output
        proposal = panels.get(panel_id, {})
        centre = seen(proposal.get("centreline_x_px"))
        baseline = seen(proposal.get("baseline_y_px"))
        for name, value, vertical, code in [("centreline_x_px", centre, True, "centreline_not_on_ink"),
                                            ("baseline_y_px", baseline, False, "baseline_not_on_ink")]:
            support = _support(ink, box, value, vertical)
            checked = support >= LINE_SUPPORT_MIN
            if not checked:
                fail(code, panel_id)
            output[name] = field(value, checked, proposal.get(name), line_support=support)
        measurements = []
        identities = set()
        for mark in proposal.get("scale_marks", []):
            if not mark.get("evidence") or not mark.get("text"):
                continue
            tokens = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", mark["text"])
            if len(tokens) != 1 or float(tokens[0]) != mark.get("value"):
                fail("scale_mark_text_mismatch", panel_id)
                continue
            kind = mark.get("kind")
            line_support = 1.0
            if kind == "waterline_label":
                line_support = _support(ink, box, mark["y_px"], False)
            elif kind == "buttock_label":
                line_support = _support(ink, box, mark["x_px"], True)
            if line_support < LINE_SUPPORT_MIN:
                fail("scale_mark_not_on_ink", panel_id)
                continue
            calculated = _scale(mark, centre, baseline)
            if calculated is None:
                continue
            scale, identity = calculated
            if identity in identities or scale <= 0:
                continue
            identities.add(identity)
            measurements.append(scale)
        enough = len(measurements) >= 2
        if not enough:
            fail("scale_independent_marks_missing", panel_id)
        mean = float(np.mean(measurements)) if measurements else None
        agreement = enough and max(abs(v - mean) / mean for v in measurements) <= SCALE_RELATIVE_TOLERANCE
        if enough and not agreement:
            fail("scale_marks_disagree", panel_id)
        ppm = mean / UNIT_METRES[units] if mean is not None and units in UNIT_METRES else None
        output["pixels_per_metre"] = field(ppm, agreement and ppm is not None,
                                            proposal.get("scale_marks", []), independent_scales=measurements)
    result["consistent"] = not failures
    result["spec_ready"] = False
    result["spec_blockers"] = ["Source license, elevation intervals and closure assumptions require explicit input.",
                               "Semantic text evidence is model-proposed, not independently transcribed."]
    return result


def prepare_request(source: Path, out: Path, view="sheet_overview", box=None, feedback=None):
    """Write a bounded image with an explicit normalized-to-source transform."""
    out.mkdir(parents=True, exist_ok=False)
    with Image.open(source) as opened:
        original = opened.convert("RGB")
    box = box or [0, 0, original.width, original.height]
    left, top, right, bottom = map(int, box)
    box = [left, top, right, bottom]
    if not 0 <= left < right <= original.width or not 0 <= top < bottom <= original.height:
        raise ValueError("Crop outside source")
    crop = original.crop((left, top, right, bottom))
    ratio = min(1.0, 1800 / max(crop.size), (700_000 / (crop.width * crop.height)) ** 0.5)
    crop = crop.resize((max(1, round(crop.width * ratio)), max(1, round(crop.height * ratio))))
    canvas = Image.new("RGB", (crop.width + 2 * RULER_MARGIN, crop.height + 2 * RULER_MARGIN), "white")
    canvas.paste(crop, (RULER_MARGIN, RULER_MARGIN))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=12)
    step = max(20, int(100 / ratio / 20) * 20)
    for x in range(math.ceil(left / step) * step, right, step):
        at = RULER_MARGIN + (x - left) * ratio
        draw.line((at, RULER_MARGIN - 5, at, RULER_MARGIN), fill="red")
        draw.text((at - 10, 5), str(x), fill="red", font=font)
    for y in range(math.ceil(top / step) * step, bottom, step):
        at = RULER_MARGIN + (y - top) * ratio
        draw.line((RULER_MARGIN - 5, at, RULER_MARGIN, at), fill="red")
        draw.text((1, at), str(y), fill="red", font=font)
    path = out / "image.png"
    canvas.quantize(colors=64).save(path, optimize=True)
    manifest = {"schema_version": "marinaframe.vision_request.v1", "purpose": "sheet_setup",
                "source_sha256": digest(source), "engineering_approved": False,
                "context": {"source_size_px": list(original.size), "crop_box_px": box,
                            "rulers": "Red margin numbers are source references, NOT response coordinates.",
                            "coordinate_frame": "normalized_attachment_1000",
                            "coordinate_transform": {"image_size_px": list(canvas.size),
                                "content_size_px": list(crop.size), "margin_px": RULER_MARGIN,
                                "crop_box_px": box},
                            "feedback": feedback or []},
                "images": [{"image_id": "setup", "file": "image.png", "sha256": digest(path),
                            "bytes": path.stat().st_size, "width": canvas.width, "height": canvas.height,
                            "view": view, "crop_box_px": box}]}
    write_json(out / "request.json", manifest)
    return manifest


def source_coordinates(reply: dict, manifest: dict) -> dict:
    """Map normalized attachment coordinates; retain raw readings separately.

    Use actual rounded dimensions on each axis, not the nominal resize ratio.
    Normalized edges are defined against width/height (not width-1/height-1).
    """
    from copy import deepcopy
    result = deepcopy(reply)
    transform = manifest["context"]["coordinate_transform"]
    width, height = transform["image_size_px"]
    content_width, content_height = transform["content_size_px"]
    left, top, right, bottom = transform["crop_box_px"]
    margin = transform["margin_px"]

    def coordinate(value, axis):
        size, content, start, end = ((width, content_width, left, right) if axis == 0
                                     else (height, content_height, top, bottom))
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1000:
            raise ValueError("Setup coordinate outside normalized attachment")
        return (value * size / 1000 - margin) * (end - start) / content + start

    for panel in result.get("panels", []):
        panel["box_px"] = [coordinate(v, i % 2) for i, v in enumerate(panel["box_px"])]
    for item in result.get("stations", []) + result.get("scale_marks", []):
        for key, axis in [("x_px", 0), ("y_px", 1), ("x2_px", 0), ("y2_px", 1)]:
            if key in item:
                item[key] = coordinate(item[key], axis)
    for key, axis in [("centreline_x_px", 0), ("baseline_y_px", 1)]:
        if "value" in result.get(key, {}):
            result[key]["value"] = coordinate(result[key]["value"], axis)
    return result


class Progress:
    """Stop after two consecutive checks without fewer blocking failures."""
    def __init__(self):
        self.best = None
        self.stalled = 0

    def stop(self, failures):
        count = len(failures)
        if self.best is None or count < self.best:
            self.best, self.stalled = count, 0
        else:
            self.stalled += 1
        return self.stalled >= 1


def overlay(source: Path, overview: dict, panels: dict, out: Path):
    with Image.open(source) as opened:
        image = opened.convert("RGB")
    draw = ImageDraw.Draw(image)
    for entry in overview.get("panels", []):
        box = entry["box_px"]
        draw.rectangle(box, outline="blue", width=3)
        panel = panels.get(entry["panel_id"], {})
        centre = seen(panel.get("centreline_x_px"))
        base = seen(panel.get("baseline_y_px"))
        if centre is not None:
            draw.line((centre, box[1], centre, box[3]), fill="magenta", width=2)
        if base is not None:
            draw.line((box[0], base, box[2], base), fill="green", width=2)
    image.thumbnail((1800, 1800))
    image.save(out)


def run_setup(source: Path, out: Path, binary: Path, basis: str):
    source, out, binary = source.resolve(), out.resolve(), binary.resolve()
    out.mkdir(parents=True, exist_ok=False)
    records, panels, overview = [], {}, {}
    progress = Progress()
    feedback = []
    round_index = 0

    def ask(view, box=None):
        nonlocal round_index
        name = f"request-{len(list(out.glob('request-*'))):04d}"
        manifest = prepare_request(source, out / name, view, box, feedback)
        answer = out / f"reading-{len(records):04d}"
        completed = subprocess.run([str(binary), "vision-request", "--request", str(out / name),
                                    "--out", str(answer), "--provider-transfer-basis", basis],
                                   capture_output=True, text=True, timeout=240)
        if completed.returncode:
            raise RuntimeError("Rust vision request failed: " + completed.stderr[:500])
        record = json.loads((answer / "vision_reading.json").read_text())
        records.append(record)
        write_json(out / "readings.json", records)
        if record.get("reply") is None:
            return None
        try:
            return source_coordinates(next(iter(record["reply"].values())), manifest)
        except ValueError as error:
            write_json(answer / "coordinate_rejection.json", {"error": str(error),
                "coordinate_frame": manifest["context"]["coordinate_frame"],
                "engineering_approved": False})
            return None

    while True:
        overview = ask("sheet_overview")
        if overview is None:
            report = {"failures": [{"kind": "provider_no_reply", "field": "overview"}], "spec_ready": False}
            break
        panels = {}
        for entry in overview.get("panels", []):
            try:
                answer = ask("panel:" + entry["panel_id"], entry["box_px"])
            except ValueError:
                answer = None
            if answer is not None:
                panels[entry["panel_id"]] = answer
        with Image.open(source) as image:
            report = check_setup(image, overview, panels)
        write_json(out / "proposal.json", {"source_sha256": digest(source), "overview": overview, "panels": panels})
        write_json(out / "checks.json", report)
        overlay(source, overview, panels, out / "overlay.png")
        if not report["failures"]:
            break
        if progress.stop(report["failures"]):
            report["stop_reason"] = "no_progress"
            break
        feedback = report["failures"]
        round_index += 1
    report["engineering_approved"] = False
    report["source_sha256"] = digest(source)
    report["usage"] = {key: sum(record.get("usage", {}).get(key, 0) for record in records)
                       for key in {k for record in records for k in record.get("usage", {})}}
    write_json(out / "checks.json", report)
    return report


def make_spec(template: dict, overview: dict, checks: dict, base_dir: Path):
    """Fill a human template only after all setup checks pass.

    The template must supply rights, closure and visible elevation extents. The
    companion provenance record, not unknown schema fields, records model origin.
    """
    from copy import deepcopy
    from .schema import validate_spec
    if checks.get("failures") or not checks.get("consistent"):
        raise ValueError("Cannot publish unchecked setup")
    if seen(overview.get("layout")) != "separate_panels":
        raise ValueError("Overlaid station assignment needs explicit line identity")
    spec = deepcopy(template)
    stations = overview["stations"]
    if len(spec.get("sections", [])) != len(stations):
        raise ValueError("Template sections must match station labels")
    factor = UNIT_METRES[seen(overview["units"])]
    for section, station in zip(spec["sections"], stations):
        if section.get("id") != station["label"]:
            raise ValueError("Template station label mismatch")
        panel = checks["panels"][station["panel_id"]]
        if not all(panel[k]["checked"] for k in ["box_px", "centreline_x_px", "baseline_y_px", "pixels_per_metre"]):
            raise ValueError("Cannot publish unchecked panel")
        section["x_m"] = seen(station["position"]) * factor
        section["roi_px"] = [int(v) for v in panel["box_px"]["value"]]
        section["calibration"] = {"centerline_px": panel["centreline_x_px"]["value"],
                                  "baseline_px": panel["baseline_y_px"]["value"],
                                  "pixels_per_metre": panel["pixels_per_metre"]["value"]}
    spec["units"] = "m"
    spec["symmetry"] = seen(overview["symmetry"])
    spec["symmetry_evidence"] = overview["symmetry"]["evidence"]
    errors = validate_spec(spec, base_dir)
    if errors:
        raise ValueError("Setup template fails source specification checks: " + str(errors))
    provenance = {"schema_version": "marinaframe.setup_spec.v1", "engineering_approved": False,
                  "setup_values": checks, "template_fields": ["source", "end_closure", "z_min_m", "z_max_m"],
                  "semantic_review_required": True}
    return spec, provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--source", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--binary", type=Path, required=True)
    run.add_argument("--provider-transfer-basis", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--view", default="sheet_overview")
    prepare.add_argument("--box", nargs=4, type=int)
    check = sub.add_parser("check")
    check.add_argument("--source", type=Path, required=True)
    check.add_argument("--proposal", type=Path, required=True)
    check.add_argument("--out", type=Path, required=True)
    publish = sub.add_parser("spec")
    publish.add_argument("--source", type=Path, required=True)
    publish.add_argument("--proposal", type=Path, required=True)
    publish.add_argument("--template", type=Path, required=True)
    publish.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        result = prepare_request(args.source, args.out, args.view, args.box)
    elif args.command in {"check", "spec"}:
        proposal = json.loads(args.proposal.read_text())
        if proposal.get("source_sha256") != digest(args.source):
            raise ValueError("Proposal source hash mismatch")
        with Image.open(args.source) as image:
            result = check_setup(image, proposal["overview"], proposal["panels"])
        if args.out.exists():
            raise ValueError("Output already exists")
        args.out.mkdir(parents=True)
        if args.command == "spec":
            template = json.loads(args.template.read_text())
            spec, provenance = make_spec(template, proposal["overview"], result, args.template.parent)
            provenance["source_sha256"] = proposal["source_sha256"]
            provenance["proposal_sha256"] = digest(args.proposal)
            write_json(args.out / "spec.json", spec)
            write_json(args.out / "setup_provenance.json", provenance)
        else:
            write_json(args.out / "checks.json", result)
    else:
        result = run_setup(args.source, args.out, args.binary, args.provider_transfer_basis)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
