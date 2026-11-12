"""Private process entry for trusted part builders; never used for model-written code."""
from __future__ import annotations

import pickle
import sys
from pathlib import Path


def main() -> None:
    folder, index = Path(sys.argv[1]), sys.argv[2]
    # The parent creates these objects in a private TemporaryDirectory. No drawing,
    # model-written code, or external file is accepted as a pickle payload.
    work, pieces = pickle.loads((folder / f'{index}.request').read_bytes())
    from .progress import report

    replies = []
    for part_index, piece in enumerate(pieces, 1):
        report(f'Building independent parts ({index})', part_index, len(pieces))
        try:
            replies.append((True, work(piece)))
        except Exception as error:
            replies.append((False, error))
            break
    (folder / f'{index}.reply').write_bytes(pickle.dumps(replies))


if __name__ == '__main__':
    main()
