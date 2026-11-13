"""Atomic task-level derived refresh. Sealed build evidence is read-only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from .exports.package import _exchange_directories, export_draft
from .exports.source import load_build, read_json
from .file_lock import try_lock_exclusive, unlock
from .provenance import digest_file, sync_directory, sync_file, write_json
from .source_record import component_record, unknown, validate

MAX_FILES = 20_000
MAX_BYTES = 8 * 1024 ** 3
FINISHED = {'awaiting_human_review', 'draft_not_verified', 'completed'}


def _checkpoint(phase: str) -> None:
    """Natural operation boundaries (also used for failure-injection tests)."""


def _inventory(root: Path) -> dict[str, str]:
    files = {}
    size = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError('Run contains a symbolic link.')
            if path.is_dir():
                continue
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError('Run contains a non-regular file.')
            size += path.stat().st_size
            if len(files) >= MAX_FILES or size > MAX_BYTES:
                raise ValueError('Run exceeds refresh limits.')
            files[path.relative_to(root).as_posix()] = digest_file(path)
    return files


def _record(item: dict, *, component: bool = False) -> dict:
    existing = item.get('source_record')
    if existing is not None:
        return validate(existing)
    if component:
        return component_record(item.get('provenance') or {})
    return unknown('This older run did not record the source region.')


def _records(stage: Path, build) -> None:
    for folder in ('sources', 'review', 'reexport'):
        (stage / folder).mkdir(exist_ok=True)
    sections = {str(s['id']): _record(s) for s in build.sections}
    components = {}
    execution = stage / 'whole_vessel/execution.json'
    if execution.is_file():
        for part in read_json(execution).get('result', {}).get('components', []):
            components[str(part['id'])] = _record(part, component=True)
    write_json(stage / 'sources/records.json', {
        'schema': 'marinaframe.run-source-records.v1',
        'revision': build.revision_id,
        'result_file': (build.build_dir / 'result.json').relative_to(stage).as_posix(),
        'result_sha256': digest_file(build.build_dir / 'result.json'),
        'sections': sections, 'components': components})
    defaults = {
        'sources/sheets.json': {'schema': 'marinaframe.run-sheets.v1', 'sheets': []},
        'review/part_reviews.json': {},
        'presentation.json': {'schema': 'marinaframe.presentation.v1',
                              'whole_vessel_first': False, 'section_lines': True,
                              'see_through': False, 'credit': None, 'note': None},
    }
    for relative, value in defaults.items():
        if not (stage / relative).exists():
            write_json(stage / relative, value)


def _assert_lock(task: Path, descriptor: int) -> None:
    """The published path must name our locked inode, not a copied reservation."""
    held = os.fstat(descriptor)
    named = (task / 'controller.lock').stat(follow_symlinks=False)
    if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
        raise RuntimeError('Controller lock identity changed.')
    # A separate open file description must be excluded, including in this process.
    with (task / 'controller.lock').open('r+b') as probe:
        try:
            try_lock_exclusive(probe)
        except BlockingIOError:
            return
        unlock(probe)
    raise RuntimeError('Controller lock ownership was lost.')


def _convert_step(step: Path, destination: Path, formats: list[str]) -> dict[str, Path]:
    """Translate existing STEP faces; never reconstruct sections or loft a hull."""
    import cadquery as cq
    from .cad_exports import export_iges
    from .rhino_exports import CadPart, export_3dm

    shape = cq.importers.importStep(str(step)).val()
    paths = {}
    for fmt in formats:
        path = destination / f'model.{fmt}'
        if fmt == 'iges':
            export_iges(shape, path)
        elif fmt == '3dm':
            export_3dm([CadPart('hull', shape, 'hull')], path)
        else:
            raise ValueError(f'Unsupported conversion: {fmt}')
        paths[fmt] = path
    return paths


def refresh(task: Path, revision: str, *, cad_formats: list[str] | None = None) -> dict:
    """Refresh a finished app task under its controller lock; rollback on failure."""
    from .platform_files import require_secure_descriptor_reads
    require_secure_descriptor_reads()
    task = Path(os.path.abspath(task))
    if task.is_symlink() or not task.is_dir():
        raise ValueError('Choose a run directory, not a symbolic link.')
    # Existing app runs already have this lock. Never create a file in a refused run.
    descriptor = os.open(task / 'controller.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError('Controller lock must be a regular file.')
    stage = None
    locked = False
    exchanged = False
    committed = False
    try:
        try_lock_exclusive(descriptor)
        locked = True
        _assert_lock(task, descriptor)
        before = _inventory(task)
        checkpoint = read_json(task / 'state.json')
        state = checkpoint.get('state', checkpoint)
        if state.get('status') not in FINISHED or state.get('pending') is not None:
            raise ValueError('Only finished runs with no pending work can be refreshed.')
        build = load_build(task, revision)
        domain_state = read_json(task / 'domain/state.json')
        current_revision = domain_state.get('revision')
        if not isinstance(current_revision, int) or build.revision_id != f'r{current_revision:04d}':
            raise ValueError('Refresh only the current revision to avoid stale source links.')
        stage = Path(tempfile.mkdtemp(prefix=f'.{task.name}.reexport-', dir=task.parent))
        shutil.copytree(task, stage, dirs_exist_ok=True)
        # Both directory names must expose the SAME locked inode throughout exchange.
        (stage / 'controller.lock').unlink()
        os.link(task / 'controller.lock', stage / 'controller.lock')
        staged_build = load_build(stage, revision)
        _records(stage, staged_build)
        _checkpoint('records')
        formats = list(dict.fromkeys(cad_formats or []))
        if any(fmt not in ('iges', '3dm') for fmt in formats):
            raise ValueError('Supported CAD conversions: iges, 3dm.')
        derived_cad = {}
        if formats:
            if staged_build.step_path is None:
                raise ValueError('CAD conversion requires an existing STEP file.')
            conversion_dir = stage / 'reexport/cad'
            conversion_dir.mkdir(exist_ok=True)
            derived_cad = _convert_step(staged_build.step_path, conversion_dir, formats)
        export_draft(stage, revision, stage / 'exports', derived_cad=derived_cad)
        _checkpoint('exports')
        after = _inventory(stage)
        allowed = ('exports/', 'reexport/')
        record_paths = {'sources/records.json', 'sources/sheets.json',
                        'review/part_reviews.json', 'presentation.json',
                        'domain/vessel_identity.json', 'domain/.vessel_identity.lock'}
        changed = sorted(name for name in before.keys() | after.keys()
                         if before.get(name) != after.get(name))
        for name in changed:
            if not name.startswith(allowed) and name not in record_paths:
                raise ValueError(f'Refresh changed protected evidence: {name}')
            if name in record_paths - {'sources/records.json'} and name in before:
                raise ValueError(f'Refresh changed an existing user record: {name}')
        history_path = stage / 'reexport/history.json'
        history = json.loads(history_path.read_text()) if history_path.exists() else []
        entry = {'schema': 'marinaframe.reexport.v1', 'revision': build.revision_id,
                 'source_result_sha256': digest_file(build.build_dir / 'result.json'),
                 'changed_files': changed, 'engineering_approved': False,
                 'limitations': ['Missing native CAD formats and drawings are not generated.',
                                 'Tank and structure inputs are not inferred.']}
        history.append(entry)
        write_json(history_path, history)
        write_json(stage / 'reexport/manifest.json', {
            **entry, 'files': {name: digest for name, digest in _inventory(stage).items()
                              if name != 'reexport/manifest.json'},
            'protected_files': {name: digest for name, digest in before.items()
                                if name not in changed and not name.startswith('reexport/')}})
        for directory, _, names in os.walk(stage):
            for name in names:
                sync_file(Path(directory) / name)
            sync_directory(Path(directory))
        _checkpoint('before_publish')
        _assert_lock(task, descriptor)
        if _inventory(task) != before:
            raise RuntimeError('Run changed during refresh.')
        _exchange_directories(stage, task)
        exchanged = True
        _checkpoint('after_publish')
        _assert_lock(task, descriptor)
        sync_directory(task.parent)
        committed = True
        return entry
    except BaseException:
        if exchanged and not committed:
            _exchange_directories(stage, task)
            exchanged = False
            sync_directory(task.parent)
        raise
    finally:
        try:
            if stage is not None and stage.exists() and (committed or not exchanged):
                # Never delete the original snapshot if rollback itself failed.
                # Publication already committed: cleanup cannot undo that success.
                shutil.rmtree(stage, ignore_errors=committed)
        finally:
            try:
                if locked:
                    unlock(descriptor)
            finally:
                os.close(descriptor)
