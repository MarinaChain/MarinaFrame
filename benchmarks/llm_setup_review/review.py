"""Receipt model vetoes for an already rendered station manifest."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from vessel_reconstruction.llm_setup import write_json


def review(images: Path, out: Path, binary: Path, basis: str):
    manifest = json.loads((images / "manifest.json").read_text())
    out.mkdir(parents=True, exist_ok=False)
    records = []
    for index in range(0, len(manifest["images"]), 3):
        entries = manifest["images"][index:index + 3]
        request = out / f"request-{index:03d}"
        request.mkdir()
        listing = []
        for entry in entries:
            shutil.copyfile(images / entry["file"], request / entry["file"])
            listing.append({"image_id": entry["review_id"], "file": entry["file"], "sha256": entry["sha256"],
                            "bytes": entry["bytes"], "width": entry["width"], "height": entry["height"],
                            "view": "station:" + entry["review_id"], "crop_box_px": entry["crop_box_px"]})
        write_json(request / "request.json", {"schema_version": "marinaframe.vision_request.v1", "purpose": "build_review",
                   "source_sha256": manifest["source_sha256"], "engineering_approved": False,
                   "context": {"step_sha256": manifest["step_sha256"], "note": "left source; right exported STEP cut in magenta"}, "images": listing})
        reading = out / f"reading-{index:03d}"
        result = subprocess.run([str(binary.resolve()), "vision-request", "--request", str(request.resolve()),
                                 "--out", str(reading.resolve()), "--provider-transfer-basis", basis], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        records.append(json.loads((reading / "vision_reading.json").read_text()))
        write_json(out / "review.json", {"step_sha256": manifest["step_sha256"], "records": records, "engineering_approved": False})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["images", "out", "binary"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--basis", required=True)
    args = parser.parse_args()
    records = review(args.images, args.out, args.binary, args.basis)
    print(json.dumps([r["reply"] for r in records]))


if __name__ == "__main__":
    main()
