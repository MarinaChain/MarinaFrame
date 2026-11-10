"""Names of the fixed files written by a build transaction."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Artifact:
    name: str
    geometry: bool = False
    required: bool = False
    draft_name: str | None = None


ARTIFACTS = {
    "result": Artifact("result.json", required=True),
    "input_spec": Artifact("input_spec.json", required=True),
    "replay_spec": Artifact("replay_spec.json", required=True),
    "submitted_spec": Artifact("submitted_spec.json"),
    "table_reading": Artifact("table_reading.json"),
    "extracted_sections": Artifact("extracted_sections.json"),
    "mesh": Artifact("mesh.json", geometry=True),
    "cad_sections": Artifact("cad_sections.json", geometry=True),
    "step": Artifact("model.step", geometry=True, draft_name="model-draft.step"),
    "stl": Artifact("model.stl", geometry=True, draft_name="model-draft.stl"),
    "iges": Artifact("model.iges", geometry=True, draft_name="model-draft.iges"),
    "3dm": Artifact("model.3dm", geometry=True, draft_name="model-draft.3dm"),
    "manifest": Artifact("manifest.json"),
    "transaction": Artifact("transaction.json"),
    # These templates describe evidence whose names depend on the input or source tree.
    "source": Artifact("{role}{extension}"),
    "preview": Artifact("{role}_preview.png"),
    "implementation": Artifact("implementation_source/vessel_reconstruction/{module}.py"),
}

GEOMETRY_NAMES = frozenset(name for artifact in ARTIFACTS.values() if artifact.geometry
                           for name in (artifact.name, artifact.draft_name) if name)
REQUIRED_NAMES = frozenset(artifact.name for artifact in ARTIFACTS.values() if artifact.required)
DRAFT_NAMES = {key: artifact.draft_name for key, artifact in ARTIFACTS.items() if artifact.draft_name}
