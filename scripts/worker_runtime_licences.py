"""Write the licence list of the bundled worker runtime (docs/WORKER_RUNTIME_LICENCES.md).

Run it with the runtime's own Python so that it lists exactly what the app would ship:

    build/worker-runtime/worker/bin/python3 -I scripts/worker_runtime_licences.py \
        --out docs/WORKER_RUNTIME_LICENCES.md

The licence text comes from each package's metadata (License-Expression, else the first
line of License, else the licence classifiers). Metadata can be incomplete; this list is an
inventory for the owner's review, not legal clearance. Native libraries that a wheel
vendors (its .dylibs folder) are listed too, because they carry their own licences.
"""
import argparse
import importlib.metadata
import json
import sys
from pathlib import Path

# Packages that need an owner decision before any distribution (docs/DEPENDENCIES_AND_RIGHTS.md).
OWNER_DECISION = {
    'pymupdf': 'AGPL-3.0 or Artifex commercial licence: distribution needs an owner decision.',
    'vtk': 'Scoped OSV exclusion for VTK 9.3.1 (GLTF loader); review before distribution.',
}
# Facts about packages whose metadata says too little; checked by hand against each
# package's own licence files in the runtime.
KNOWN = {
    'cadquery-ocp': 'Bindings for Open CASCADE Technology (libTK*), LGPL-2.1 with the OCCT '
                    'exception; the metadata declares no licence.',
    'opencv-python-headless': 'Vendors FFmpeg and codec libraries; see LICENSE-3RD-PARTY.txt '
                              'in its dist-info.',
}
# Licences with obligations that a distributor must meet (copyleft or notice terms).
COPYLEFT_WORDS = ('GPL', 'AFFERO', 'LGPL', 'MPL')
# Vendored native libraries that are GPL or LGPL by their usual upstream licence, matched by
# file-name prefix. A name match is a prompt for review, not a finding about this build.
COPYLEFT_LIBRARIES = {
    'libx264': 'GPL-2.0+', 'libx265': 'GPL-2.0+', 'libpostproc': 'GPL-2.0+ (FFmpeg)',
    'librubberband': 'GPL-2.0+', 'libavcodec': 'LGPL-2.1+ (FFmpeg)',
    'libavdevice': 'LGPL-2.1+ (FFmpeg)', 'libavfilter': 'LGPL-2.1+ (FFmpeg)',
    'libavformat': 'LGPL-2.1+ (FFmpeg)', 'libavutil': 'LGPL-2.1+ (FFmpeg)',
    'libswresample': 'LGPL-2.1+ (FFmpeg)', 'libswscale': 'LGPL-2.1+ (FFmpeg)',
    'libgnutls': 'LGPL-2.1+', 'libgmp': 'LGPL-3.0+/GPL-2.0+', 'libnettle': 'LGPL-3.0+/GPL-2.0+',
    'libhogweed': 'LGPL-3.0+/GPL-2.0+', 'libglib': 'LGPL-2.1+', 'libintl': 'LGPL-2.1+',
    'libfribidi': 'LGPL-2.1+', 'libbluray': 'LGPL-2.1+', 'libmp3lame': 'LGPL-2.0+',
    'libtasn1': 'LGPL-2.1+', 'libidn2': 'LGPL-3.0+/GPL-2.0+',
    'libfreeimage': 'GPL-2.0/GPL-3.0 or FreeImage Public License', 'libraw': 'LGPL-2.1 or CDDL-1.0',
    'libgfortran': 'GPL-3.0+ with GCC runtime exception',
    'libgcc_s': 'GPL-3.0+ with GCC runtime exception', 'libquadmath': 'LGPL-2.1+',
    'libTK': 'LGPL-2.1 with OCCT exception',
}


def declared_licence(meta) -> str:
    expression = meta.get('License-Expression')
    if expression:
        return expression.strip()
    text = (meta.get('License') or '').strip()
    if text:
        first_line = text.splitlines()[0].strip()
        return first_line[:80] + (' ...' if len(first_line) > 80 or '\n' in text else '')
    classifiers = [c.split('::')[-1].strip() for c in meta.get_all('Classifier') or []
                   if c.startswith('License ::')]
    return '; '.join(classifiers) or 'Not declared'


def vendored_libraries(distribution) -> list[str]:
    """Names of native libraries in the wheel's .dylibs folders."""
    names = set()
    for file in distribution.files or []:
        parts = Path(str(file)).parts
        if any(part.endswith('.dylibs') for part in parts[:-1]) and '.dylib' in parts[-1]:
            names.add(parts[-1])
    return sorted(names)


def copyleft_libraries(libraries: list[str]) -> list[str]:
    """`name (licence)` for each vendored library that COPYLEFT_LIBRARIES names."""
    found = {}
    for library in libraries:
        for prefix, licence in COPYLEFT_LIBRARIES.items():
            if library.startswith(prefix):
                found.setdefault(f'{prefix}* ({licence})' if prefix == 'libTK' else
                                 f'{library.split(".")[0]} ({licence})', None)
    return list(found)


def notes_for(key: str, licence: str) -> str:
    notes = [text for table in (OWNER_DECISION, KNOWN) if (text := table.get(key))]
    if any(word in licence.upper() for word in COPYLEFT_WORDS) and key not in OWNER_DECISION:
        notes.append('Copyleft terms: keep notices and meet the licence when distributing.')
    return ' '.join(notes)


def libraries_cell(libraries: list[str]) -> str:
    if not libraries:
        return '-'
    flagged = copyleft_libraries(libraries)
    text = f'{len(libraries)}'
    if flagged:
        text += '; copyleft by name: ' + ', '.join(flagged)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    runtime = Path(sys.prefix)
    manifest = json.loads((runtime / 'MARINAFRAME_RUNTIME.json').read_text())

    rows = []
    for distribution in importlib.metadata.distributions():
        meta = distribution.metadata
        name = meta['Name']
        key = name.lower().replace('_', '-')
        licence = declared_licence(meta)
        rows.append((key, name, distribution.version, licence, vendored_libraries(distribution),
                     notes_for(key, licence)))
    rows.sort()

    lines = [
        '# Worker runtime: bundled packages and licences',
        '',
        'Generated by `scripts/worker_runtime_licences.py` from the runtime that',
        '`scripts/build_worker_runtime.sh` builds; do not edit by hand. The runtime itself',
        '(about 1.2 GB) is not in Git and nothing has been distributed. Licence text is the',
        "packages' declared metadata, which can be incomplete: this is an inventory for the",
        "owner's review, not legal clearance (see `docs/DEPENDENCIES_AND_RIGHTS.md`).",
        '',
        f"- Python: CPython {manifest['python']} from python-build-standalone release",
        f"  {manifest['python_build_standalone_release']} (`{manifest['python_archive']}`,",
        f"  SHA-256 `{manifest['python_archive_sha256']}`). CPython is PSF-2.0; its",
        '  licence file, with the licences of the libraries built into it, is',
        '  `lib/python3.12/LICENSE.txt` in the runtime. The runtime also holds Tcl/Tk 9',
        '  (`lib/libtcl9*`, Tcl/Tk licence, BSD style) from the same build.',
        f"- Packages: `{manifest['lock']}` (SHA-256 `{manifest['lock_sha256']}`) and",
        f"  `{manifest['package_wheel']}` built from commit `{manifest['source_commit'][:12]}`.",
        '',
        'The column "Vendored native libraries" gives the number of libraries in the',
        "wheel's `.dylibs` folder and those whose usual upstream licence is GPL or LGPL",
        '(matched by file name: a prompt for review, not a finding about this build).',
        '',
        '| Package | Version | Declared licence | Vendored native libraries | Note |',
        '|---|---|---|---|---|',
    ]
    for _key, name, version, licence, libraries, note in rows:
        licence_cell = licence.replace('|', '/')
        lines.append(f'| {name} | {version} | {licence_cell} | {libraries_cell(libraries)} '
                     f'| {note or "-"} |')
    lines.append('')
    lines.append(f'{len(rows)} distributions.')
    args.out.write_text('\n'.join(lines) + '\n')
    print(f'wrote {args.out} ({len(rows)} distributions)')


if __name__ == '__main__':
    main()
