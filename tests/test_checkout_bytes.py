"""Source checkout policy must preserve frozen byte identities across platforms."""
from pathlib import Path
import subprocess


def test_python_sources_have_explicit_lf_checkout_policy():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ['git', '-C', str(root), 'check-attr', 'text', 'eol', '--',
         'src/vessel_reconstruction/provenance.py'],
        check=True, capture_output=True, text=True)
    assert ': text: auto' in result.stdout
    assert ': eol: lf' in result.stdout
