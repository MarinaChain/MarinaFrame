#!/usr/bin/env python3
"""Build the static, read-only web demo of MarinaFrame (docs/WEB_DEMO.md).

    .venv/bin/python scripts/build_web_demo.py --runs <runs folder>

Steps:
1. Stage app/ui by the desktop release rules (app/core/src/release_ui.rs, through the
   exporter's --stage-ui mode) into build/web-demo/, add the static backend
   (app/ui/static/backend.js) and switch index.html to it with a web CSP.
   The demo's pages in app/ui/static (the pilot proposal) come along.
2. Export the runs named in scripts/web_demo_runs.json with the app's own backend
   (app/core/examples/web_demo_export.rs) into build/web-demo/data/.
3. Refuse the bundle when a run is not listed with an allowed licence, when a drawing is not
   one of the listed public sheets, when any name looks like holdout truth, sealed or
   licensed data, when a local path is left in the data, or when it is over the size budget.
4. Downscale drawing images to MAX_IMAGE_EDGE_PX on the long edge (the original size is kept
   in the manifest) and write data/manifest.json.

The same runs and the same commit give the same bytes. Output: build/web-demo/ (git-ignored),
ready for any static web server at "/". Needs Pillow (the repository .venv has it).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
SELECTION = REPO / "scripts" / "web_demo_runs.json"
# The static backend and the demo's own pages (app/ui/static: .js, .html, .css only).
STATIC_FOLDER = REPO / "app" / "ui" / "static"
STATIC_SUFFIXES = {".js", ".html", ".css"}
EXPORTER = REPO / "target" / "release" / "examples" / "web_demo_export"
DEFAULT_OUT = REPO / "build" / "web-demo"

# Licences a demo run may carry. Anything else fails the build.
ALLOWED_LICENCES = {
    "public-domain-us-government",  # HAER drawings, Library of Congress
    "mit",  # DTMB 5415 surface (mathLab/WaveBEMapp-DTMB-5415)
    # Series 60 example hull of the FreeCAD Ship workbench (s60.fcstd License property CC-BY 3.0;
    # attribution is shown with the run, from its "source" text).
    "cc-by-3.0",
    "synthetic",  # the built-in sample hull and generated drawings of the above
    "generated-example",  # a concept-preview run: vessel and drawings made for the demo (concept runs only)
    # Licence not confirmed; the owner of MarinaFrame approved showing it on the demo site
    # (2026-11-11: R/V Gunnerus, MiDShip development cases). Never committed to git.
    "owner-approved-display",
}
# Name parts that mark data the demo must never carry: holdout or benchmark truth, sealed
# sets and benchmark scores. Checked against slugs, every file in the bundle and every source name.
FORBIDDEN_NAME_PARTS = ("truth", "holdout_value", "sealed", "score")
# The run views never mention truth data; a JSON file that does carries benchmark data.
TRUTH_TEXT = re.compile(r"truth", re.IGNORECASE)
# A local path of the computer that built the runs (the exporter replaces the run folder).
LOCAL_PATH = re.compile(r"/(Users|home|private|tmp|var/folders|Volumes)/")
# Source kinds that are written by the app itself (spec inputs), not drawings someone gave.
GENERATED_SOURCE_KINDS = {"spec"}
# Long edge of a drawing image in the demo. The app's own full preview is 4096 px; a web page
# does not need more and the HAER scans are 10 000 px and more.
MAX_IMAGE_EDGE_PX = 4000
# Size budget of the whole bundle (UI and data).
MAX_BUNDLE_BYTES = 300 * 1024 * 1024
# The Content-Security-Policy of the web page. The desktop page also allows the Tauri IPC
# origins; the demo needs only its own files. docs/WEB_DEMO.md repeats it as a header.
WEB_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; font-src 'self'; "
    "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'"
)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


class BuildError(Exception):
    """A reason the bundle may not be published."""


def run(command: list[str]) -> None:
    result = subprocess.run(command, cwd=REPO, capture_output=True, text=True)
    if result.returncode != 0:
        raise BuildError(f"{' '.join(command[:3])} failed:\n{result.stderr.strip()}")


def load_selection(path: Path) -> list[dict]:
    runs = json.loads(path.read_text())["runs"]
    slugs = [entry["slug"] for entry in runs]
    if len(set(slugs)) != len(slugs):
        raise BuildError("scripts/web_demo_runs.json names a run twice")
    for entry in runs:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", entry["slug"]):
            raise BuildError(f"{entry['slug']}: a slug is letters, digits and '-'")
        if entry.get("licence") not in ALLOWED_LICENCES:
            raise BuildError(f"{entry['slug']}: licence {entry.get('licence')!r} is not allowed in the demo")
        # A made-up vessel is shown only with its concept-preview label, and only a made-up
        # vessel is labelled so: the two always go together.
        if (entry.get("licence") == "generated-example") != (entry.get("concept") is True):
            raise BuildError(f"{entry['slug']}: 'generated-example' goes with \"concept\": true, and only with it")
        check_name(entry["slug"], "run")
    return runs


def check_name(name: str, what: str) -> None:
    lowered = name.lower()
    for part in FORBIDDEN_NAME_PARTS:
        if part in lowered:
            raise BuildError(f"{what} {name!r} looks like {part} data, which the demo never carries")


def stage_ui(out: Path) -> None:
    """The desktop release UI, the static backend and an index.html that selects it."""
    run([str(EXPORTER), "--stage-ui", str(REPO / "app" / "ui"), str(out)])
    (out / "static").mkdir()
    for path in sorted(STATIC_FOLDER.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix not in STATIC_SUFFIXES:
            raise BuildError(f"app/ui/static/{path.name}: only .js, .html and .css files belong there")
        shutil.copyfile(path, out / "static" / path.name)
    index = out / "index.html"
    html = index.read_text()
    html, csp_count = re.subn(
        r'<meta http-equiv="Content-Security-Policy" content="[^"]*">',
        f'<meta http-equiv="Content-Security-Policy" content="{WEB_CSP}">',
        html,
    )
    marker = "<!-- For the web build, add: <meta name=\"marinaframe-backend\" content=\"http\"> -->"
    if csp_count != 1 or marker not in html:
        raise BuildError("app/ui/index.html changed: update stage_ui in scripts/build_web_demo.py")
    html = html.replace(marker, '<meta name="marinaframe-backend" content="static">')
    index.write_text(html)


def export_runs(runs_folder: Path, data: Path, selection: list[dict], worker_python: str, config: Path | None) -> None:
    """Export every listed run. A run may name its own runs folder ("runs_folder", relative to
    --runs), for example a concept run made by another lane; data/tasks.json lists them all."""
    reviewed = ["--config", str(config)] if config else []
    folders: dict[Path, list[str]] = {}
    for entry in selection:
        folder = (runs_folder / entry.get("runs_folder", ".")).resolve()
        folders.setdefault(folder, []).append(entry["slug"])
    summaries = []
    for folder, slugs in folders.items():
        run([
            str(EXPORTER), "--runs", str(folder), "--out", str(data),
            "--worker-python", worker_python, "--worker-source", str(REPO / "src"), *reviewed, *slugs,
        ])
        summaries += json.loads((data / "tasks.json").read_text())
    (data / "tasks.json").write_text(json.dumps(summaries, indent=2) + "\n")


def check_sources(data: Path, entry: dict) -> list[dict]:
    """Every drawing of the run is one of the listed public sheets; returns the sources."""
    sources = json.loads((data / "runs" / entry["slug"] / "sources.json").read_text())["sources"]
    allowed = set(entry.get("drawing_sha256", []))
    for source in sources:
        check_name(source["name"], f"{entry['slug']}: source")
        if source["kind"] in GENERATED_SOURCE_KINDS:
            continue
        if source.get("sha256") not in allowed:
            raise BuildError(
                f"{entry['slug']}: source {source['name']} (sha256 {source.get('sha256')}) is not a listed public sheet"
            )
    return sources


def check_files(out: Path) -> int:
    """Names, local paths and total size of the bundle. Returns its size in bytes."""
    total = 0
    for path in sorted(out.rglob("*")):
        if path.is_symlink():
            raise BuildError(f"{path.relative_to(out)}: links are not published")
        if not path.is_file():
            continue
        relative = path.relative_to(out).as_posix()
        check_name(relative, "file")
        if path.suffix == ".json":
            text = path.read_text(errors="replace")
            if LOCAL_PATH.search(text):
                raise BuildError(f"{relative}: names a local path of this computer")
            if TRUTH_TEXT.search(text):
                raise BuildError(f"{relative}: mentions truth data, which the demo never carries")
        total += path.stat().st_size
    if total > MAX_BUNDLE_BYTES:
        raise BuildError(f"bundle is {total / 1e6:.1f} MB, over the {MAX_BUNDLE_BYTES / 1e6:.0f} MB budget")
    return total


def downscale_images(run_dir: Path) -> list[dict]:
    """Shrink large page images in place; returns what was shrunk, with the original size."""
    changed = []
    for path in sorted(run_dir.rglob("*")):
        if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
            continue
        with Image.open(path) as image:
            width, height = image.size
            if max(width, height) <= MAX_IMAGE_EDGE_PX:
                continue
            scale = MAX_IMAGE_EDGE_PX / max(width, height)
            shown = (max(1, round(width * scale)), max(1, round(height * scale)))
            resized = image.resize(shown, Image.Resampling.LANCZOS)
            resized.save(path, format=image.format, optimize=True)
        changed.append({
            "file": path.relative_to(run_dir).as_posix(),
            "original_px": [width, height],
            "shown_px": list(shown),
        })
    return changed


EXPORT_FILE = re.compile(r"^(?P<stem>.+?)(?P<rest>_r\d{4}_DRAFT.*)$")


def rename_run(run_dir: Path, original_name: str, entry: dict) -> None:
    """Show the run under its listed name: in its JSON, and (with "file_stem") in the names of
    its export files, which the app makes from the run's own name. The name gates then check
    the renamed files."""
    renames = {}
    stem = entry.get("file_stem")
    if stem:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", stem):
            raise BuildError(f"{entry['slug']}: a file_stem is letters, digits and '-'")
        for export in sorted(run_dir.glob("exports/*/*")):
            match = EXPORT_FILE.match(export.name)
            if match:
                renames[export.name] = stem + match["rest"]
                export.rename(export.with_name(renames[export.name]))
    # JSON for the app; CSV and STEP (plain text, no byte offsets) exports for download.
    for path in sorted([*run_dir.rglob("*.json"), *run_dir.rglob("*.csv"), *run_dir.rglob("*.step")]):
        text = path.read_text(errors="replace")
        changed = text.replace(original_name, entry["name"]) if original_name else text
        for old, new in renames.items():
            changed = changed.replace(old, new)
        if changed != text:
            path.write_text(changed)


def write_manifest(data: Path, selection: list[dict], downscaled: dict[str, list[dict]]) -> None:
    summaries = {summary["task"].rsplit("/", 1)[-1]: summary for summary in json.loads((data / "tasks.json").read_text())}
    (data / "tasks.json").unlink()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    runs = []
    for entry in selection:
        slug = entry["slug"]
        summary = summaries[slug]
        # The listed name replaces the run folder name in the list and in the run view.
        summary["name"] = entry["name"]
        task_file = data / "runs" / slug / "task.json"
        view = json.loads(task_file.read_text())
        view["summary"]["name"] = entry["name"]
        task_file.write_text(json.dumps(view, indent=2, sort_keys=True) + "\n")
        runs.append({
            "slug": slug,
            "name": entry["name"],
            "licence": entry["licence"],
            "source": entry["source"],
            "tagline": entry.get("tagline"),
            "concept": entry.get("concept") is True,
            "credit": entry.get("credit"),
            "note": entry.get("note"),
            "whole_vessel_first": entry.get("whole_vessel_first") is True,
            "section_lines": entry.get("section_lines") is not False,
            "summary": summary,
            "downscaled_images": downscaled[slug],
        })
    manifest = {
        "format": 1,
        "read_only": True,
        "built_from_commit": commit,
        "max_image_edge_px": MAX_IMAGE_EDGE_PX,
        "engineering_approved": False,
        "runs": runs,
    }
    (data / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def build(runs_folder: Path, out: Path, selection_path: Path, worker_python: str, config: Path | None, skip_cargo: bool) -> int:
    selection = load_selection(selection_path)
    if not skip_cargo:
        run(["cargo", "build", "--release", "--locked", "-p", "marinaframe-app-core", "--example", "web_demo_export"])
    if out.exists():
        shutil.rmtree(out)
    stage_ui(out)
    data = out / "data"
    export_runs(runs_folder, data, selection, worker_python, config)
    downscaled = {}
    original_names = {
        summary["task"].rsplit("/", 1)[-1]: summary["name"] for summary in json.loads((data / "tasks.json").read_text())
    }
    for entry in selection:
        rename_run(data / "runs" / entry["slug"], original_names.get(entry["slug"], ""), entry)
        check_sources(data, entry)
        downscaled[entry["slug"]] = downscale_images(data / "runs" / entry["slug"])
    write_manifest(data, selection, downscaled)
    return check_files(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", required=True, type=Path, help="runs folder holding the selected run folders")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--selection", type=Path, default=SELECTION)
    parser.add_argument("--worker-python", default=sys.executable, help="Python of the CAD worker (renders PDF/TIFF pages)")
    parser.add_argument("--config", type=Path, help="app config folder the runs were reviewed with (part reviews, sign-off)")
    parser.add_argument("--skip-cargo", action="store_true", help="use the exporter already built")
    args = parser.parse_args()
    try:
        size = build(args.runs.resolve(), args.out.resolve(), args.selection, args.worker_python, args.config, args.skip_cargo)
    except BuildError as error:
        print(f"build_web_demo: {error}", file=sys.stderr)
        if args.out.exists():
            shutil.rmtree(args.out)
        return 1
    print(f"build_web_demo: {args.out} ({size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
