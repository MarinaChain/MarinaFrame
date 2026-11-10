"""Load the tool definitions shared with the Rust controller."""
import json
from importlib.resources import files


def catalog():
    """Return a fresh copy of the packaged catalog."""
    return json.loads(files("vessel_reconstruction").joinpath("tool_catalog.json").read_text(encoding="utf-8"))
