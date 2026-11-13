"""Run a record-only draft concept graph with a persistent input-hash cache.

Seed from explicit JSON inputs with --config, or resume/edit an existing record
with --record. All source data belongs in ignored work directories.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from vessel_reconstruction.design_record import DesignRecord
from vessel_reconstruction.design_loop import create_record, run_pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--config', type=Path)
    source.add_argument('--record', type=Path)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    record = create_record(json.loads(args.config.read_text())) if args.config else DesignRecord.load(args.record)
    result, receipt = run_pipeline(record, args.cache)
    result.save(args.out)
    args.receipt.write_text(json.dumps(asdict(receipt), indent=2) + '\n')
    print(json.dumps(asdict(receipt), sort_keys=True))


if __name__ == '__main__':
    main()
