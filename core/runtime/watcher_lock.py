#!/usr/bin/env python3
"""Exclusive watcher lock with runtime-aware process ownership.

Legacy PID-only locks remain readable for diagnosis, but current ownership is a
JSON process identity and is never accepted based on numeric PID alone.
"""

from __future__ import annotations

import os
import json
import sys
from pathlib import Path
from typing import Any

from .runtime_identity import WatcherOwnership, read_watcher_ownership

PID_NAME = "watcher.pid"
LEGACY_PID_NAME = "output_watcher.pid"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except (OSError, OverflowError, AttributeError):
            return False
    try:
        os.kill(pid, 0)
    except (OSError, OverflowError):
        return False
    return True


def read_lock_pid(lock_path: Path) -> int | None:
    if not lock_path.is_file():
        return None
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        if raw:
            if raw.startswith("{"):
                payload = json.loads(raw)
                return int(payload.get("pid") or 0) or None
            return int(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    for pid_name in (PID_NAME, LEGACY_PID_NAME):
        pid_path = lock_path.parent / pid_name
        if not pid_path.is_file():
            continue
        try:
            return int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
    return None


def _owner_payload(owner: WatcherOwnership | dict[str, Any] | None, pid: int) -> str:
    if isinstance(owner, WatcherOwnership):
        return json.dumps(owner.to_dict(), indent=2) + "\n"
    if isinstance(owner, dict):
        return json.dumps(owner, indent=2) + "\n"
    return str(pid)


def _remove_lock_files(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)
    (lock_path.parent / PID_NAME).unlink(missing_ok=True)
    (lock_path.parent / LEGACY_PID_NAME).unlink(missing_ok=True)


def remove_ownership_files(lock_path: Path, *, status_path: Path | None = None) -> None:
    """Remove active ownership only; never evidence, processed index, logs, or outputs."""
    _remove_lock_files(lock_path)
    if status_path is not None:
        status_path.unlink(missing_ok=True)


def try_acquire_lock(
    lock_path: Path,
    *,
    owner: WatcherOwnership | dict[str, Any] | None = None,
) -> tuple[bool, int | None]:
    """Atomically acquire. Caller must validate an existing identity before retry.

    PID-only fallback behavior is retained for legacy unit simulations. Production
    callers pass ``owner`` and never auto-accept or auto-clear an existing lock.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    pid = int(owner.pid if isinstance(owner, WatcherOwnership) else os.getpid())

    def _atomic_create() -> bool:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        try:
            os.write(fd, _owner_payload(owner, pid).encode("utf-8"))
        finally:
            os.close(fd)
        (lock_path.parent / PID_NAME).write_text(str(pid), encoding="utf-8")
        return True

    if _atomic_create():
        return True, None

    holder = read_lock_pid(lock_path)
    if owner is not None:
        return False, holder
    if holder is not None and pid_alive(holder):
        return False, holder

    _remove_lock_files(lock_path)
    if _atomic_create():
        return True, None

    holder = read_lock_pid(lock_path)
    return False, holder


def release_lock(lock_path: Path, *, owner_pid: int | None = None) -> bool:
    """Release lock only when owned by owner_pid (default: current process)."""
    if not lock_path.is_file():
        return False
    expected = owner_pid if owner_pid is not None else os.getpid()
    holder = read_lock_pid(lock_path)
    if holder != expected:
        return False
    _remove_lock_files(lock_path)
    return True


def read_lock_ownership(lock_path: Path) -> WatcherOwnership | None:
    return read_watcher_ownership(lock_path)


def clear_stale_lock(lock_path: Path) -> bool:
    """Clear lock only when holder PID is not alive. Returns True if cleared."""
    if not lock_path.is_file():
        return False
    holder = read_lock_pid(lock_path)
    if holder is not None and pid_alive(holder):
        return False
    _remove_lock_files(lock_path)
    return True
