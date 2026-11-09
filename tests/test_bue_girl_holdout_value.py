"""Round-12 checks without drawings, private truth, or model calls."""
import hashlib
from pathlib import Path


FROZEN = {
    'src/vessel_reconstruction/body_plan_reader.py': '327c9f141876dc1945383ebe35023b6e7baaacc34306c5eecf26ffb16ba94e11',
    'src/vessel_reconstruction/body_plan_crossings.py': 'c6553371691121cd934b0991f273f9ff3a41963d46fd4238034f818aaf6fcf97',
    'src/vessel_reconstruction/body_plan_identity.py': 'ba738892696025364c3a58664bdf3fbf46e3c7d1a72df7eca31bcc441e9a0c34',
    'benchmarks/balclutha/crossing_value.py': 'bafb3ac55a69046cbf3fafcdd02f63889a34a69b064917b8798315ad4c9a4ddf',
}


def test_reader_matches_the_frozen_checkpoint():
    root = Path(__file__).resolve().parents[1]
    for name, digest in FROZEN.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
