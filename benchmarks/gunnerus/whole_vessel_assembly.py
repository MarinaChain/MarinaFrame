"""Assemble the Gunnerus hull (existing vector hull path) with the step 1 parts into one STEP.

The hull comes from the lines plan through ``make_gunnerus_configs.vector_config`` and
``vector_path.run`` (the production region loft). This is a development build for the app
view: no hull score is computed and the sealed hull benchmark is not touched.

Usage (outputs are drawing derivatives: keep them out of the repository)::

    PYTHONPATH=src python -m benchmarks.gunnerus.whole_vessel_assembly \\
        --sources work/sources/gunnerus --step1 <step 1 run dir> --out work/whole-vessel/assembly-001
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

LINES_FILE = 'polarkonsult/Lines Plan Rev0.dxf'
# Component STEP files of the step 1 run (millimetres). Openings are not material.
PART_IDS = ('aft_deck', 'main_deck', 'house_t1', 'aft_bulwark', 'house_t2', 'wheelhouse', 'fwd_rail')
# Render: isometric view from aft starboard, above (pixels of the PNG).
RENDER_SIZE = (1600, 900)
# Viewer mesh chord tolerance (mm): fine enough for a 36 m ship on screen.
MESH_TOLERANCE_MM = 5.0
# Truth STEP volume (hull and first tier; docs/SHIP_CAD_LANGUAGE.md).
TRUTH_VOLUME_M3 = 1302.280


def deck_at_side(inputs: dict) -> dict:
    """Deck at side from the GA reading: aft deck aft of the first-tier end wall, 1-deck forward.

    The lines-plan stations run up to the bulwark and forecastle tops (up to 7.59 m), so a loft
    to those tops holds the bulwarks and the first tier as hull: +52 % volume against the truth.
    In the whole vessel those are their own parts, so the hull stops at the deck.
    """
    levels = inputs['levels']
    walls = inputs.get('tier_end_walls', {}).get('house_t1', {}).get('walls') or []
    split_x = walls[0]['x_m'] if walls else (levels['aft_deck']['extent'] or [0, 15.5])[1]
    return {'split_x_m': split_x, 'aft_deck_z_m': levels['aft_deck']['z'], 'main_deck_z_m': levels['main_deck']['z']}


def cap_stations(config: dict, deck: dict) -> dict:
    """End each station at the deck at side (never above its drawn top)."""
    for station in config['stations']:
        deck_z = deck['aft_deck_z_m'] if station['x_m'] < deck['split_x_m'] else deck['main_deck_z_m']
        drawn = station.get('top_z_m', config['side_line']['top_z_m'])
        station['top_z_m'] = round(min(drawn, deck_z), 4)
    config['side_line']['top_z_m'] = round(min(config['side_line']['top_z_m'], deck['main_deck_z_m']), 4)
    return config


def build_hull(sources: Path, out: Path, deck: dict | None = None) -> Path:
    from benchmarks.gunnerus import make_gunnerus_configs, vector_path

    config, ledger = make_gunnerus_configs.vector_config(sources / LINES_FILE)
    if deck:
        config = cap_stations(config, deck)
    config['dxf'] = str((sources / LINES_FILE).resolve())
    (out / 'hull_config.json').write_text(json.dumps(config, indent=2) + '\n')
    (out / 'hull_identity.json').write_text(json.dumps(ledger, indent=2) + '\n')
    summary = vector_path.run(out / 'hull_config.json', out / 'hull')
    (out / 'hull_summary.json').write_text(json.dumps(summary, indent=2, default=str) + '\n')
    return out / 'hull' / 'model.brep'


def cap_region_rows(rows: list, cap_z: float) -> list | None:
    """Rows ``[z, y_in, y_out]`` up to cap_z, with an interpolated row at cap_z; None if too few."""
    kept = [row for row in rows if row[0] <= cap_z]
    above = [row for row in rows if row[0] > cap_z]
    if kept and above and kept[-1][0] < cap_z:
        low, high = kept[-1], above[0]
        t = (cap_z - low[0]) / (high[0] - low[0])
        kept.append([cap_z] + [low[i] + t * (high[i] - low[i]) for i in (1, 2)])
    return kept if len(kept) >= 2 else None


def cap_sections(sections: list[dict], deck: dict) -> list[dict]:
    """End each station at the deck at side, cutting the read section rows (no CAD Boolean).

    Station tops only end the side-line extension; forward station curves are drawn up to the
    forecastle top (7.59 m), so their rows must be cut. A Boolean cut of the lofted solids lost
    whole solids on this hull, so the cut happens before the loft.
    """
    capped = []
    for section in sections:
        cap_z = deck['aft_deck_z_m'] if section['x_m'] < deck['split_x_m'] else deck['main_deck_z_m']
        regions = []
        for region in section['regions']:
            rows = cap_region_rows(region['rows_m'], cap_z)
            if rows:
                regions.append({'kind': region['kind'], 'rows_m': rows})
        if regions:
            capped.append({'id': section['id'], 'x_m': section['x_m'], 'regions': regions})
    return capped


def build_hull_to_deck(sections_path: Path, deck: dict, out: Path) -> tuple[Path, dict]:
    """Loft the capped sections with the production region builder (same CAD bound ladder)."""
    from benchmarks.gunnerus.vector_path import CAD_DEVIATION_LADDER_M
    from vessel_reconstruction.errors import GeometryError
    from vessel_reconstruction.geometry import build_region_hull

    sections = cap_sections(json.loads(sections_path.read_text()), deck)
    error = None
    for bound in CAD_DEVIATION_LADDER_M:
        try:
            shape, report = build_region_hull(sections, max_deviation_m=bound)
        except GeometryError as exc:
            error = str(exc)
            if 'complexity limit' in error:
                continue
            break
        path = out / 'hull_to_deck.brep'
        write_brep(shape, path)
        return path, {'status': 'built', 'cad_bound_m': bound, 'stations': len(sections),
                      'solid_count': report['solid_count'], 'volume_m3': report['volume_m3']}
    raise GeometryError(f'hull to deck not built: {error}')


def read_shape(path: Path):
    import cadquery as cq
    from OCP.BinTools import BinTools
    from OCP.TopoDS import TopoDS_Shape

    if path.suffix == '.brep':
        shape = TopoDS_Shape()
        BinTools.Read_s(shape, str(path))
        return cq.Shape.cast(shape)
    return cq.importers.importStep(str(path)).val()


def render(shape, path: Path) -> None:
    """Shaded isometric PNG of the assembly (matplotlib, no display)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    vertices, triangles = shape.tessellate(50.0, 0.5)
    points = np.array([[v.x, v.y, v.z] for v in vertices]) / 1000.0
    faces = points[np.asarray(triangles)]
    normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
    light = np.clip(normals @ np.array([0.3, -0.5, 0.8]), 0.1, 1.0)
    figure = plt.figure(figsize=(RENDER_SIZE[0] / 100, RENDER_SIZE[1] / 100), dpi=100)
    axes = figure.add_subplot(projection='3d')
    axes.add_collection3d(Poly3DCollection(faces, facecolors=plt.cm.Greys(0.3 + 0.6 * light), linewidths=0))
    low, high = points.min(axis=0), points.max(axis=0)
    axes.set_xlim(low[0], high[0]), axes.set_ylim(low[1], high[1]), axes.set_zlim(low[2], high[2])
    axes.set_box_aspect(high - low)
    axes.view_init(elev=20, azim=-60)
    axes.set_axis_off()
    figure.savefig(path, bbox_inches='tight')
    plt.close(figure)


def write_brep(shape, path: Path) -> None:
    from OCP.BinTools import BinTools

    BinTools.Write_s(shape.wrapped, str(path))


def export_all(shapes: dict, out: Path) -> dict:
    """STEP per part and for the assembly (no pcurves: about half the size), plus a GLB mesh view."""
    import cadquery as cq

    sizes = {}
    parts = out / 'whole_vessel'
    parts.mkdir(exist_ok=True)
    for name, shape in shapes.items():
        path = parts / f'{name}.step'
        cq.exporters.export(shape, str(path), opt={'write_pcurves': False})
        sizes[f'whole_vessel/{name}.step'] = path.stat().st_size
    step = out / 'whole-vessel-draft.step'
    cq.exporters.export(cq.Compound.makeCompound(list(shapes.values())), str(step), opt={'write_pcurves': False})
    sizes[step.name] = step.stat().st_size
    assembly = cq.Assembly()
    for name, shape in shapes.items():
        assembly.add(shape, name=name)
    mesh = out / 'whole-vessel-draft.glb'
    assembly.save(str(mesh), exportType='GLTF', tolerance=MESH_TOLERANCE_MM, angularTolerance=0.5)
    sizes[mesh.name] = mesh.stat().st_size
    return {'bytes': sizes, 'assembly_step_sha256': hashlib.sha256(step.read_bytes()).hexdigest(),
            'mesh_tolerance_mm': MESH_TOLERANCE_MM}


LABELS = {'hull': 'Hull (to the deck at side)', 'aft_deck': 'Aft working deck', 'main_deck': '1-deck',
          'house_t1': 'Superstructure tier 1 (1-deck to A-deck)', 'aft_bulwark': 'Aft bulwark',
          'house_t2': 'Deckhouse tier 2 (on A-deck)', 'wheelhouse': 'Wheelhouse',
          'fwd_rail': 'Forward rail (A-deck)'}


def _argument_provenance(component: dict) -> dict:
    """Provenance keyed by argument name, with a basis for each value (the app reads this)."""
    by_argument = {}
    references = {name: ref for name, ref in component.get('args', {}).items() if isinstance(ref, str)}
    for argument, label in component.get('source_labels', {}).items():
        record = component.get('provenance', {}).get(references.get(argument, argument), {})
        basis = record.get('basis')
        if basis is None and label == 'traced':
            basis = f'{record.get("method", "measured")} in the {record.get("view", "drawing")} view'
        by_argument[argument] = {'source': label, 'basis': basis}
    return by_argument


def write_app_parts(step1: Path, inputs: dict, out: Path, hull: dict | None) -> Path:
    """The app's whole-vessel folder: ``whole_vessel/execution.json`` and ``<id>.step``.

    Same shape as the ship-cad worker output (docs/APP_SPEC.md "Whole-vessel parts"), plus a
    ``label`` per part, the program ``args`` and the resolved ``geometry`` values (an older
    worker result has no geometry, so it is resolved again from the run inputs). The STEP
    files are written by ``export_all`` into the same folder.
    """
    from vessel_reconstruction.ship_cad import resolve_program

    execution = json.loads((step1 / 'execution.json').read_text())
    program = inputs['program']
    references = {c['id']: c['args'] for c in program.get('components', [])}
    resolved = {c['id']: c['geometry'] for c in resolve_program(program, inputs.get('measurements', {}),
                                                                inputs.get('guesses', {}))}
    components = []
    if hull:
        components.append(hull)
    for component in (execution.get('result') or {}).get('components', []):
        item = dict(component, label=LABELS.get(component['id'], component['id']))
        item['args'] = component.get('args') or references.get(component['id'], {})
        if item.get('geometry') is None and item.get('built'):
            item['geometry'] = resolved.get(component['id'])
        item['provenance'] = {**component.get('provenance', {}), **_argument_provenance(item)}
        components.append(item)
    folder = out / 'whole_vessel'
    folder.mkdir(exist_ok=True)
    record = {'exit_code': 0, 'result': {'schema': 'ship-cad-result/v1', 'status': 'draft_only',
                                         'engineering_approved': False, 'components': components}}
    (folder / 'execution.json').write_text(json.dumps(record, indent=2) + '\n')
    return folder


def hull_component(volume_m3: float, box: dict, cap: dict, summary: dict) -> dict:
    return {'id': 'hull', 'op': 'hull', 'label': LABELS['hull'], 'status': 'measured_draft', 'built': True,
            'reason': 'Region loft of the lines-plan stations, cut at the deck at side read from the GA',
            'source': {'view': 'body', 'region': 'hull', 'method': 'body_plan_regions'},
            'source_labels': {'sections': 'traced', 'deck_at_side': 'traced'},
            'provenance': {'sections': {'source': 'traced', 'basis': f'{summary.get("stations")} body-plan '
                                        'stations read from the lines plan DXF'},
                           'deck_at_side': {'source': 'traced', 'basis': f'aft deck {cap["aft_deck_z_m"]} m aft of '
                                            f'x {cap["split_x_m"]} m, 1-deck {cap["main_deck_z_m"]} m forward '
                                            '(GA profile)'}},
            'args': {'sections': 'hull_sections', 'deck_at_side': 'hull_deck_at_side'},
            'geometry': {'sections': f'{summary.get("stations")} stations',
                         'deck_at_side': [cap['aft_deck_z_m'], cap['main_deck_z_m']]},
            'bbox_m': box, 'volume_m3': volume_m3}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--step1', type=Path, required=True, help='Step 1 run folder (whole_vessel.py output)')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--hull-brep', type=Path, help='Reuse a hull model.brep built by this script earlier.')
    args = parser.parse_args()
    import cadquery as cq

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.time()
    step1 = args.step1.resolve()
    deck = deck_at_side(json.loads((step1 / 'inputs.json').read_text()))
    hull_path = args.hull_brep.resolve() if args.hull_brep else build_hull(args.sources, out, deck)
    record = {'engineering_approved': False, 'status': 'draft_only', 'hull_source': str(hull_path),
              'hull_station_cap': deck, 'hull_seconds': time.time() - started}
    shapes, volumes, hull_box = {}, {}, None
    if hull_path.is_file():
        record['hull_loft_volume_m3'] = read_shape(hull_path).Volume() / 1e9
        to_deck, record['hull_to_deck'] = build_hull_to_deck(hull_path.parent / 'sections.json', deck, out)
        hull = read_shape(to_deck)
        shapes['hull'] = hull
        volumes['hull'] = hull.Volume() / 1e9
        box = hull.BoundingBox()
        hull_box = {'min': [box.xmin / 1000, box.ymin / 1000, box.zmin / 1000],
                    'max': [box.xmax / 1000, box.ymax / 1000, box.zmax / 1000]}
    parts = step1 / 'task' / 'work' / 'output'
    for part in PART_IDS:
        path = parts / f'{part}.step'
        if path.is_file():
            shapes[part] = read_shape(path)
            volumes[part] = shapes[part].Volume() / 1e9
    record.update(volumes_m3=volumes, sum_of_parts_m3=sum(volumes.values()))
    if 'hull' in volumes and 'house_t1' in volumes:
        # The truth STEP holds the hull and the first tier only (docs/plans/...-scope.md, 3.3).
        record['truth_comparable_m3'] = volumes['hull'] + volumes['house_t1']
        record['truth_volume_m3'] = TRUTH_VOLUME_M3
        record['truth_comparable_error'] = record['truth_comparable_m3'] / TRUTH_VOLUME_M3 - 1
    record['exports'] = export_all(shapes, out)
    assembly = cq.Compound.makeCompound(list(shapes.values()))
    box = assembly.BoundingBox()
    record.update(bbox_m={'min': [box.xmin / 1000, box.ymin / 1000, box.zmin / 1000],
                          'max': [box.xmax / 1000, box.ymax / 1000, box.zmax / 1000]},
                  solids=len(assembly.Solids()))
    hull_entry = (hull_component(volumes['hull'], hull_box, deck, record['hull_to_deck'])
                  if 'hull' in volumes else None)
    inputs = json.loads((step1 / 'inputs.json').read_text())
    write_app_parts(step1, inputs, out, hull_entry)
    render(assembly, out / 'whole-vessel-draft.png')
    record.update(render='whole-vessel-draft.png', seconds=time.time() - started)
    (out / 'assembly.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
