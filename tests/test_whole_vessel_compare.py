"""Build-folder comparison (benchmarks/gunnerus/whole_vessel_compare.py), synthetic folders."""
import json

from benchmarks.gunnerus.whole_vessel_compare import differences

STEP = "ISO-10303-21;\nHEADER;\nFILE_NAME('part.step','{stamp}');\nENDSEC;\nDATA;\n#1 = CARTESIAN_POINT('',({x},0.));\nENDSEC;\n"


def _run(root, stamp, x, seconds, extra=None):
    (root / 'whole_vessel').mkdir(parents=True)
    (root / 'whole_vessel' / 'part.step').write_text(STEP.format(stamp=stamp, x=x))
    record = {'seconds': seconds, 'hull_source': str(root / 'hull' / 'model.brep'), 'volume_m3': 1.5,
              'process': {'pid': seconds}}
    (root / 'assembly.json').write_text(json.dumps(record))
    (root / 'mesh.glb').write_bytes(b'glTF' + bytes([1, 2, 3]))
    (root / 'build.log').write_text(f'took {seconds} s')
    for name, text in (extra or {}).items():
        (root / name).write_text(text)
    return root


def test_timing_header_and_paths_are_not_differences(tmp_path):
    before = _run(tmp_path / 'before', '2026-11-11T10:00:00', '1.', 300)
    after = _run(tmp_path / 'after', '2026-11-11T11:00:00', '1.', 200)
    assert differences(before, after) == (3, [])


def test_geometry_and_missing_files_are_differences(tmp_path):
    before = _run(tmp_path / 'before', 'a', '1.', 300, extra={'only.json': '{}'})
    after = _run(tmp_path / 'after', 'a', '1.000000000001', 300)
    compared, differ = differences(before, after)
    assert compared == 4
    assert differ == ['only.json: only in before', 'whole_vessel/part.step: differs']
