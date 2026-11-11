"""Parsed DXF documents shared inside a build step (dxf_documents.py)."""
import os

import pytest

ezdxf = pytest.importorskip('ezdxf')


def _write_drawing(path, length):
    document = ezdxf.new()
    document.modelspace().add_line((0, 0), (length, 0), dxfattribs={'layer': 'HULL'})
    document.saveas(path)


def test_documents_are_shared_only_inside_the_block(tmp_path):
    from vessel_reconstruction.dxf_documents import read_document, shared_documents

    path = tmp_path / 'lines.dxf'
    _write_drawing(path, 10)
    assert read_document(path) is not read_document(path)
    with shared_documents():
        first = read_document(path)
        assert read_document(str(path)) is first
        assert read_document(tmp_path / '.' / 'lines.dxf') is first
        with shared_documents():  # nested: the same documents
            assert read_document(path) is first
    assert read_document(path) is not first


def test_a_changed_file_is_parsed_again(tmp_path):
    from vessel_reconstruction.dxf_documents import read_document, shared_documents

    path = tmp_path / 'lines.dxf'
    _write_drawing(path, 10)
    with shared_documents():
        first = read_document(path)
        _write_drawing(path, 25)
        status = path.stat()
        os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns + 1_000_000))
        second = read_document(path)
        assert second is not first
        line = next(iter(second.modelspace()))
        assert line.dxf.end.x == 25


def test_read_dxf_gives_the_same_entities_with_and_without_sharing(tmp_path):
    from vessel_reconstruction.dxf_documents import shared_documents
    from vessel_reconstruction.ship_measure import read_dxf

    path = tmp_path / 'lines.dxf'
    _write_drawing(path, 10)
    plain = read_dxf(path)
    with shared_documents():
        assert read_dxf(path) == plain
        assert read_dxf(path, layers=['HULL']) == plain
        assert read_dxf(path, layers=['OTHER']) == []
