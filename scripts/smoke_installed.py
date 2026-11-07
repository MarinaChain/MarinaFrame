"""Exercise the installed wheel, with isolated Python imports outside the source tree."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    with tempfile.TemporaryDirectory(prefix='marinaframe-installed-') as temporary:
        def run(name, command):
            started = time.monotonic()
            result = subprocess.run(command, cwd=temporary, capture_output=True, text=True, timeout=240)
            (out/f'{name}.txt').write_text(result.stdout + result.stderr)
            rows.append({'name': name, 'command': command, 'exit_code': result.returncode,
                         'elapsed_seconds': time.monotonic()-started})
            if result.returncode:
                raise RuntimeError(f'{name} failed: see its retained log')
            return result.stdout
        run('import', [sys.executable, '-I', '-c',
            'import vessel_reconstruction as v; '
            'print(v.__version__,v.__file__); '
            'assert "site-packages" in v.__file__'])
        run('pip-check', [sys.executable, '-I', '-m', 'pip', 'check'])
        run('help', [sys.executable, '-I', '-m', 'vessel_reconstruction', '--help'])
        run('example', [sys.executable, str(repo/'examples/make_development_example.py')])
        cli = [sys.executable, '-I', '-m', 'vessel_reconstruction']
        run_dir = out/'run'
        run('reconstruct', cli + ['reconstruct', str(repo/'data/examples/development/spec.json'), '--out', str(run_dir)])
        run('verify', cli + ['verify', str(run_dir)])
    (out/'commands.json').write_text(json.dumps(rows, indent=2))
    print(json.dumps({'checks': len(rows), 'all_passed': True, 'output': str(out)}, indent=2))


if __name__ == '__main__':
    main()
