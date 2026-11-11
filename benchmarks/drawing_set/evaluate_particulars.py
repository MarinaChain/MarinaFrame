"""Development check of printed particulars (no sealed inputs or model requests).

    PYTHONPATH=src:. .venv/bin/python -m benchmarks.drawing_set.evaluate_particulars

The fixed sample is six Gunnerus vector sheets and five HAER scans. Readings are
checked against labels transcribed from their text, not hull geometry or derived
truth. This measures the parser on PDF words and 6000-pixel whole-page OCR;
intake's additional strip OCR is not included. Raw text/words stay in work/.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from vessel_reconstruction.particulars import FIELDS, pdf_words, read_words
from vessel_reconstruction.sheet_types import ocr_read

# All paths below are development sources used in DRAWING_SET_INTAKE.md.
PDFS = ("GA Gunnerus Rev1.pdf", "Lines Plan Rev0.pdf", "Midship Section Rev0.pdf",
        "Profile and Plan Rev0.pdf", "Shell Expansion Rev0.pdf", "Tank Plan Rev1.pdf")
SCANS = ("ca_thayer/ca_thayer_s01_title_sheet.tif", "wapama/wapama_s01_s_s_wapama_as_is_lines_2010.tif",
         "master-pnp-habshaer-ny-ny2300-ny2390-sheet-00004a.tif",
         "master-pnp-habshaer-or-or0500-or0589-sheet-00002a.tif",
         "master-pnp-habshaer-or-or0500-or0590-sheet-00002a.tif")
LABELS = {
    "Lines Plan Rev0": {"loa_m": 36.25, "lpp_m": 33.90, "beam_m": 9.60},
    "ca_thayer_s01_title_sheet": {"built_year": 1895, "builder": "Hans D. Bendixsen"},
}
OCR_SIDE = 6000


def collect(path: Path) -> dict:
    if path.suffix.lower() == ".pdf":
        import fitz
        with fitz.open(path) as document:
            page = document[0]
            full = [page.rect.width, page.rect.height]
            text = page.get_text()
        # Use a 72-dpi page so boxes are also PDF points in this parser benchmark.
        words = pdf_words(path, 0, full)
        where = "pdf_text"
    else:
        # HAER scans exceed Pillow's default image-size warning threshold.
        old_limit = Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS = None
            with Image.open(path) as opened:
                full = list(opened.size)
                picture = opened.convert("L")
                picture.thumbnail((OCR_SIDE, OCR_SIDE))
        finally:
            Image.MAX_IMAGE_PIXELS = old_limit
        words = []
        text, _ = ocr_read(np.asarray(picture), side=OCR_SIDE, words_out=words)
        sx, sy = full[0] / picture.width, full[1] / picture.height
        for word in words:
            x0, y0, x1, y1 = word["bbox"]
            word["bbox"] = [x0 * sx, y0 * sy, x1 * sx, y1 * sy]
        where = "ocr"
    return {"file": str(path), "text": text, "words": words, "text_source": where}


def run(sources: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    paths = [sources / "gunnerus/polarkonsult" / name for name in PDFS]
    paths += [sources / "haer" / name for name in SCANS]
    counts = {field: {"labelled": 0, "read": 0, "correct": 0, "wrong": 0, "missed": 0, "unlabelled": 0}
              for field in FIELDS}
    rows = []
    for path in paths:
        cache = out / (path.stem + ".json")
        data = json.loads(cache.read_text()) if cache.is_file() else collect(path)
        readings = read_words(data["words"], source={"sheet": path.stem, "file": str(path), "page_index": 0,
                                                    "text_source": data.get("text_source", "pdf_text" if path.suffix == ".pdf" else "ocr"),
                                                    "bbox_space": "page_px"})
        labels = LABELS.get(path.stem, {})
        for field in FIELDS:
            values = [r["value"] for r in readings if r["field"] == field]
            count = counts[field]
            count["read"] += len(values)
            if field in labels:
                count["labelled"] += 1
                count["missed"] += not values
                for value in values:
                    expected = labels[field]
                    equal = (math.isclose(value, expected, abs_tol=1e-6) if isinstance(expected, (int, float))
                             else value == expected)
                    count["correct" if equal else "wrong"] += 1
            else:
                count["unlabelled"] += len(values)
        data["readings"] = readings
        cache.write_text(json.dumps(data, indent=2) + "\n")
        rows.append({"file": str(path.relative_to(sources)), "labels": labels, "readings": readings})
    result = {"sheets": len(rows), "counts": counts, "rows": rows}
    (out / "evaluation.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path,
                        default=Path("/Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources"))
    parser.add_argument("--out", type=Path, default=Path("work/particulars"))
    args = parser.parse_args()
    result = run(args.sources, args.out)
    print(json.dumps({"sheets": result["sheets"], "counts": result["counts"]}, indent=2))


if __name__ == "__main__":
    main()
