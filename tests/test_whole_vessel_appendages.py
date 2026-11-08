"""Synthetic tests for the appendage reader (no licensed drawing) and the display mesh."""
import numpy as np
import pytest

ezdxf = pytest.importorskip('ezdxf')

from benchmarks.gunnerus import whole_vessel_appendages as appendages  # noqa: E402
from vessel_reconstruction.ship_cad import resolve_program  # noqa: E402

X0, Z0 = appendages.FRAME0_X, appendages.PROFILE_BASE_Y
PLAN_CENTRE_Y = 5000.0


def drawing(x_m, z_m):
    return (X0 + 1000 * x_m, Z0 + 1000 * z_m)


def plan(x_m, y_m):
    return (X0 + 1000 * x_m, PLAN_CENTRE_Y + 1000 * y_m)


def synthetic_ga(path):
    """A GA with a keel line, a skeg edge, a stern bottom, a thruster block and the tank-top plan."""
    doc = ezdxf.new()
    msp = doc.modelspace()
    # Keel line and the skeg's lower edge (two lines 15 mm apart, as drawn).
    msp.add_line(drawing(0.0, -0.6), drawing(8.0, -0.3), dxfattribs={'layer': 'S0CO3'})
    msp.add_lwpolyline([drawing(1.5, -0.9), drawing(5.0, -0.7), drawing(7.6, -0.315)], dxfattribs={'layer': 'S0CO2'})
    msp.add_lwpolyline([drawing(1.5, -0.915), drawing(5.0, -0.715)], dxfattribs={'layer': 'S0CO2'})
    msp.add_lwpolyline([drawing(x, 2.1 - 0.05 * x) for x in (-1.0, -0.5, 0.0, 0.5, 1.0)], dxfattribs={'layer': 'S0CO3'})
    # Thruster (profile block): a box from below the keel up into the hull, plus a centre line.
    side = doc.blocks.new(appendages.THRUSTER_PROFILE_BLOCK)
    side.add_lwpolyline([(-800, -2400), (800, -2400), (800, 2500), (-800, 2500)], close=True)
    side.add_line((-1600, 500), (1600, 500), dxfattribs={'linetype': 'CENTER'})
    msp.add_blockref(appendages.THRUSTER_PROFILE_BLOCK, drawing(0.0, 1.8))
    # Tank-top plan: frame ruler on the centreline and two thruster blocks at y = +-2.5 m.
    doc.blocks.new(appendages.FRAME_RULER_BLOCK).add_line((0, 0), (1000, 0))
    msp.add_blockref(appendages.FRAME_RULER_BLOCK, (X0, PLAN_CENTRE_Y))
    top = doc.blocks.new(appendages.THRUSTER_PLAN_BLOCK)
    top.add_circle((0, 0), 1000)
    for y in (2.5, -2.5):
        msp.add_blockref(appendages.THRUSTER_PLAN_BLOCK, plan(0.0, y))
    doc.saveas(path)


def step1_inputs():
    return {'program': {'schema': 'ship-cad/v1', 'components': []}, 'measurements': {}, 'guesses': {},
            'source': {'file': 'ga.dxf', 'sha256': '0' * 64}}


def test_appendages_are_read_from_ink_and_gaps_are_labelled_guesses(tmp_path):
    synthetic_ga(tmp_path / 'ga.dxf')
    inputs = appendages.add_appendages(step1_inputs(), tmp_path, 'ga.dxf')
    assert inputs['appendages']['ids'] == ['azimuth_ps', 'azimuth_sb', 'skeg_ps', 'skeg_sb']
    assert set(inputs['appendages']['not_built']) == {'rudder', 'bow_thruster', 'drop_keel'}
    # Thruster outline: the box below the stern bottom; the centre line is not material.
    outline = np.array(inputs['measurements']['azimuth_ps_outline']['value'])
    assert outline[:, 0].min() == pytest.approx(-0.8) and outline[:, 0].max() == pytest.approx(0.8)
    assert outline[:, 1].min() == pytest.approx(-0.6)
    assert outline[:, 1].max() == pytest.approx(2.1, abs=0.06)
    assert inputs['guesses']['azimuth_ps_span']['value'] == [2.25, 2.75]
    assert inputs['guesses']['azimuth_sb_span']['value'] == [-2.75, -2.25]
    # Skeg: lowest edge, closed by the keel line; it ends where the edge meets the keel.
    assert inputs['guesses']['skeg_ps_span']['value'] == [2.35, 2.65]
    skeg = np.array(inputs['measurements']['skeg_sb_outline']['value'])
    assert skeg[0].tolist() == pytest.approx([1.5, -0.6 + 0.3 * 1.5 / 8.0], abs=1e-4)
    assert skeg[1].tolist() == pytest.approx([1.5, -0.915])
    assert skeg[-1][0] == pytest.approx(7.6)
    resolved = resolve_program(inputs['program'], inputs['measurements'], inputs['guesses'])
    assert [c['id'] for c in resolved] == ['azimuth_ps', 'azimuth_sb', 'skeg_ps', 'skeg_sb']
    for component in resolved:
        assert component['geometry'] is not None
        assert component['source_labels'] == {'outline': 'traced', 'span': 'guessed'}
        assert component['status'] == 'draft_guess'


def test_display_mesh_of_one_face_hull_keeps_the_volume_and_names_parts(tmp_path):
    geometry = pytest.importorskip('vessel_reconstruction.geometry')
    trimesh = pytest.importorskip('trimesh')
    from vessel_reconstruction.display_mesh import mesh_volume_mm3, shape_mesh, write_glb

    z = np.linspace(0, 3, 60)
    sections = [{'id': f's{i}', 'x_m': 2.0 * i, 'points_yz_m': np.column_stack([s * 2 * np.sqrt(z / 3), z]).tolist()}
                for i, s in enumerate((0.6, 1.0, 0.8, 0.4))]
    shape, report = geometry.build_region_hull(sections, one_face_per_side=True)
    vertices, triangles = shape_mesh(shape, 1.0, 0.5)
    assert mesh_volume_mm3(vertices, triangles) / 1e9 == pytest.approx(report['volume_m3'], rel=2e-3)
    write_glb({'hull': (vertices, triangles)}, tmp_path / 'm.glb')
    scene = trimesh.load(tmp_path / 'm.glb')
    assert 'hull' in scene.graph.nodes
    import json
    import struct
    data = (tmp_path / 'm.glb').read_bytes()
    header = json.loads(data[20:20 + struct.unpack('<I', data[12:16])[0]])
    assert header['meshes'][0]['primitives'][0]['attributes'].keys() >= {'POSITION', 'NORMAL'}
    # glTF is Y-up: the model's height (z) is the GLB's y.
    assert scene.bounds[1][1] == pytest.approx(3000.0, abs=1.0)
