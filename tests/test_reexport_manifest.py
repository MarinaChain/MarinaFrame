import json

from vessel_reconstruction import reexport
from vessel_reconstruction.provenance import digest_file
from test_reexport import finished


def test_manifest_hashes_match_after_repeated_refresh(tmp_path):
    task = finished(tmp_path)
    for _ in range(2):
        reexport.refresh(task, 'r1')
        manifest = json.loads((task / 'reexport/manifest.json').read_text())
        assert 'reexport/manifest.json' not in manifest['files']
        for name, digest in manifest['files'].items():
            assert digest_file(task / name) == digest
