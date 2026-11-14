#!/usr/bin/env python3
"""One-factor numerical diagnostics on the frozen development sample only."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_thin_ship_shipd import (digest, evaluate_offsets, relative_error,
                                    selected_rows, subset_path)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reference_rw(y, speed, x, z, count):
    """Vectorised published Filon formula; diagnostic, not production code.

    Matches local ModifiedMichellCw.py, including endpoint terms and nan_to_num.
    Angle refinement changes only the number of published michspace samples.
    """
    theta = -((np.logspace(0, 1, count)-1)*np.pi/18-np.pi/2)[::-1]
    a = 1/np.cos(theta)
    k0 = 9.81/speed**2
    k = k0*a*a
    dz = z[1]-z[0]
    q = k*dz
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        depth = np.exp(k[:, None]*z[None, :])*dz
        depth[:, 0] *= (np.exp(q)-1-q)/q**2
        depth[:, -1] *= (np.exp(-q)-1+q)/q**2
        depth[:, 1:-1] *= ((np.exp(q)+np.exp(-q)-2)/q**2)[:, None]
        f = depth @ y.T
        dx = x[-1]/(len(x)-1)
        phase = k0*a[:, None]*x[None, :]
        p, qsin = f*np.cos(phase), f*np.sin(phase)
        pt, qt = p[:, -1], qsin[:, -1]
        t = k0*dx*a
        alpha = (t*t+.5*t*np.sin(2*t)+np.cos(2*t)-1)/t**3
        beta = (3*t+t*np.cos(2*t)-2*np.sin(2*t))/t**3
        gamma = 4*(np.sin(t)-t*np.cos(t))/t**3
        p_int = dx*(alpha*qt+beta*(p[:, ::2].sum(axis=1)-.5*pt)
                    +gamma*p[:, 1::2].sum(axis=1))
        q_int = dx*(-alpha*pt+beta*(qsin[:, ::2].sum(axis=1)-.5*qt)
                    +gamma*qsin[:, 1::2].sum(axis=1))
        integrand = 4*1000*speed**2/np.pi*k*k/a**3 * (
            k*k*(p_int*p_int+q_int*q_int)
            +2*k*a*(q_int*pt-p_int*qt)+a*a*(pt*pt+qt*qt))
        integrand = np.nan_to_num(integrand)
    return float(np.sum(.5*(integrand[:-1]+integrand[1:])*np.diff(theta)))


def statistics(rows):
    values = [r["error_percent"] for r in rows if r["error_percent"] is not None]
    signed = [100*(r["cw"]-r["reference_cw"])/r["reference_cw"]
              for r in rows if r["error_percent"] is not None]
    return {"conditions": len(rows), "finite": len(values),
            "median_absolute_percent": float(np.median(values)) if values else None,
            "p90_absolute_percent": float(np.percentile(values, 90)) if values else None,
            "median_signed_percent": float(np.median(signed)) if signed else None}


def export_summary(directory, output):
    """Export only aggregate evidence; keep IDs and condition values ignored."""
    diagnostics = [json.loads(line) for line in (directory/"experiments.jsonl").read_text().splitlines()]
    development = json.loads((directory/"reference-refinement.json").read_text())
    result = {"status": "review_required", "engineering_approved": False,
              "original_gate": "FAIL; unchanged", "splits_complete_case":
              json.loads((directory/"splits.json").read_text()),
              "refined_reference_development_complete_case": statistics(development),
              "diagnostic_conditions": len(diagnostics), "variants": {}}
    for name in diagnostics[0]["variants"]:
        errors, changes = [], []
        for row in diagnostics:
            variant = row["variants"][name]
            if variant["reference_error_percent"] is not None:
                errors.append(variant["reference_error_percent"])
                changes.append(100*abs(variant["cw"]/row["variants"]["baseline"]["cw"]-1))
        result["variants"][name] = {"finite": len(errors),
            "reference_error_median_p90_percent": np.percentile(errors, [50, 90]).tolist(),
            "change_median_max_percent": np.percentile(changes, [50, 100]).tolist()}
    result["max_section_error_m"] = max(row["section_error_m"] for row in diagnostics)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")


def band(value, boundaries):
    return str(sum(value >= bound for bound in boundaries))


def shape_features(hull, draft):
    # Elliptical cross-section proxy, not a measured bulb volume or area.
    peak = hull.Hbb*hull.WL
    halfheight = max(peak, hull.WL-peak)
    halfwidth = hull.BB_Prof[3] if hull.bit_BB else 0
    area_proxy = math.pi*halfwidth*halfheight/(2*hull.Bd*hull.Dd)
    return {"length_band": band(hull.Lbb, (.05, .1)) if hull.bit_BB else "no_bow_bulb",
            "area_proxy_band": band(area_proxy, (.05, .15)) if hull.bit_BB else "no_bow_bulb",
            "peak_immersion_band": band((draft*hull.Dd-peak)/(draft*hull.Dd), (0, .5))
            if hull.bit_BB else "no_bow_bulb"}


def run(args):
    manifest = json.loads(args.manifest.read_text())
    excluded = set(args.exclusions.read_text().splitlines())
    if digest(args.exclusions) != manifest["exclusions_sha256"] or excluded.intersection(manifest["ids"]):
        raise ValueError("Exclusions changed or frozen IDs excluded")
    for name, expected in manifest["sources"].items():
        if digest(args.source/name) != expected:
            raise ValueError(f"Source changed: {name}")
    records = []
    with args.trace.open() as stream:
        for line in stream:
            # Check identifier before using any condition values.
            record = json.loads(line)
            if record["id"] not in manifest["ids"] or record["id"] in excluded:
                raise ValueError("Unexpected trace ID")
            records.append(record)
    if len(records) != 9600:
        raise ValueError("Incomplete baseline")
    geometry = load_module("shipd_geometry", args.source/"code/HullParameterization.py")
    original = load_module("shipd_reference", args.source/"code/ModifiedMichellCw.py")
    vectors = {}
    for subset in (1, 2, 3):
        ids = [i for i in manifest["ids"] if i.startswith(f"shipd-{subset}-")]
        rows = selected_rows(subset_path(args.source, subset)/"Input_Vectors.csv",
                             {int(i.rsplit("-", 1)[1]) for i in ids})
        vectors.update({i: rows[int(i.rsplit("-", 1)[1])] for i in ids})
    hulls = {i: geometry.Hull_Parameterization(v) for i, v in vectors.items()}
    for record in records:
        record.update(shape_features(hulls[record["id"]], record["draft_fraction"]))
    groups = {}
    for field in ("bow_bulb", "fn", "length_band", "area_proxy_band", "peak_immersion_band"):
        groups[field] = {str(value): statistics([r for r in records if r[field] == value])
                         for value in sorted({r[field] for r in records}, key=str)}
    for field in ("length_band", "area_proxy_band", "peak_immersion_band"):
        groups[field+"_by_fn"] = {
            f"{value}:{fn}": statistics([r for r in records if r[field] == value and r["fn"] == fn])
            for value in sorted({r[field] for r in records}, key=str)
            for fn in manifest["froudes"]}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"splits.json").write_text(json.dumps(groups, indent=2)+"\n")
    worst = sorted(manifest["ids"], key=lambda i: (
        -max(r["error_percent"] or 0 for r in records if r["id"] == i), i))
    chosen = ([i for i in worst if hulls[i].bit_BB][:6]
              +[i for i in worst if not hulls[i].bit_BB][:3])
    diagnostics = []
    with (args.output/"experiments.jsonl").open("x") as stream:
        for identifier in chosen:
            hull = hulls[identifier]
            for draft in (.25, .5, .67):
                x, z, y, wl = hull.gen_PC_for_Cw(hull.Dd*draft, NUM_WL=51, PointsPerWL=301)
                # Check returned dense offsets against explicitly indexed waterline sections.
                section_error = 0.
                # Use the original linspace exactly, avoiding a subtract/add round trip
                # that can move a boundary station across a strict geometry comparison.
                heights = np.linspace(1e-8*hull.Dd, draft*hull.Dd, 51)
                bow = [hull.BB_profile(h) if hull.bit_BB and h <= hull.WL
                       else hull.bow_profile(h) for h in heights]
                stern = [hull.SB_profile(h) if hull.bit_SB and h <= hull.HSBOA*hull.WL
                         else hull.stern_profile(h) for h in heights]
                original_x = np.linspace(min(bow), max(stern), 301)
                for col, height in enumerate(heights):
                    points = hull.gen_MeshGridWL(original_x, height)
                    reconstructed = np.zeros(301)
                    for point in points[1:-1]:
                        index = int(np.argmin(abs(original_x-point[0])))
                        reconstructed[index] = point[1]
                    section_error = max(section_error, float(np.max(abs(reconstructed-y[:, col]))))
                variants = {"baseline": (x, z, y, wl, 512, 24),
                            "angles": (x, z, y, wl, 2048, 24),
                            "tail": (x, z, y, wl, 512, 48)}
                exact_z = z.copy()
                exact_z[0] = -draft*hull.Dd
                variants["keel_origin"] = (x, exact_z, y, wl, 512, 24)
                for name, nx, nz in (("x_resolution", 1201, 51), ("z_resolution", 301, 201)):
                    rx, rz, ry, rwl = hull.gen_PC_for_Cw(hull.Dd*draft, NUM_WL=nz, PointsPerWL=nx)
                    variants[name] = (rx, rz, ry, rwl, 512, 24)
                for fn in (.1, .2, .3, .45):
                    baseline = next(r for r in records if r["id"] == identifier
                                    and r["fn"] == fn and r["draft_fraction"] == draft)
                    result = {"id": identifier, "draft": draft, "fn": fn,
                              "bow_bulb": bool(hull.bit_BB), "reference_cw": baseline["reference_cw"],
                              "section_error_m": section_error, "variants": {}}
                    for name, (vx, vz, vy, vwl, angles, tail) in variants.items():
                        value = evaluate_offsets(vx, vz, vy, vwl, hull.LOA, fn, angles, tail)
                        value["reference_error_percent"] = relative_error(value["cw"], baseline["reference_cw"])
                        result["variants"][name] = value
                    speed = fn*math.sqrt(9.81*wl)
                    result["reference_angles"] = {}
                    for count in (21, 81, 321):
                        rw = reference_rw(y, speed, x, z, count)
                        cw = rw/(.5*1000*speed**2*hull.LOA**2)
                        result["reference_angles"][str(count)] = cw
                    if not diagnostics:
                        direct = original.ModMichell(y, speed, x, z, 1000, 21)
                        result["original_vectorised_difference_percent"] = relative_error(
                            result["reference_angles"]["21"], direct/(.5*1000*speed**2*hull.LOA**2))
                    diagnostics.append(result)
                    stream.write(json.dumps(result, allow_nan=False)+"\n")
                    stream.flush()
            print(json.dumps({"completed_hulls": len({r["id"] for r in diagnostics}),
                              "conditions": len(diagnostics)}), flush=True)
    # Descriptive full-development comparison, not a replacement gate run.
    development = []
    for identifier, hull in hulls.items():
        for draft in manifest["drafts"]:
            x, z, y, wl = hull.gen_PC_for_Cw(hull.Dd*draft, NUM_WL=51, PointsPerWL=301)
            for fn in manifest["froudes"]:
                baseline = next(r for r in records if r["id"] == identifier
                                and r["draft_fraction"] == draft and r["fn"] == fn)
                speed = fn*math.sqrt(9.81*wl)
                cw = reference_rw(y, speed, x, z, 321)/(.5*1000*speed**2*hull.LOA**2)
                development.append({"id": identifier, "fn": fn, "draft": draft,
                                    "reference_321_cw": cw,
                                    "error_percent": relative_error(baseline["cw"], cw),
                                    "cw": baseline["cw"], "reference_cw": cw})
    (args.output/"reference-refinement.json").write_text(json.dumps(development)+"\n")
    print(json.dumps({"reference_321_development": statistics(development)}), flush=True)
    print("Diagnostics complete", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, help="Export aggregates from this diagnostic directory")
    for name in ("source", "exclusions", "manifest", "trace", "output"):
        parser.add_argument("--"+name, type=Path)
    args = parser.parse_args()
    if args.export is not None:
        if args.output is None:
            parser.error("export requires --output")
        export_summary(args.export, args.output)
    else:
        if any(getattr(args, name) is None for name in ("source", "exclusions", "manifest", "trace", "output")):
            parser.error("run requires source, exclusions, manifest, trace and output")
        run(args)
