"""Access to POSIX process limits for the sandboxed workers, failing closed where they do not exist.

The CAD and render workers set hard limits on CPU time, memory, file size and open files before they
run, and report their CPU use in the receipt. These use the POSIX `resource` module, which Windows does
not have. A worker must never run without its limits, so on Windows it stops with a clear error
instead; the rest of the package does not need this module and stays importable on Windows.
"""
from __future__ import annotations

import os
from types import ModuleType

WINDOWS_NOT_SUPPORTED = ('The sandboxed worker needs POSIX process limits (the resource module), which '
                         'Windows does not provide; worker isolation on Windows is not built yet.')


def posix_resource() -> ModuleType:
    """The `resource` module, or a RuntimeError on Windows (a worker never runs without limits)."""
    if os.name == 'nt':
        raise RuntimeError(WINDOWS_NOT_SUPPORTED)
    import resource

    return resource
