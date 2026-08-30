#!/usr/bin/env python3
"""Exclusive inter-process lock for append-only JSONL ledgers.

Uses the same O_EXCL create pattern as watcher ownership locks, with stale-PID
cleanup so a crashed writer cannot permanently block capture/recovery.

Same-process threads also serialize on a threading.Lock so Windows cannot race
``unlink`` against a concurrent ``read_text`` of the lock file.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .watcher_lock import clear_stale_lock, pid_alive, read_lock_pid, release_lock, try_acquire_lock

_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.Lock] = {}


def ledger_lock_path(ledger_path: Path) -> Path:
    return Path(str(ledger_path) + ".lock")


def _thread_lock_for(ledger_path: Path) -> threading.Lock:
    key = str(Path(ledger_path))
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock


def _release_with_retry(lock_path: Path, *, attempts: int = 10, delay: float = 0.05) -> None:
    last_exc: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            release_lock(lock_path)
            return
        except OSError as exc:
            last_exc = exc
            time.sleep(delay)
    if last_exc is not None:
        raise last_exc


def append_jsonl_line_unlocked(ledger_path: Path, line: str) -> None:
    """Append one complete JSONL line. Caller must already hold ``exclusive_jsonl_lock``."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = line if line.endswith("\n") else f"{line}\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".jsonl_", suffix=".tmp", dir=str(ledger_path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        existing = ledger_path.read_bytes() if ledger_path.is_file() else b""
        tmp_path.write_bytes(existing + payload.encode("utf-8"))
        tmp_path.replace(ledger_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def append_jsonl_line(ledger_path: Path, line: str) -> None:
    """Atomically append one JSONL line under the shared ledger lock."""
    with exclusive_jsonl_lock(ledger_path):
        append_jsonl_line_unlocked(ledger_path, line)


@contextmanager
def exclusive_jsonl_lock(
    ledger_path: Path,
    *,
    timeout_seconds: float = 30.0,
    poll_seconds: float = 0.05,
    max_stale_clear_attempts: int = 3,
) -> Iterator[None]:
    """Hold an exclusive lock spanning check+append for ``ledger_path``."""
    thread_lock = _thread_lock_for(ledger_path)
    if not thread_lock.acquire(timeout=timeout_seconds):
        raise TimeoutError(f"Timed out acquiring in-process ledger lock for {ledger_path}")
    lock_path = ledger_lock_path(ledger_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    stale_clears = 0
    acquired = False
    try:
        while time.monotonic() < deadline:
            ok, holder = try_acquire_lock(lock_path, owner=None)
            if ok:
                acquired = True
                break
            if holder is not None and not pid_alive(holder) and stale_clears < max_stale_clear_attempts:
                if clear_stale_lock(lock_path):
                    stale_clears += 1
                    continue
            time.sleep(poll_seconds)
        if not acquired:
            holder = read_lock_pid(lock_path)
            raise TimeoutError(
                f"Timed out acquiring ledger lock for {ledger_path} "
                f"(holder_pid={holder})"
            )
        try:
            yield
        finally:
            _release_with_retry(lock_path)
    finally:
        thread_lock.release()
