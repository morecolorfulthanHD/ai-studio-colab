#!/usr/bin/env python3
"""Ephemeral Colab runtime and watcher process identity.

Active watcher ownership belongs under ``/content/ai-studio-runtime`` and must
never be inferred from a numeric PID stored on persistent Google Drive.
"""

from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

RUNTIME_IDENTITY_NAME = "runtime_identity.json"
WATCHER_STATE_DIR_NAME = "output-watcher"
WATCHER_LOCK_NAME = "watcher.lock"
WATCHER_PID_NAME = "watcher.pid"
WATCHER_STATUS_NAME = "watcher_status.json"
STATUS_SCHEMA_VERSION = 2
DEFAULT_HEARTBEAT_MAX_AGE_SECONDS = 60.0


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_boot_id() -> str:
    path = Path("/proc/sys/kernel/random/boot_id")
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def process_start_ticks(pid: int) -> str:
    """Linux /proc process start ticks (field 22), safe around spaced comm names."""
    try:
        raw = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
        close = raw.rfind(")")
        if close < 0:
            return ""
        fields_after_comm = raw[close + 2 :].split()
        # fields_after_comm[0] is stat field 3; starttime is field 22.
        return fields_after_comm[19]
    except (OSError, ValueError, IndexError):
        return ""


def process_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
    except (OSError, ValueError):
        return ""
    return " ".join(part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part)


def watcher_command_valid(cmdline: str, repo_root: Path) -> bool:
    normalized = cmdline.replace("\\", "/")
    expected_root = str(repo_root.resolve()).replace("\\", "/")
    return "run_output_watcher.py" in normalized and expected_root in normalized


def runtime_root(bundle: Any) -> Path:
    try:
        return bundle.path("runtime_root")
    except KeyError:
        return bundle.path("runtime_workflows").parent


def runtime_identity_path(bundle: Any) -> Path:
    try:
        return bundle.path("runtime_identity")
    except KeyError:
        return runtime_root(bundle) / RUNTIME_IDENTITY_NAME


def watcher_state_dir(bundle: Any) -> Path:
    try:
        return bundle.path("runtime_output_watcher")
    except KeyError:
        return runtime_root(bundle) / WATCHER_STATE_DIR_NAME


def watcher_lock_path(bundle: Any) -> Path:
    return watcher_state_dir(bundle) / WATCHER_LOCK_NAME


def watcher_status_path(bundle: Any) -> Path:
    return watcher_state_dir(bundle) / WATCHER_STATUS_NAME


def watcher_pid_path(bundle: Any) -> Path:
    return watcher_state_dir(bundle) / WATCHER_PID_NAME


def persistent_autosync_dir(bundle: Any) -> Path:
    return bundle.path("drive_logs") / "autosync"


@dataclass(frozen=True)
class RuntimeIdentity:
    runtime_id: str
    runtime_started_timestamp: str
    hostname: str
    boot_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeIdentity":
        return cls(
            runtime_id=str(payload.get("runtime_id") or ""),
            runtime_started_timestamp=str(payload.get("runtime_started_timestamp") or ""),
            hostname=str(payload.get("hostname") or ""),
            boot_id=str(payload.get("boot_id") or ""),
        )

    def valid(self) -> bool:
        return bool(self.runtime_id and self.runtime_started_timestamp and self.hostname)


def read_runtime_identity(path: Path) -> RuntimeIdentity | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    identity = RuntimeIdentity.from_dict(payload)
    return identity if identity.valid() else None


def ensure_runtime_identity(path: Path) -> RuntimeIdentity:
    """Create once in ephemeral runtime storage; never use Drive as authority."""
    existing = read_runtime_identity(path)
    if existing is not None:
        return existing
    identity = RuntimeIdentity(
        runtime_id=str(uuid.uuid4()),
        runtime_started_timestamp=utc_now(),
        hostname=socket.gethostname(),
        boot_id=read_boot_id(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(identity.to_dict(), indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return identity


@dataclass(frozen=True)
class WatcherOwnership:
    pid: int
    runtime_id: str
    boot_id: str
    process_start_ticks: str
    command_signature: str
    repository_root: str
    comfyui_base_url: str
    acquired_timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WatcherOwnership":
        return cls(
            pid=int(payload.get("pid") or 0),
            runtime_id=str(payload.get("runtime_id") or ""),
            boot_id=str(payload.get("boot_id") or ""),
            process_start_ticks=str(payload.get("process_start_ticks") or ""),
            command_signature=str(payload.get("command_signature") or ""),
            repository_root=str(payload.get("repository_root") or ""),
            comfyui_base_url=str(payload.get("comfyui_base_url") or ""),
            acquired_timestamp=str(payload.get("acquired_timestamp") or ""),
        )

    def valid(self) -> bool:
        return bool(
            self.pid > 0
            and self.runtime_id
            and self.process_start_ticks
            and self.command_signature
            and self.repository_root
        )


def current_watcher_ownership(
    runtime: RuntimeIdentity,
    *,
    repo_root: Path,
    comfyui_base_url: str,
    pid: int | None = None,
) -> WatcherOwnership:
    owner_pid = int(pid or os.getpid())
    return WatcherOwnership(
        pid=owner_pid,
        runtime_id=runtime.runtime_id,
        boot_id=runtime.boot_id,
        process_start_ticks=process_start_ticks(owner_pid),
        command_signature="run_output_watcher.py",
        repository_root=str(repo_root.resolve()),
        comfyui_base_url=comfyui_base_url,
        acquired_timestamp=utc_now(),
    )


def read_watcher_ownership(path: Path) -> WatcherOwnership | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        owner = WatcherOwnership.from_dict(payload)
    except (TypeError, ValueError):
        return None
    return owner if owner.valid() else None


def heartbeat_age_seconds(value: str, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        heartbeat = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - heartbeat.astimezone(timezone.utc)).total_seconds())


@dataclass(frozen=True)
class OwnershipValidation:
    ownership_state: str
    process_alive: bool
    process_command_valid: bool
    process_start_ticks: str
    heartbeat_age_seconds: float | None
    heartbeat_fresh: bool
    reason: str

    @property
    def current(self) -> bool:
        return self.ownership_state == "current_runtime"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_watcher_ownership(
    owner: WatcherOwnership | None,
    runtime: RuntimeIdentity | None,
    status_payload: dict[str, Any] | None,
    *,
    repo_root: Path,
    heartbeat_max_age_seconds: float = DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    pid_alive_fn: Callable[[int], bool],
    cmdline_fn: Callable[[int], str] = process_cmdline,
    start_ticks_fn: Callable[[int], str] = process_start_ticks,
    now: datetime | None = None,
) -> OwnershipValidation:
    if owner is None or runtime is None:
        return OwnershipValidation("malformed", False, False, "", None, False, "identity or lock malformed")
    if owner.runtime_id != runtime.runtime_id:
        return OwnershipValidation("old_runtime", False, False, "", None, False, "runtime_id mismatch")
    if runtime.boot_id and owner.boot_id != runtime.boot_id:
        return OwnershipValidation("old_runtime", False, False, "", None, False, "boot_id mismatch")
    if Path(owner.repository_root).resolve() != repo_root.resolve() or owner.command_signature != "run_output_watcher.py":
        return OwnershipValidation(
            "foreign_process", False, False, "", None, False, "recorded watcher command/repository mismatch"
        )
    alive = pid_alive_fn(owner.pid)
    if not alive:
        return OwnershipValidation("dead", False, False, "", None, False, "recorded PID is not alive")
    cmdline = cmdline_fn(owner.pid)
    command_ok = watcher_command_valid(cmdline, repo_root)
    if not command_ok:
        return OwnershipValidation(
            "foreign_process", True, False, start_ticks_fn(owner.pid), None, False, "PID command line is not this watcher"
        )
    actual_ticks = start_ticks_fn(owner.pid)
    if not actual_ticks or actual_ticks != owner.process_start_ticks:
        return OwnershipValidation(
            "pid_reused", True, True, actual_ticks, None, False, "process start ticks differ"
        )
    heartbeat = str((status_payload or {}).get("heartbeat") or "")
    age = heartbeat_age_seconds(heartbeat, now=now)
    fresh = age is not None and age <= heartbeat_max_age_seconds
    if not fresh:
        return OwnershipValidation(
            "stale_heartbeat", True, True, actual_ticks, age, False, "heartbeat missing, invalid, or stale"
        )
    return OwnershipValidation("current_runtime", True, True, actual_ticks, age, True, "valid current watcher")
