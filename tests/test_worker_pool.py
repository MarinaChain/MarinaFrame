"""The machine-wide worker pool: a lone run gets every worker, concurrent runs share them,
and the workers of a crashed run come back (parallel.worker_tokens)."""
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from vessel_reconstruction import parallel

SRC = str(Path(parallel.__file__).resolve().parents[1])

# A run in its own process: take up to WANTED of SIZE tokens, mark the count it holds in
# the holders folder, read the total all runs hold, keep the tokens a moment, give them back.
RUN = textwrap.dedent("""
    import os, sys, time
    from pathlib import Path
    from vessel_reconstruction import parallel
    size, wanted, holders, hold = int(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3]), float(sys.argv[4])
    def total_held():
        total = 0
        for mark in holders.glob("*.held"):
            try:
                total += int(mark.read_text())
            except (FileNotFoundError, ValueError):
                pass  # another run is just giving its tokens back
        return total
    with parallel.worker_tokens(wanted, size=size) as granted:
        mark = holders / f"{os.getpid()}.held"
        (holders / f"{os.getpid()}.tmp").write_text(str(granted))
        os.replace(holders / f"{os.getpid()}.tmp", mark)
        most = 0
        stop = time.monotonic() + hold
        while time.monotonic() < stop:
            most = max(most, total_held())
            time.sleep(0.005)
        mark.unlink()
    print(granted, most)
""")


@pytest.fixture
def pool(tmp_path, monkeypatch):
    folder = tmp_path / "pool"
    monkeypatch.setenv(parallel.POOL_DIRECTORY_ENVIRONMENT_VARIABLE, str(folder))
    return folder


def _start_runs(count, size, wanted, holders, hold=0.4):
    environment = {**os.environ, "PYTHONPATH": SRC}
    return [subprocess.Popen([sys.executable, "-c", RUN, str(size), str(wanted), str(holders), str(hold)],
                             stdout=subprocess.PIPE, text=True, env=environment) for _ in range(count)]


def test_the_pool_has_cores_less_two_and_a_lone_run_gets_them_all(pool, monkeypatch):
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 10)
    assert parallel.pool_size() == 8
    with parallel.worker_tokens(12) as granted:
        assert granted == 8
    with parallel.worker_tokens(3) as granted:  # never more than the run can use
        assert granted == 3
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 2)
    assert parallel.pool_size() == 1


@pytest.mark.parametrize("runs", [2, 5])
def test_concurrent_runs_never_hold_more_than_the_pool(pool, tmp_path, runs):
    size = 4
    holders = tmp_path / "holders"
    holders.mkdir()
    # Each run wants 3 of 4: the first gets 3, the next the last one, the others wait.
    processes = _start_runs(runs, size, 3, holders)
    results = [process.communicate()[0].split() for process in processes]
    assert all(process.returncode == 0 for process in processes)
    granted = [int(r[0]) for r in results]
    most = max(int(r[1]) for r in results)
    assert all(1 <= g <= 3 for g in granted)  # every run got a worker in the end
    assert most <= size


def test_a_crashed_runs_workers_come_back(pool, tmp_path):
    size = 3
    holders = tmp_path / "holders"
    holders.mkdir()
    [process] = _start_runs(1, size, size, holders, hold=60)
    while not list(holders.glob("*.held")):
        assert process.poll() is None
        time.sleep(0.01)
    with parallel.worker_tokens(size, size=size, wait=False) as granted:
        assert granted == 0  # all held by the live run
    process.send_signal(signal.SIGKILL)
    process.wait()
    with parallel.worker_tokens(size, size=size, wait=False) as granted:
        assert granted == size  # the kernel dropped the dead run's locks


def test_a_waiting_run_stops_when_cancelled(pool):
    import threading
    cancel = threading.Event()
    with parallel.worker_tokens(1, size=1):
        cancel.set()
        with pytest.raises(InterruptedError):
            with parallel.worker_tokens(1, cancel, size=1):
                pass


def _unsafe_folder(kind, tmp_path, monkeypatch):
    """A pool folder another local user could have prepared: shared mode, a link, or not ours."""
    folder = tmp_path / "pool"
    if kind == "shared_mode":
        folder.mkdir()
        folder.chmod(0o755)
    elif kind == "symlink":
        (tmp_path / "elsewhere").mkdir(mode=0o700)
        folder.symlink_to(tmp_path / "elsewhere")
    elif kind == "foreign_owner":
        folder.mkdir(mode=0o700)
        real = parallel.os.getuid()
        monkeypatch.setattr(parallel.os, "getuid", lambda: real + 1)
    elif kind == "symlinked_token":
        folder.mkdir(mode=0o700)
        (folder / "token-0.lock").symlink_to(tmp_path / "victim")
    monkeypatch.setenv(parallel.POOL_DIRECTORY_ENVIRONMENT_VARIABLE, str(folder))
    return folder


@pytest.mark.parametrize("kind", ["shared_mode", "symlink", "foreign_owner", "symlinked_token"])
def test_an_unsafe_pool_folder_means_no_shared_limit_not_an_error(kind, tmp_path, monkeypatch, caplog):
    _unsafe_folder(kind, tmp_path, monkeypatch)
    if kind != "symlinked_token":
        with pytest.raises(PermissionError):
            parallel.pool_directory()
    with caplog.at_level("WARNING", logger=parallel.__name__):
        with parallel.worker_tokens(3, size=4) as granted:
            assert granted == 3  # the run's own bound, without the pool
    assert "Worker pool not used" in caplog.text
    assert not (tmp_path / "victim").exists()  # a token link is never followed


def test_an_inspection_runs_when_the_pool_folder_is_unsafe(tmp_path, monkeypatch):
    from test_agent_tools import drawing
    from vessel_reconstruction.agent_tools import DomainTools
    path, _ = drawing(tmp_path / "input")
    _unsafe_folder("shared_mode", tmp_path, monkeypatch)
    monkeypatch.setenv(parallel.WORKERS_ENVIRONMENT_VARIABLE, "2")
    observed = DomainTools(tmp_path / "task", path).execute("inspect_source", {})
    assert observed["ok"] and observed["resources"]["workers"] == 2


def test_the_default_pool_folder_is_in_the_users_home_cache(monkeypatch):
    monkeypatch.delenv(parallel.POOL_DIRECTORY_ENVIRONMENT_VARIABLE, raising=False)
    folder = parallel.pool_directory()
    import pwd
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    assert folder.is_relative_to(home) and folder.name == "worker-pool"
    assert not str(folder).startswith("/tmp")
