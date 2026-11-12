"""Offline synthetic GA tools. Does not import or call a reader."""
import argparse
import json
from pathlib import Path

from .generate import write_suite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    generate = commands.add_parser('generate')
    generate.add_argument('--out', type=Path, required=True)
    generate.add_argument('--seed', type=int, default=17)
    generate.add_argument('--count', type=int, default=6)
    scoring = commands.add_parser('score')
    scoring.add_argument('--truth', type=Path, required=True)
    scoring.add_argument('--reading', type=Path, required=True)
    scoring.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'generate':
        write_suite(args.out, args.seed, args.count)
    else:
        from .score import score

        result = score(json.loads(args.truth.read_text()), json.loads(args.reading.read_text()))
        with args.out.open('x') as stream:
            stream.write(json.dumps(result, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
