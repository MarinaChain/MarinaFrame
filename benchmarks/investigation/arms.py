"""Three-arm evaluation of model investigation (W11) on crowded drawings.

Arms, on the same captured input:
  abstain  deterministic policy, --on-ambiguity abstain
  draft    deterministic policy, --on-ambiguity draft
  llm      live DeepSeek policy, --on-ambiguity draft (investigation tools)

Subcommands:
  prepare-gunnerus --out DIR      Gunnerus raster body plan (development data), as raster_path.py
  prepare-sheet --sheet NAME --derivatives DIR --out DIR
                                  authentic HAER/ALMA sheet with assistant-read provisional
                                  calibration (docs/GEOMETRY_ACCURACY_V05.md 8.2); station
                                  sections share the declared panel
  run --arm ARM --input DIR --out DIR
                                  run the Rust controller; the llm arm loads the OpenCode keys
                                  with scripts/load_opencode_keys.sh (no key is printed)
  summarize --run DIR --input DIR [--truth DIR --metric FILE]
                                  counts, usage, overlay of every chosen line; Gunnerus score

Everything is written under the git-ignored work/ folder. Station positions on the
authentic sheets are ordinals, not metres, so their draft geometry is not meaningful;
only line identity is evaluated there, by inspection of the overlays.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT.parents[2] / "work" / "sources" if (ROOT.parents[2] / "work" / "sources").is_dir() else ROOT / "work" / "sources"
BASIS = ("Founder decision 2026-11-07 in chat: any acquired drawing may be sent to DeepSeek "
         "(docs/CONTINUATION_STATUS.md, Provider transfer decision); development and evaluation only.")

# Provisional calibration read by the assistant (GEOMETRY_ACCURACY_V05.md 8.2).
# Each station or band is one section; x_m is an ordinal.
SHEETS = {
    "s7": {"derivative": "s7.png", "sha256_prefix": "1f6c4c5cd172",
           "description": "Balclutha CA-54 sheet 7 body plan, x4 greyscale derivative",
           "panel": {"roi_px": [1200, 650, 1975, 1725], "centerline_px": 1206, "baseline_px": 1714.4,
                     "pixels_per_metre": 122.87, "z": [0.0, 8.5344]},
           "stations": [(f"st{n}", float(n), "panel") for n in range(11, 21)]},
    "wapama": {"derivative": "wapama.png", "sha256_prefix": "7f0defdb91ac",
               "description": "Wapama CA-67 sheet 5 as-is body plans (port half), x4 greyscale derivative",
               "panel": {"roi_px": [1690, 1300, 2720, 2172], "centerline_px": 1699.5, "baseline_px": 2162.5,
                         "pixels_per_metre": 164.04, "z": [0.0, 5.1816]},
               "panel2": {"roi_px": [1690, 2800, 2720, 3672], "centerline_px": 1699.5, "baseline_px": 3662.5,
                          "pixels_per_metre": 164.04, "z": [0.0, 5.1816]},
               "stations": [("st0.5", 0.5, "panel"), ("st1", 1.0, "panel"), ("st1.5", 1.5, "panel"),
                            ("st2", 2.0, "panel"), ("st3", 3.0, "panel"), ("st4", 4.0, "panel"),
                            ("st5", 5.0, "panel"), ("st6", 6.0, "panel2"), ("st7", 7.0, "panel2"),
                            ("st8", 8.0, "panel2"), ("st8.5", 8.5, "panel2"), ("st9", 9.0, "panel2"),
                            ("st9.5", 9.5, "panel2"), ("st10", 10.0, "panel2")]},
    "s48": {"derivative": "s48.png", "sha256_prefix": "33e6e612b115",
            "description": "Balclutha CA-54 sheet 48 section at frame 108, x4 greyscale derivative",
            "full": {"roi_px": [1195, 860, 2070, 2605], "centerline_px": 1204.75, "baseline_px": 2601,
                     "pixels_per_metre": 163.0, "z": [0.0, 10.6196]},
            "lower": {"roi_px": [1195, 1940, 2070, 2605], "centerline_px": 1204.75, "baseline_px": 2601,
                      "pixels_per_metre": 163.0, "z": [0.0, 4.0]},
            "upper": {"roi_px": [1195, 860, 2070, 1960], "centerline_px": 1204.75, "baseline_px": 2601,
                      "pixels_per_metre": 163.0, "z": [4.0, 10.6196]},
            "stations": [("frame-108", 0.0, "full"), ("frame-108-lower", 1.0, "lower"),
                         ("frame-108-upper", 2.0, "upper")]},
    "alma_sections": {"derivative": "alma_sections.png", "sha256_prefix": "1847e066d39d",
                      "description": "ALMA cross sections sheet 4, midship section A-A, x3 greyscale derivative",
                      "deck": {"roi_px": [1250, 1510, 2160, 1960], "centerline_px": 1258.5, "baseline_px": 1951.6,
                               "pixels_per_metre": 246.7, "z": [0.0, 1.7491]},
                      "rail": {"roi_px": [1250, 1405, 2160, 1960], "centerline_px": 1258.5, "baseline_px": 1951.6,
                               "pixels_per_metre": 246.7, "z": [0.0, 2.1751]},
                      "lower": {"roi_px": [1250, 1720, 2160, 1960], "centerline_px": 1258.5, "baseline_px": 1951.6,
                                "pixels_per_metre": 246.7, "z": [0.0, 0.9]},
                      "stations": [("midship-AA-to-deck", 0.0, "deck"), ("midship-AA-to-rail", 1.0, "rail"),
                                   ("midship-AA-lower", 2.0, "lower")]},
    "alma_lines": {"derivative": "alma_lines.png", "sha256_prefix": "d8e52523abd3",
                   "description": "ALMA lines drawing body plan (right half), x3 greyscale derivative",
                   "full": {"roi_px": [1945, 580, 2560, 840], "centerline_px": 1955.5, "baseline_px": 833,
                            "pixels_per_metre": 164.2, "z": [0.1218, 1.4799]},
                   "lower": {"roi_px": [1945, 690, 2560, 840], "centerline_px": 1955.5, "baseline_px": 833,
                             "pixels_per_metre": 164.2, "z": [0.1218, 0.8]},
                   "upper": {"roi_px": [1945, 580, 2560, 710], "centerline_px": 1955.5, "baseline_px": 833,
                             "pixels_per_metre": 164.2, "z": [0.8, 1.4799]},
                   "stations": [("body-right-half", 0.0, "full"), ("body-right-lower", 1.0, "lower"),
                                ("body-right-upper", 2.0, "upper")]},
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_sheet(name: str, derivatives: Path, out: Path) -> dict:
    sheet = SHEETS[name]
    out.mkdir(parents=True, exist_ok=False)
    source = derivatives / sheet["derivative"]
    digest = _sha256(source)
    if not digest.startswith(sheet["sha256_prefix"]):
        raise SystemExit(f"{name}: derivative hash {digest[:12]} is not the documented one")
    (out / "drawing.png").write_bytes(source.read_bytes())
    sections = []
    for sid, x, panel_name in sheet["stations"]:
        panel = sheet[panel_name]
        sections.append({"id": sid, "x_m": x, "roi_px": panel["roi_px"],
                         "calibration": {"centerline_px": panel["centerline_px"], "baseline_px": panel["baseline_px"],
                                         "pixels_per_metre": panel["pixels_per_metre"]},
                         "z_min_m": panel["z"][0], "z_max_m": panel["z"][1],
                         "evidence": ("Assistant-read provisional calibration (docs/GEOMETRY_ACCURACY_V05.md 8.2); "
                                      "the panel is shared by every station drawn in it; x_m is an ordinal.")})
    spec = {"schema_version": "1.0", "vessel_id": f"authentic sheet {name} (line identity only)", "units": "m",
            "source": {"file": "drawing.png", "sha256": digest, "license": "US public domain (NPS HAER / NPS)",
                       "description": sheet["description"]},
            "symmetry": "port_starboard", "symmetry_evidence": "Half body plan; symmetry assumed for the draft only.",
            "end_closure": "flat_at_terminal_stations", "sections": sections, "components": []}
    (out / "spec.json").write_text(json.dumps(spec, indent=2) + "\n")
    return {"sheet": name, "drawing_sha256": digest, "sections": len(sections)}


def prepare_gunnerus(out: Path) -> dict:
    sys.path.insert(0, str(ROOT))
    from benchmarks.gunnerus import make_gunnerus_configs, raster_path
    base = SOURCES / "gunnerus" / "polarkonsult"
    config, _ = make_gunnerus_configs.vector_config(base / "Lines Plan Rev0.dxf")
    raster = make_gunnerus_configs.raster_config(base / "Lines Plan Rev0.pdf", config["stations"])
    out.mkdir(parents=True, exist_ok=False)
    (out / "gunnerus_raster.json").write_text(json.dumps(raster, indent=2) + "\n")
    raster_path.cmd_prepare(raster, out, out)
    return {"sheet": "gunnerus", "drawing_sha256": _sha256(out / "drawing.png"), "sections": len(raster["stations"])}


def run_arm(arm: str, input_dir: Path, out: Path, controller: Path, python: str) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    policy, ambiguity = {"abstain": ("deterministic", "abstain"), "draft": ("deterministic", "draft"),
                         "llm": ("live", "draft")}[arm]
    command = [str(controller), "run", "--task", str(out / "task"), "--source", str(input_dir / "spec.json"),
               "--worker-python", python, "--worker-source", str(ROOT / "src"),
               "--policy", policy, "--on-ambiguity", ambiguity]
    if arm == "llm":
        command += ["--provider-transfer-basis", BASIS]
        # The canonical loader exports the keys into this shell only.
        # The keys file is named explicitly: `source` would otherwise pass the
        # controller command as the loader's first argument.
        loader = 'source scripts/load_opencode_keys.sh "$HOME/.config/marinaframe/opencode-go-keys.txt" >/dev/null'
        command = ["bash", "-c", loader + ' && exec "$@"', "bash", *command]
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
    seconds = time.perf_counter() - started
    (out / "controller_stdout.json").write_text(completed.stdout)
    (out / "controller_stderr.txt").write_text(completed.stderr[-20000:])
    record = {"arm": arm, "exit": completed.returncode, "wall_seconds": round(seconds, 1),
              "commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                       cwd=ROOT).stdout.strip()}
    (out / "arm_record.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def _events(task: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((task / "events").glob("*.json"))]


def summarize(run: Path, input_dir: Path, truth: Path | None, metric: Path | None) -> dict:
    from PIL import Image, ImageDraw
    task = run / "task"
    record = json.loads((run / "arm_record.json").read_text())
    stdout = (run / "controller_stdout.json").read_text().strip()
    status = json.loads(stdout) if stdout.startswith("{") else {"status": "cli_error"}
    state = json.loads((task / "domain" / "state.json").read_text())
    spec = json.loads((input_dir / "spec.json").read_text())
    events = _events(task)
    counters = events[-1]["state_after"]["counters"] if events else {}
    guesses = state.get("guesses") or []
    lines = {}
    for sid, cid in state["selected"].items():
        lines[sid] = ("selected", cid)
    for guess in guesses:
        if guess["chosen_candidate_id"]:
            lines[guess["section_id"]] = (guess["kind"], guess["chosen_candidate_id"])
    kinds = {}
    for guess in guesses:
        kinds[guess["kind"]] = kinds.get(guess["kind"], 0) + 1
    tools, refused = {}, 0
    for event in events:
        if event["kind"] == "decision" and event["payload"].get("actor") == "live_model":
            tool = event["payload"]["decision"]["tool"]
            tools[tool] = tools.get(tool, 0) + 1
        if event["kind"] in ("operation_rejected", "model_output_rejected"):
            refused += 1
        if (event["kind"] == "worker_result"
                and event["payload"]["response"]["result"].get("status") == "proposal_refused"):
            refused += 1
    image = Image.open(input_dir / "drawing.png").convert("RGB")
    draw = ImageDraw.Draw(image)
    colours = {"selected": (0, 150, 0), "best_candidate": (230, 120, 0), "model_choice": (200, 0, 200)}
    chosen = {}
    for sid, (kind, cid) in sorted(lines.items()):
        candidate = next(c for c in state["catalog"][sid]["candidates"] if c["candidate_id"] == cid)
        anchors = candidate["contour_selection"]["anchors_px"] if "contour_selection" in candidate else []
        if len(anchors) >= 2:
            draw.line([tuple(p) for p in anchors], fill=colours[kind], width=3)
            label = anchors[len(anchors) // 2]
            draw.text((label[0] + 4, label[1]), sid, fill=colours[kind])
        chosen[sid] = {"kind": kind, "candidate_id": cid, "hypothesis": candidate.get("hypothesis"),
                       "anchors_px": anchors}
    image.save(run / "overlay.png")
    summary = {"arm": record["arm"], "status": status.get("status"),
               "termination_reason": status.get("termination_reason"),
               "sections": len(spec["sections"]), "sections_with_line": len(lines),
               "selected": len(state["selected"]), "guess_kinds": kinds,
               "requests": {k: counters.get(k) for k in ("requests_intended", "requests_completed",
                                                          "requests_failed", "requests_unknown",
                                                          "requests_not_sent")},
               "prompt_tokens": counters.get("prompt_tokens"), "completion_tokens": counters.get("completion_tokens"),
               "observed_cost_usd": counters.get("observed_cost_usd"),
               "requests_without_cost": counters.get("requests_without_cost"),
               "model_tools": tools, "refusals": refused, "wall_seconds": record["wall_seconds"],
               "views_sent": len(state.get("views", [])), "commit": record["commit"], "lines": chosen}
    candidate = status.get("current_candidate") or {}
    if truth is not None and candidate.get("path"):
        sys.path.insert(0, str(ROOT))
        from benchmarks.gunnerus import score
        run_dir = task / candidate["path"]
        model = next((run_dir / n for n in ("model-draft.step", "model.step") if (run_dir / n).exists()), None)
        stations = [{"id": s["id"], "x_m": s["x_m"], "status": "read" if s["id"] in lines else "not_read"}
                    for s in spec["sections"]]
        result = score.score(truth, model, stations, json.loads(metric.read_text()), run / "score")
        summary["score_status"] = result["status"]
        summary["score_file"] = str(run / "score" / "score.json")
    (run / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["prepare-gunnerus", "prepare-sheet", "run", "batch", "summarize"])
    parser.add_argument("--root", type=Path, help="batch: folder with one <sheet>/input per sheet")
    parser.add_argument("--sheets", help="batch: comma-separated sheet folders")
    parser.add_argument("--arms", help="batch: comma-separated arms, run in order per sheet")
    parser.add_argument("--sheet", choices=sorted(SHEETS))
    parser.add_argument("--derivatives", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--arm", choices=["abstain", "draft", "llm"])
    parser.add_argument("--controller", type=Path, default=ROOT / "target/release/marinaframe")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--truth", type=Path)
    parser.add_argument("--metric", type=Path)
    args = parser.parse_args()
    if args.command == "prepare-gunnerus":
        result = prepare_gunnerus(args.out)
    elif args.command == "prepare-sheet":
        result = prepare_sheet(args.sheet, args.derivatives, args.out)
    elif args.command == "run":
        result = run_arm(args.arm, args.input, args.out, args.controller, args.python)
    elif args.command == "batch":
        result = {}
        for sheet in args.sheets.split(","):
            for arm in args.arms.split(","):
                result[f"{sheet}/{arm}"] = run_arm(arm, args.root / sheet / "input", args.root / sheet / arm,
                                                   args.controller, args.python)
                print(json.dumps({f"{sheet}/{arm}": result[f"{sheet}/{arm}"]}), flush=True)
    else:
        result = summarize(args.run, args.input, args.truth, args.metric)
        result = {k: v for k, v in result.items() if k != "lines"}
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
