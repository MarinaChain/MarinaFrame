"""Platform-specific reporting of controller-owned POSIX admission locks."""
import os
from pathlib import Path

_IS_WINDOWS = os.name == 'nt'


def native_admission_lock_metadata() -> dict:
    """Describe a lock; never acquire it or claim unsupported locking exists.

    The native controller owns admission enforcement. Windows has no current
    equivalent of that POSIX profile. A reporting-only round (including fake
    controllers in tests) can still run, but must record that absence honestly.
    """
    if _IS_WINDOWS:
        return {
            'native_admission_lock': None,
            'native_admission_lock_reason': 'POSIX native admission locking is not supported on this platform.',
        }
    path = (Path(os.environ.get('TMPDIR') or '/tmp')
            / f'marinaframe-native-admission-{os.geteuid()}.lock').resolve()
    return {'native_admission_lock': str(path)}
