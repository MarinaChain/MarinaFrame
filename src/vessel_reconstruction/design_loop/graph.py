"""Ordered record-only graph with content-addressed, owned-output caching."""
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Callable

from ..design_record import DesignRecord


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def get_path(data, path):
    for key in path:
        data = data[key]
    return data


def set_path(data, path, value):
    parent = get_path(data, path[:-1])
    parent[path[-1]] = deepcopy(value)


@dataclass(frozen=True)
class Step:
    name: str
    version: str
    reads: tuple[tuple[str, ...], ...]
    writes: tuple[tuple[str, ...], ...]
    calculate: Callable[[DesignRecord], DesignRecord]
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class Receipt:
    executed: tuple[str, ...]
    cached: tuple[str, ...]
    input_hashes: dict[str, str]


def run_graph(record, steps, cache_dir):
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    seen, owners = set(), []
    for step in steps:
        if step.name in seen or not set(step.depends_on) <= seen:
            raise ValueError('Duplicate step or unordered dependency')
        for path in step.writes:
            if not path or any(path[:len(other)] == other or other[:len(path)] == path for other in owners):
                raise ValueError('Output ownership paths overlap')
            owners.append(path)
        seen.add(step.name)
    executed, cached, hashes = [], [], {}
    for step in steps:
        before = record.to_dict()
        key = digest(dict(step=step.name, version=step.version, schema=before['schema_version'],
                          reads=step.reads, writes=step.writes,
                          inputs=[get_path(before, path) for path in step.reads]))
        hashes[step.name] = key
        path = cache_dir / f'{key}.json'
        if path.exists():
            try:
                entry = json.loads(path.read_text())
                patch = entry['patch']
                if entry['key'] != key or entry['digest'] != digest(patch) or len(patch) != len(step.writes):
                    raise ValueError('invalid cache integrity')
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError('Invalid design-loop cache entry') from error
            cached.append(step.name)
        else:
            after = step.calculate(record).to_dict()
            patch = [get_path(after, output) for output in step.writes]
            owned_only = deepcopy(before)
            for output, value in zip(step.writes, patch):
                set_path(owned_only, output, value)
            if owned_only != after:
                raise ValueError(f'Step {step.name} changed unowned record fields')
            executed.append(step.name)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(dict(key=key, digest=digest(patch), patch=patch), allow_nan=False))
            temporary.replace(path)
        for output, value in zip(step.writes, patch):
            set_path(before, output, value)
        record = DesignRecord.from_dict(before)
    return record, Receipt(tuple(executed), tuple(cached), hashes)
