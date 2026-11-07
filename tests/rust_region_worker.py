"""Worker shim for the Rust region-pipeline tests (rust-control/tests/region_pipeline.rs).

It runs the real rust_worker protocol and real DomainTools without any
injection. Its only extra command writes the multi-piece drawing:

  make-drawing DIR   write tests/region_fixture.py's drawing and spec.json into DIR
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from region_fixture import write

from vessel_reconstruction import rust_worker


def main(argv: list[str]) -> int:
    if argv[:1] == ["make-drawing"]:
        write(Path(argv[1]))
        return 0
    if argv[:2] == ["-m", "vessel_reconstruction.rust_worker"]:
        argv = argv[2:]
    return rust_worker.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
