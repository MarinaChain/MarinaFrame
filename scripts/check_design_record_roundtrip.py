"""Check Python -> Rust -> Python canonical JSON equality for the public fixture.

Build the Rust example first. No subprocess timeout is imposed on our own code.
"""
import argparse
from pathlib import Path
import subprocess

from vessel_reconstruction.design_record import DesignRecord


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-binary", type=Path, required=True)
    parser.add_argument("--record", type=Path, default=Path("tests/fixtures/design_record/kvlcc2.json"))
    args = parser.parse_args()
    original = DesignRecord.load(args.record).to_json()
    result = subprocess.run([str(args.rust_binary.resolve())], input=original, text=True,
                            capture_output=True, check=True)
    restored = DesignRecord.loads(result.stdout).to_json()
    if restored != original:
        raise ValueError("Cross-language canonical JSON differs")
    print(f"PASS: Python -> Rust -> Python identical canonical JSON ({len(original.encode('utf-8'))} bytes)")


if __name__ == "__main__":
    main()
