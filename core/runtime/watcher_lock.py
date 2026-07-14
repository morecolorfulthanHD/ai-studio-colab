#!/usr/bin/env python3
"""Exclusive watcher lock — atomic acquisition and PID-scoped release."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PID_NAME = "output_watcher.pid"


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
            return int(raw)
    except (OSError, ValueError):
        pass
    pid_path = lock_path.parent / PID_NAME
    if pid_path.is_file():
        try:
            return int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
    return None


def _write_lock_pid(lock_path: Path, pid: int) -> None:
    lock_path.write_text(str(pid), encoding="utf-8")
    (lock_path.parent / PID_NAME).write_text(str(pid), encoding="utf-8")


def _remove_lock_files(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)
    (lock_path.parent / PID_NAME).unlink(missing_ok=True)


def try_acquire_lock(lock_path: Path) -> tuple[bool, int | None]:
    """Atomically acquire the watcher lock. Returns (acquired, holder_pid_if_held)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()

    def _atomic_create() -> bool:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        try:
            os.write(fd, str(pid).encode("ascii"))
        finally:
            os.close(fd)
        _write_lock_pid(lock_path, pid)
        return True

    if _atomic_create():
        return True, None

    holder = read_lock_pid(lock_path)
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


def clear_stale_lock(lock_path: Path) -> bool:
    """Clear lock only when holder PID is not alive. Returns True if cleared."""
    if not lock_path.is_file():
        return False
    holder = read_lock_pid(lock_path)
    if holder is not None and pid_alive(holder):
        return False
    _remove_lock_files(lock_path)
    return True
