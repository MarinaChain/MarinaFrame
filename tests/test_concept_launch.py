"""Concept-preview survey launch (benchmarks/concept_launch): the offsets, the mesh cuts, and
(cad tier) that volumes match the CadQuery model and every region lies on its sheet."""
from __future__ import annotations

import math

import numpy as np
import pytest

from benchmarks.concept_launch import CONCEPT_LABEL, SHEET_LABEL
from benchmarks.concept_launch import model as M
from benchmarks.concept_launch import sheets as S


# --- quick tier: offsets and cuts ---------------------------------------------------------------

def test_sections_run_from_keel_to_deck_on_the_starboard_half():
    for x in M.LOFT_X_M:
        points = M.section_points(x)
        assert points[0, 0] == pytest.approx(0.0, abs=1e-9)
        assert points[0, 1] == pytest.approx(M.keel_height(x))
        assert points[-1, 1] == pytest.approx(M.DEPTH_M)
        assert np.all(points[:, 0] >= 0) and np.all(np.diff(points[:, 1]) >= -1e-12)
        assert points[:, 0].max() <= M.HALF_BEAM_M + 1e-9


def test_body_plan_stations_are_loft_stations():
    # The body plan is drawn from the loft stations, so a section region shows the exact section.
    for _, x in M.BODY_PLAN_STATIONS:
        assert any(abs(x - loft_x) < 1e-9 for loft_x in M.LOFT_X_M)


def test_midship_section_area_is_close_to_its_box():
    area = M.section_area(M.LENGTH_M / 2)
    box = 2 * M.HALF_BEAM_M * M.DEPTH_M
    assert 0.85 * box < area < box


def _box_triangles(x0, x1, y0, y1, z0, z1) -> np.ndarray:
    corners = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], dtype=float)
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
             (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    return corners[np.array(faces)]


def test_silhouette_of_a_box_is_its_rectangle():
    outline = np.array(S.silhouette(_box_triangles(1, 4, -2, 2, 0.5, 3), 0, 2))
    assert outline[:, 0].min() == pytest.approx(1) and outline[:, 0].max() == pytest.approx(4)
    assert outline[:, 1].min() == pytest.approx(0.5) and outline[:, 1].max() == pytest.approx(3)


def test_plane_cut_of_a_box_is_a_closed_rectangle():
    chains = S.chain_segments(S.plane_segments(_box_triangles(0, 2, -1, 1, 0, 1), 2, 0.5), 0, 1)
    assert len(chains) == 1
    points = np.array(chains[0])
    assert math.dist(chains[0][0], chains[0][-1]) < 1e-6
    assert points[:, 0].min() == pytest.approx(0) and points[:, 1].max() == pytest.approx(1)


def test_regions_are_clipped_to_the_sheet():
    sheet = S.Sheet("ga", "x.png", "Test", 1)
    sheet.add_region("item", "plan", [-50, -50, 100, 100])
    sheet.add_region("edge", "plan", [3900, 2700, 4100, 2900])
    width, height = S.SHEET_PX
    for _, _, (left, top, right, bottom) in sheet.regions:
        assert 0 <= left < right <= width and 0 <= top < bottom <= height


def test_labels_say_concept_preview():
    assert "Concept preview" in CONCEPT_LABEL and "not a reading of real drawings" in CONCEPT_LABEL
    assert SHEET_LABEL.startswith("CONCEPT PREVIEW")


# --- cad tier: the whole model and its sheets ---------------------------------------------------

@pytest.fixture(scope="module")
def built():
    pytest.importorskip("cadquery")
    from benchmarks.concept_launch import run_folder

    model, tank_model, table = run_folder.build_model()
    sheet_list = S.draw_all(model, run_folder.SHEET_FILES)
    return run_folder, model, tank_model, table, sheet_list


@pytest.mark.cad
def test_hull_volume_matches_the_offsets(built):
    _, model, _, _, _ = built
    xs = np.linspace(0, M.BOW_END_X_M, 600)
    offsets = float(np.trapezoid([M.section_area(x) for x in xs], xs))
    assert model.parts["hull"].solid.Volume() == pytest.approx(offsets, rel=0.005)


@pytest.mark.cad
def test_tank_capacities_match_the_cad_solids(built):
    _, model, _, _, _ = built
    assert len(model.capacity) == len(M.TANKS)
    for tank_id, row in model.capacity.items():
        assert row["volume_100_m3"] == pytest.approx(model.parts[tank_id].solid.Volume(), rel=0.005)
        assert row["engineering_approved"] is False


@pytest.mark.cad
def test_displacement_matches_the_underwater_solid(built):
    _, model, _, table, _ = built
    hull = model.parts["hull"].solid
    design = next(row for row in table if row["draft_m"] == M.DESIGN_DRAFT_M)
    below = hull.intersect(M._box(-1, 30, -5, 5, -1, M.DESIGN_DRAFT_M)).Volume()
    assert design["volume_m3"] == pytest.approx(below, rel=1e-9)
    assert design["displacement_t"] == pytest.approx(below * M.SEA_WATER_T_M3)
    volumes = [row["volume_m3"] for row in table]
    assert volumes == sorted(volumes)


@pytest.mark.cad
def test_every_item_has_regions_inside_its_sheet(built):
    run_folder, model, _, _, sheet_list = built
    width, height = S.SHEET_PX
    for sheet in sheet_list:
        assert sheet.finish().size == S.SHEET_PX
        for _, _, (left, top, right, bottom) in sheet.regions:
            assert 0 <= left < right <= width and 0 <= top < bottom <= height
    regions = run_folder.regions_by_item(sheet_list)
    for part in model.parts.values():
        assert part.id in regions, part.id
    for station_id, _ in M.BODY_PLAN_STATIONS:
        assert [r["view"] for r in regions[station_id]] == ["body plan"]


@pytest.mark.cad
def test_part_regions_contain_the_drawn_part(built):
    # A region box holds the projection of the part's mesh through the view's transform.
    run_folder, model, _, _, sheet_list = built
    ga = next(sheet for sheet in sheet_list if sheet.key == "ga")
    for item, view, (left, top, right, bottom) in ga.regions:
        if item not in ("house_t1", "wheelhouse", "rudder", "mast") or view != "profile":
            continue
        vertices = model.triangles[item].reshape(-1, 3)
        cols, rows = zip(*(S.GA_PROFILE.px(x, z) for x, _, z in vertices))
        assert left <= min(cols) and max(cols) <= right and top <= min(rows) and max(rows) <= bottom


@pytest.mark.cad
def test_records_are_valid_and_two_parts_are_guessed(built):
    from vessel_reconstruction import source_record

    run_folder, model, _, _, sheet_list = built
    regions = run_folder.regions_by_item(sheet_list)
    records = {part.id: run_folder.part_record(part, regions) for part in model.parts.values()}
    for record in records.values():
        source_record.validate(record)
    guessed = sorted(part_id for part_id, record in records.items() if record["kind"] == "guessed")
    assert guessed == ["tank_fw1", "wheelhouse"]
    assert {"part": "house_t1"} in records["wheelhouse"]["inputs"]


@pytest.mark.cad
def test_every_steel_member_is_drawn_and_grouped(built):
    from benchmarks.concept_launch import structure as T
    from vessel_reconstruction.structure.display import group_meshes

    run_folder, model, _, _, sheet_list = built
    regions = run_folder.regions_by_item(sheet_list)
    members = model.members
    assert len({m["member_id"] for m in members}) == len(members)
    for member in members:
        assert any(r["sheet"] == run_folder.SHEET_FILES["construction"] for r in regions[member["member_id"]])
        T.kind_of(member)
    # Bulkheads, web frames, the girder and the inner bottom are also parts with the same id.
    part_ids = set(model.parts)
    assert {"bhd_fr07", "web_fr12", "centre_girder", "inner_bottom"} <= part_ids & {m["member_id"] for m in members}
    groups = set(group_meshes(members))
    assert {"bulkhead", "deck", "primary", "stiffener"} <= groups


@pytest.mark.cad
def test_tanks_stand_at_different_heights(built):
    _, model, _, _, _ = built
    tops = {round(model.parts[spec.id].solid.BoundingBox().zmax, 1) for spec in M.TANKS}
    assert len(tops) >= 3
