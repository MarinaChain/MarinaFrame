"""Structure display meshes: plate slabs and swept stiffener sections with exact volumes."""
import json
from pathlib import Path
import struct

import numpy as np
import pytest

from vessel_reconstruction.exports.hydrostatics import signed_volume
from vessel_reconstruction.structure import display


def volume(triangles) -> float:
    return abs(signed_volume(triangles))


def test_plate_is_a_slab_of_its_thickness():
    # A floor in the plane x = 5: 2 m wide, 1 m high, with many collinear points on its edges.
    edge = [(5.0, y, 0.0) for y in np.linspace(-1, 1, 50)]
    contour = edge + [(5.0, 1.0, 1.0), (5.0, -1.0, 1.0)]
    triangles = display.plate_triangles(contour, 0.010)
    assert volume(triangles) == pytest.approx(2 * 1 * 0.010)
    assert np.ptp(triangles[:, :, 0]) == pytest.approx(0.010)
    # Thinned: the 50 collinear edge points are not all kept.
    assert len(triangles) < 50


def test_concave_plate_keeps_its_area():
    contour = [(0, 0, 2), (2, 0, 2), (2, 1, 2), (1, 1, 2), (1, 2, 2), (0, 2, 2)]  # an L in the deck plane
    assert volume(display.plate_triangles(contour, 0.008)) == pytest.approx(3 * 0.008)


@pytest.mark.parametrize("profile, area", [
    ({"kind": "FlatBar", "height_mm": 100, "web_mm": 8}, 0.1 * 0.008),
    ({"kind": "TBar", "height_mm": 200, "web_mm": 8, "flange_width_mm": 50, "flange_thickness_mm": 10},
     0.19 * 0.008 + 0.05 * 0.010),
    ({"kind": "LBar", "height_mm": 120, "web_mm": 8, "flange_width_mm": 60, "flange_thickness_mm": 8},
     0.112 * 0.008 + 0.06 * 0.008),
])
def test_stiffener_is_its_section_swept_along_the_trace(profile, area):
    trace = [(0, 0, 0), (2, 0, 0), (4, 0, 0)]
    triangles = display.stiffener_triangles(trace, profile, (0, 0, 1))
    assert volume(triangles) == pytest.approx(4 * area, rel=1e-6)
    # The web stands up from the plate along the web direction.
    assert triangles[:, :, 2].min() == pytest.approx(0) and triangles[:, :, 2].max() == pytest.approx(profile["height_mm"] / 1000)


def test_member_groups_follow_the_labels():
    assert display.member_group({"label": "bottom_shell", "contour": [1]}) == "shell"
    assert display.member_group({"label": "inner_bottom", "contour": [1]}) == "deck"
    assert display.member_group({"label": "transverse_bulkhead", "contour": [1]}) == "bulkhead"
    assert display.member_group({"label": "floor", "contour": [1]}) == "primary"
    assert display.member_group({"label": "frame", "trace": [1], "profile": {"kind": "FlatBar"}}) == "stiffener"
    assert display.member_group({"label": "deck_girder", "trace": [1], "profile": {"kind": "FlatBar"}}) == "primary"


def test_structure_glb_has_one_node_per_group_with_labelled_members(tmp_path):
    members = [
        {"member_id": "p1", "label": "floor", "contour": [(5, -1, 0), (5, 1, 0), (5, 1, 1), (5, -1, 1)],
         "thickness_mm": 8.0, "thickness_source": "printed"},
        {"member_id": "s1", "label": "frame", "trace": [(5, 1, 0), (5, 1, 1)], "web_direction": (0, -1, 0),
         "profile": {"name": "HP 100x6", "kind": "BulbFlat", "height_mm": 100, "web_mm": 6},
         "thickness_mm": 6.0, "thickness_source": "guessed"},
    ]
    counts = display.write_structure_glb(members, tmp_path / "s.glb")
    assert counts == {"primary": 1, "stiffener": 1}
    data = (tmp_path / "s.glb").read_bytes()
    gltf = json.loads(data[20:20 + struct.unpack_from("<I", data, 12)[0]])
    extras = {mesh["extras"]["group"]: mesh["extras"] for mesh in gltf["meshes"]}
    assert extras["stiffener"]["members"][0] == {"id": "s1", "label": "frame", "thickness_mm": 6.0,
                                                 "thickness_source": "guessed", "profile": "HP 100x6"}
    assert all(e["kind"] == "structure" and e["engineering_approved"] is False for e in extras.values())
    assert {node.get("name") for node in gltf["nodes"]} >= {"structure_primary", "structure_stiffener"}


def test_app_tokens_use_the_same_steel_palette():
    css = (Path(__file__).resolve().parents[1] / "app/ui/styles.css").read_text()
    for group, (_, colour, _) in display.MEMBER_GROUPS.items():
        assert f"--steel-{group}: {colour};" in css, group
