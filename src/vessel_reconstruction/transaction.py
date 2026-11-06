"""Exclusive local run staging and same-filesystem atomic publication (POSIX)."""
from __future__ import annotations

import fcntl
import ctypes
import errno
import os
import stat
import re
import uuid
from pathlib import Path

from .provenance import sync_directory, write_json
from .schema import load_bounded_json


class RunPublicationError(RuntimeError):
    """The run could not be durably published; no successful result is returned."""


class RunTransaction:
    def __init__(self, output_dir: str | Path):
        requested = Path(output_dir).absolute()
        if requested.name in ("", ".", ".."):
            raise ValueError("Choose a named new run directory.")
        requested.parent.mkdir(parents=True, exist_ok=True)
        self.out = requested.parent.resolve() / requested.name
        self.token = uuid.uuid4().hex
        self.lock_path = self.out.parent / f".{self.out.name}.run-lock"
        self.stage = self.out.parent / f".{self.out.name}.staging-{self.token}"
        self.lock_fd = None
        self.published = False
        self.durable = False
        if os.path.lexists(self.out):
            raise FileExistsError("Run output already exists; choose a new directory to preserve evidence.")
        try:
            self.lock_fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError as exc:
            raise FileExistsError("A transaction already reserves this output; recover the interrupted run or use another directory.") from exc
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if os.path.lexists(self.out):
                raise FileExistsError("Run output already exists.")
            self.stage.mkdir(mode=0o700)
            self.checkpoint("created")
            sync_directory(self.out.parent)
        except BaseException:
            self.close()
            raise

    def checkpoint(self, phase: str) -> None:
        record = {"schema_version": "1.0", "target": self.out.name,
                  "staging_directory": self.stage.name, "transaction_id": self.token,
                  "owner_pid": os.getpid(), "phase": phase, "status": "in_progress"}
        # Keep the reservation inode locked while replacing its *contents*.
        # Replacing that inode would release mutual exclusion for other opens.
        from .provenance import canonical_json
        payload = canonical_json(record)
        os.lseek(self.lock_fd, 0, os.SEEK_SET)
        os.ftruncate(self.lock_fd, 0)
        os.write(self.lock_fd, payload)
        os.fsync(self.lock_fd)
        write_json(self.stage / "transaction.json", record)

    def publish(self):
        if os.path.lexists(self.out):
            raise FileExistsError("The final run path appeared before publication; it will not be overwritten.")
        # The manifest was written and checked before this rename. The lock
        # excludes all cooperating writers for this final destination.
        (self.stage / "transaction.json").unlink(missing_ok=True)
        sync_directory(self.stage)
        # Linux renameat2 supplies atomic NOREPLACE. A check followed by ordinary
        # rename could otherwise overwrite a concurrently created empty target.
        library = ctypes.CDLL(None, use_errno=True)
        operation = getattr(library, "renameat2", None)
        if operation is None:
            raise RunPublicationError("Atomic no-replace publication requires Linux renameat2 support.")
        operation.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        operation.restype = ctypes.c_int
        if operation(-100, os.fsencode(self.stage), -100, os.fsencode(self.out), 1) != 0:
            code = ctypes.get_errno()
            if code == errno.EEXIST:
                raise FileExistsError("The final run path appeared before atomic publication.")
            raise OSError(code, "Atomic no-replace run publication failed.")
        self.published = True
        sync_directory(self.out.parent)
        self.durable = True

    def close(self):
        if self.lock_fd is not None:
            try:
                if self.published and self.durable:
                    try:
                        self.lock_path.unlink(missing_ok=True)
                    except OSError as exc:
                        # The reservation still exists, so the verifier refuses
                        # downloads until orphan recovery can complete safely.
                        raise RunPublicationError("Evidence is sealed but publication reservation could not be released; recovery is required.") from exc
                    try:
                        sync_directory(self.out.parent)
                    except OSError:
                        # Files + rename already crossed their durability
                        # boundary in publish(). Do not turn committed evidence
                        # into a failed job merely because reservation cleanup
                        # cannot be fsynced. After a crash an old reservation
                        # may reappear; verification then conservatively blocks
                        # it and explicit recovery removes unpublished exports.
                        pass
            finally:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                os.close(self.lock_fd)
                self.lock_fd = None


def quarantine_interrupted(output_dir: str | Path) -> dict:
    """Quarantine an orphan staging directory only after its OS lock is free.

    No CAD or document parser is invoked. An active worker retains its flock
    even when its PID is reused elsewhere, so recovery cannot seize live work.
    """
    requested = Path(output_dir).absolute()
    out = requested.parent.resolve() / requested.name
    lock_path = out.parent / f".{out.name}.run-lock"
    if not lock_path.exists():
        return {"recovered": False, "reason": "final_output_exists" if os.path.lexists(out) else "no_transaction", "run_dir": str(out)}
    descriptor = os.open(lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Transaction reservation is not an ordinary file.")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"recovered": False, "reason": "active_transaction", "run_dir": str(out)}
        try:
            record = load_bounded_json(lock_path, max_bytes=16_384, max_nodes=100)
        except (OSError, ValueError):
            record = {}
        prefix = f".{out.name}.staging-"
        stages = [p for p in out.parent.iterdir()
                  if p.name.startswith(prefix) and re.fullmatch(r"[0-9a-f]{32}", p.name[len(prefix):])
                  and p.is_dir() and not p.is_symlink()]
        if os.path.lexists(out):
            if out.is_symlink() or not out.is_dir():
                return {"recovered": False, "reason": "unsafe_final_output", "run_dir": str(out)}
            # The reservation was never cleared: this directory was never
            # admitted by verify_run, even if rename finished before a crash.
            stages.append(out)
        if len(stages) > 1:
            return {"recovered": False, "reason": "ambiguous_staging", "run_dir": str(out)}
        quarantined = None
        if stages:
            stage = stages[0]
            # Partial geometry remains private and is removed before marking
            # the orphan as quarantined. If cleanup fails, do not publish.
            for name in ("mesh.json", "model.step", "model.stl", "cad_sections.json", "manifest.json", "result.json"):
                (stage / name).unlink(missing_ok=True)
            quarantined = out.parent / f".{out.name}.interrupted-{uuid.uuid4().hex}"
            os.rename(stage, quarantined)
            write_json(quarantined / "interruption.json", {"status": "interrupted", "last_phase": record.get("phase", "unknown"),
                                                           "geometry_removed": True, "original_target": out.name})
        lock_path.unlink()
        sync_directory(out.parent)
        return {"recovered": True, "reason": "orphan_quarantined", "run_dir": str(out),
                "last_phase": record.get("phase", "unknown"),
                "quarantine": str(quarantined) if quarantined else None}
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
