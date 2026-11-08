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


def build_hull(sources: Path, out: Path) -> Path:
    from benchmarks.gunnerus import make_gunnerus_configs, vector_path

    config, ledger = make_gunnerus_configs.vector_config(sources / LINES_FILE)
    config['dxf'] = str((sources / LINES_FILE).resolve())
    (out / 'hull_config.json').write_text(json.dumps(config, indent=2) + '\n')
    (out / 'hull_identity.json').write_text(json.dumps(ledger, indent=2) + '\n')
    summary = vector_path.run(out / 'hull_config.json', out / 'hull')
    (out / 'hull_summary.json').write_text(json.dumps(summary, indent=2, default=str) + '\n')
    return out / 'hull' / 'model.brep'


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


KIND_OF_OP = {'deck': 'deck', 'deckhouse': 'deckhouse', 'bulwark': 'bulwark', 'appendage': 'appendage'}


def components_record(step1: Path, out: Path, hull_volume_m3: float | None, hull_box: dict | None) -> dict:
    """Component list for the app tree (TaskView ``components``; see docs/APP_SPEC.md when it lands).

    One item per component: id, kind, box (m), source counts, review state, STEP path, volume.
    Every item starts as ``needs_review``; nothing here is approved.
    """
    execution = json.loads((step1 / 'execution.json').read_text())
    items = []
    if hull_volume_m3 is not None:
        items.append({'id': 'hull', 'kind': 'hull', 'box_m': hull_box, 'volume_m3': hull_volume_m3,
                      'source_counts': {'traced': None, 'ai_inferred': 0, 'guessed': None},
                      'review_state': 'needs_review', 'step_path': 'hull/model.brep',
                      'note': 'Region loft from the lines plan; per-value source counts are not recorded'})
    for component in (execution.get('result') or {}).get('components', []):
        counts = {'traced': 0, 'ai_inferred': 0, 'guessed': 0}
        for label in component.get('source_labels', {}).values():
            counts[label] = counts.get(label, 0) + 1
        built = component.get('built', False)
        items.append({'id': component['id'], 'kind': KIND_OF_OP.get(component['op'], component['op']),
                      'box_m': component.get('bbox_m') if built else None,
                      'volume_m3': component.get('volume_m3') if built else None,
                      'source_counts': counts, 'review_state': 'needs_review', 'status': component['status'],
                      'step_path': str(step1 / 'task' / 'work' / 'output' / f'{component["id"]}.step') if built
                      else None})
    record = {'schema': 'marinaframe.components.v0', 'engineering_approved': False,
              'assembly_step': 'whole-vessel-draft.step', 'components': items}
    (out / 'components.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--step1', type=Path, required=True, help='Step 1 run folder (whole_vessel.py output)')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    import cadquery as cq

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.time()
    hull_path = build_hull(args.sources, out)
    record = {'engineering_approved': False, 'status': 'draft_only', 'hull_seconds': time.time() - started}
    shapes, volumes, hull_box = [], {}, None
    if hull_path.is_file():
        hull = read_shape(hull_path)
        shapes.append(hull)
        volumes['hull'] = hull.Volume() / 1e9
        box = hull.BoundingBox()
        hull_box = {'min': [box.xmin / 1000, box.ymin / 1000, box.zmin / 1000],
                    'max': [box.xmax / 1000, box.ymax / 1000, box.zmax / 1000]}
    parts = args.step1 / 'task' / 'work' / 'output'
    for part in PART_IDS:
        path = parts / f'{part}.step'
        if path.is_file():
            shape = read_shape(path)
            shapes.append(shape)
            volumes[part] = shape.Volume() / 1e9
    assembly = cq.Compound.makeCompound(shapes)
    step = out / 'whole-vessel-draft.step'
    cq.exporters.export(assembly, str(step))
    box = assembly.BoundingBox()
    record.update(volumes_m3=volumes, sum_of_parts_m3=sum(volumes.values()),
                  bbox_m={'min': [box.xmin / 1000, box.ymin / 1000, box.zmin / 1000],
                          'max': [box.xmax / 1000, box.ymax / 1000, box.zmax / 1000]},
                  step=step.name, step_sha256=hashlib.sha256(step.read_bytes()).hexdigest(),
                  step_bytes=step.stat().st_size, solids=len(assembly.Solids()))
    components_record(args.step1.resolve(), out, volumes.get('hull'), hull_box)
    render(assembly, out / 'whole-vessel-draft.png')
    record.update(render='whole-vessel-draft.png', seconds=time.time() - started)
    (out / 'assembly.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
