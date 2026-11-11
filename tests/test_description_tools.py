"""Read phase survives reopening and does not build or select geometry."""
from draft_fixture import draft_drawing
from vessel_reconstruction.agent_tools import DomainTools


def test_tiny_named_view_expands_to_a_usable_crop_with_warning(tmp_path):
    spec, _ = draft_drawing(tmp_path / "input")
    task = tmp_path / "task"
    task.mkdir()
    tools = DomainTools(task, spec)
    observed = tools.execute("describe_views", {"views": [
        {"view_id": "body", "kind": "body", "region_px": [0, 0, 1, 1]}]})
    assert observed["ok"], observed
    assert observed["warnings"][0]["field"] == "views.body.region_px"
    assert tools.describe()["description_next_view"]["view_id"]


def test_description_extra_outer_fields_are_metadata_not_refusals(tmp_path):
    spec, _ = draft_drawing(tmp_path / "input")
    task = tmp_path / "task"
    task.mkdir()
    tools = DomainTools(task, spec)
    result = tools.execute("describe_vessel", {"description": {"principal": {"scale": "1:100"}},
                                               "notes": "extra model notes", "reason": "read sheet"})
    assert result["ok"], result
    description = tools.describe()["vessel_description"]
    assert description["outer_metadata"]["notes"] == "extra model notes"
    assert "principal.scale" in {w["field"] for w in description["warnings"]}
    assert tools.execute("describe_vessel", {"description": None})["ok"]


def test_body_panels_share_first_setup_without_more_model_requests(tmp_path):
    spec_path, spec = draft_drawing(tmp_path / "input")
    task = tmp_path / "task"
    task.mkdir()
    tools = DomainTools(task, spec_path)
    tools.execute("survey_sheet", {})
    described = tools.execute("describe_views", {"views": [
        {"view_id": f"panel-{i}", "kind": "body", "region_px": s["roi_px"]}
        for i, s in enumerate(spec["sections"])]})
    evidence = tools.describe()["description_next_view"]["view_id"]
    first = spec["sections"][0]
    result = tools.execute("propose_sheet_setup", {"view": "body", "region_px": first["roi_px"],
        "pixels_per_metre": 60., "grid_spacing_m": .5, "centreline_px": 20., "baseline_px": 210.,
        "evidence_view_id": evidence, "scale_claim": "shared panel grid", "reason": "one body family"})
    assert result["ok"], result
    state = tools.describe()
    assert state["description_phase"] == "vessel"
    setups = list(tools.state["sheet_setups"].values())
    assert len(setups) == 3
    assert [s["centreline_px"] for s in setups] == [20., 220., 420.]
    assert all(s["pixels_per_metre"] == 60. for s in setups)


def test_body_family_can_supply_shared_setup_and_panel_datums(tmp_path):
    spec_path, spec = draft_drawing(tmp_path / "input")
    task = tmp_path / "task"
    task.mkdir()
    tools = DomainTools(task, spec_path)
    tools.execute("survey_sheet", {})
    result = tools.execute("describe_views", {"views": [{"view_id": "body", "kind": "body",
        "region_px": [0, 0, 600, 230], "setup": {"pixels_per_metre": 60., "grid_spacing_m": .5},
        "panels": [{"region_px": s["roi_px"], "centreline_px": s["calibration"]["centerline_px"],
                    "baseline_px": 210.} for s in spec["sections"]]}]})
    assert result["ok"], result
    assert tools.describe()["description_phase"] == "vessel"
    assert len(tools.state["sheet_setups"]) == 3


def test_description_phase_persists_and_setup_mismatch_is_advisory(tmp_path):
    spec, _ = draft_drawing(tmp_path / "input")
    task = tmp_path / "task"
    task.mkdir()
    tools = DomainTools(task, spec)
    assert tools.describe()["description_phase"] == "survey"
    surveyed = tools.execute("survey_sheet", {"phase1_only": True})
    assert surveyed["ok"], surveyed
    assert surveyed["view"]["view_id"]
    assert tools.describe()["description_phase"] == "views"
    described = tools.execute("describe_views", {"views": [
        {"view_id": "body", "kind": "body", "region_px": [0, 0, 600, 240], "halves": "separate station panels"},
        {"view_id": "title", "kind": "title_block", "region_px": [0, 0, 200, 20]}]})
    assert described["ok"], described
    next_view = tools.describe()["description_next_view"]
    assert next_view["kind"] == "body"
    setup = tools.execute("propose_sheet_setup", {"view": "body", "region_px": [0, 0, 600, 240],
        "pixels_per_metre": 60., "grid_spacing_m": 1., "centreline_px": 4., "baseline_px": 211.,
        "evidence_view_id": next_view["view_id"], "scale_claim": "Read grid", "reason": "Read body view"})
    assert setup["ok"], setup
    assert setup["setup"]["warnings"]
    assert tools.describe()["description_phase"] == "vessel"
    result = tools.execute("describe_vessel", {"description": {"principal": {
        "beam": {"value": 99., "source": "ai_inferred"}}, "form": {"type": "displacement"}}})
    assert result["ok"], result
    assert result["warnings"]
    reopened = DomainTools(task, spec)
    state = reopened.describe()
    assert state["description_phase"] == "complete"
    assert state["vessel_description"]["principal"]["beam"]["value"] == 99.
    assert state["current_candidate"] is None
    assert state["selected_count"] == 0
    assert (task / "domain" / "vessel.json").is_file()
