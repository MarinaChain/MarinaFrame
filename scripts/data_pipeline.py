"""Validate, assemble and review explicitly authorized annotation datasets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from vessel_reconstruction.dataset_pipeline import build_dataset, review_packet, validate_annotation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema', type=Path, required=True)
    parser.add_argument('--asset-root', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    validate = commands.add_parser('validate')
    validate.add_argument('annotations', type=Path, nargs='+')
    validate.add_argument('--out', type=Path, required=True)
    build = commands.add_parser('build')
    build.add_argument('--manifest', type=Path, required=True)
    build.add_argument('--out', type=Path, required=True)
    build.add_argument('--allow-provisional', action='store_true')
    review = commands.add_parser('review')
    review.add_argument('--manifest', type=Path, required=True)
    review.add_argument('--out', type=Path, required=True)
    review.add_argument('--audience', choices=['local', 'release'], default='local')
    args = parser.parse_args()
    if args.command == 'validate':
        rows = [validate_annotation(path, args.asset_root, args.schema) for path in args.annotations]
        result = {'valid': all(row['valid'] for row in rows), 'documents': len(rows), 'results': rows}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open('x') as handle:
            json.dump(result, handle, indent=2, allow_nan=False)
            handle.write('\n')
        print(json.dumps({'valid': result['valid'], 'documents': len(rows)}))
        return 0 if result['valid'] else 1
    if args.command == 'build':
        result = build_dataset(args.manifest, args.asset_root, args.schema, args.out,
                               allow_provisional=args.allow_provisional)
        print(json.dumps({key: result[key] for key in ('dataset_sha256', 'items', 'training_rows', 'gold_annotation_documents')}))
        return 0
    result = review_packet(args.manifest, args.asset_root, args.schema, args.out, audience=args.audience)
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
