"""Regression for the exact input boundary behind the temporary VTK GLTF exclusion."""
import pytest

from vessel_reconstruction.resources import ResourceLimitError, inspect_source, source_extension


@pytest.mark.parametrize('payload', [b'glTF\x02\x00\x00\x00' + b'\x00'*100,
                                   b'{"asset":{"version":"2.0"},"meshes":[]}',
                                   b'# vtk DataFile Version 3.0\n'])
def test_vtk_formats_are_not_supported_sources(tmp_path, payload):
    # An attacker-controlled extension does not route unsupported contents to VTK.
    path = tmp_path/'disguised.png'
    path.write_bytes(payload)
    with pytest.raises(ResourceLimitError):
        source_extension(payload[:16])
    with pytest.raises(ResourceLimitError):
        inspect_source(path, {'file': path.name})
