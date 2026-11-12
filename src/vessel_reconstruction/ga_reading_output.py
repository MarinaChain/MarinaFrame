"""Commercial GA reading output."""
from __future__ import annotations

from .provenance import write_json
from PIL import Image
from pathlib import Path


# ------------------------------------------------------------------ app run folder

def write_app_run(result: dict, sources_dir: Path, task: Path, name: str) -> Path:
    """A run folder the desktop app opens: the GA page, the reading, no 3D model."""
    import shutil
    task = Path(task)
    (task / "ga_reading").mkdir(parents=True, exist_ok=False)
    (task / "domain").mkdir()
    ga = (result["sources"].get("ga") or result["sources"]["particulars"])["file"]
    shutil.copy2(Path(sources_dir) / ga, task / "ga_reading" / ga)
    if "particulars" in result["sources"] and "ga" in result["sources"]:
        shutil.copy2(Path(sources_dir) / result["sources"]["particulars"]["file"], task / "ga_reading")
    write_json(task / "ga_reading" / "ga_reading.json", result)
    write_json(task / "domain" / "state.json", {"inspection_artifacts": [
        {"kind": "source_page", "path": f"ga_reading/{ga}"}]})
    write_json(task / "state.json", {"state": {
        "task_id": name, "status": "awaiting_human_review", "kind": "ga_reading", "engineering_approved": False,
        "config": {"source_spec": f"/{name}/spec.json", "policy": "deterministic", "model": result.get("model")}}})
    return task


def overlay(result: dict, sources_dir: Path, out_png: Path) -> None:
    """Draw every read (blue) and guessed (orange) box on the GA sheet, for visual checks."""
    from PIL import ImageDraw
    ga = (result["sources"].get("ga") or result["sources"]["particulars"])["file"]
    canvas = Image.open(Path(sources_dir) / ga).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    records = [(s["label"] or s["kind"], s["source_record"]) for s in result["spaces"]]
    records += [(f"{k}={v['value']}", v["source_record"]) for k, v in result["particulars"].items()
                if v.get("source_record", {}).get("kind") == "read"]
    for label, record in records:
        colour = (0, 90, 255) if record["kind"] == "read" else (255, 140, 0)
        for region in record.get("regions") or record.get("inputs") or []:
            if region.get("sheet") == ga and region.get("box_px"):
                draw.rectangle(region["box_px"], outline=colour, width=3)
                draw.text((region["box_px"][0], region["box_px"][3] + 2), label[:24], fill=colour)
    canvas.save(out_png)
