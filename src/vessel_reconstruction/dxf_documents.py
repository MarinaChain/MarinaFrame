"""Parsed DXF documents shared by the readers of one build step.

A whole-vessel build reads the same large drawings several times (the Gunnerus GA, 56 MB, four
times in step 1; the lines plan, 45 MB, twice in each step), and each parse takes 4 to 7 s.
Inside a ``shared_documents()`` block, ``read_document`` parses each file once and gives the same
document to every reader. The readers only read (queries, virtual entities, paths); none of
them changes a document. Outside a block every call parses the file again, as before.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

# (resolved path, size, modification time) -> parsed document, inside a block; None outside.
_documents: dict | None = None


@contextmanager
def shared_documents():
    """Parse each DXF file once inside this block (see the module docstring)."""
    global _documents
    outer = _documents
    if outer is None:
        _documents = {}
    try:
        yield
    finally:
        _documents = outer


def read_document(path: str | Path):
    """The parsed ezdxf document of ``path`` (``ezdxf.readfile``). Callers must not change it."""
    import ezdxf

    if _documents is None:
        return ezdxf.readfile(str(path))
    resolved = Path(path).resolve()
    status = resolved.stat()
    # A changed file (size or modification time) is parsed again.
    key = (str(resolved), status.st_size, status.st_mtime_ns)
    if key not in _documents:
        _documents[key] = ezdxf.readfile(str(path))
    return _documents[key]
