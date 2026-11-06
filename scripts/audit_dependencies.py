"""Check the pinned public dependency names/versions against OSV. No application data sent."""
import argparse
import datetime
import json
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, default=Path('requirements-linux-py312.lock'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--scope-exclusions', type=Path, default=Path('docs/dependency-scope-exclusions.json'))
    args = parser.parse_args()
    packages = [line.split()[0].split('==') for line in args.lock.read_text().splitlines()
                if line.strip() and not line.startswith('#')]
    queries = [{'package': {'name': name, 'ecosystem': 'PyPI'}, 'version': version} for name, version in packages]
    report = {'time_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'database': 'OSV', 'scope': 'Pinned Python versions only; not native libraries or a comprehensive audit'}
    try:
        request = urllib.request.Request('https://api.osv.dev/v1/querybatch',
            data=json.dumps({'queries': queries}).encode(), headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read(4_000_000))
        results = data['results']
        if len(results) != len(packages):
            raise ValueError('Incomplete database response')
        report.update(status='completed', checked=len(packages), findings=[
            {'package': name, 'version': version, 'ids': [entry['id'] for entry in result.get('vulns', [])]}
            for (name, version), result in zip(packages, results) if result.get('vulns')])
        exclusions = json.loads(args.scope_exclusions.read_text()) if args.scope_exclusions.exists() else []
        today = datetime.datetime.now(datetime.timezone.utc).date()
        valid_exclusions = {(row['package'].lower(), row['version'], row['id']): row
                            for row in exclusions if datetime.date.fromisoformat(row['review_by']) >= today}
        report['scope_exclusions'] = []
        report['unresolved'] = []
        for finding in report['findings']:
            for identifier in finding['ids']:
                match = valid_exclusions.get((finding['package'].lower(), finding['version'], identifier))
                if match:
                    report['scope_exclusions'].append(match)
                else:
                    report['unresolved'].append({**finding, 'ids': [identifier]})
        exit_code = 1 if report['unresolved'] else 0
    except Exception as exc:
        report.update(status='unavailable', error_type=type(exc).__name__)
        exit_code = 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
