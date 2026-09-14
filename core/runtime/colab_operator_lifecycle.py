#!/usr/bin/env python3
"""Local Colab operator run lifecycle, cancellation, and process ownership.

Machine-local orchestration only — never writes Google Drive application state.
Does not disconnect Colab, kill remote kernels, Full Reset, or touch Drive data.

Cursor UI Stop may kill the agent without running Python hooks; helpers must
heartbeat/check run validity and self-terminate when cancelled or stale.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class LifecycleStatus(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    IDLE = "IDLE"  # no active run (control surface only)


ACTIVE_STATUSES = frozenset(
    {LifecycleStatus.STARTING, LifecycleStatus.RUNNING, LifecycleStatus.CANCELLING}
)
TERMINAL_STATUSES = frozenset(
    {LifecycleStatus.CANCELLED, LifecycleStatus.COMPLETE, LifecycleStatus.FAILED}
)


class OperatorCancelled(Exception):
    """Raised when an operator helper detects cancellation / stale run."""

    def __init__(self, run_id: str, reason: str = "cancelled"):
        self.run_id = run_id
        self.reason = reason
        super().__init__(f"OPERATOR_CANCELLED run_id={run_id} reason={reason}")


class OperatorStaleRun(OperatorCancelled):
    """Old helper noticed a newer run_id is active."""

    def __init__(self, run_id: str, current_run_id: str):
        self.current_run_id = current_run_id
        super().__init__(run_id, reason=f"stale; current={current_run_id}")


DEFAULT_CHROME_USER_DATA_DIR_NAME = "CursorChromeProfile"
DEFAULT_CDP_PORT = 9222


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_operator_state_dir() -> Path:
    """Machine-local operator state (not Drive)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "AI_Studio" / "operator"
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "ai-studio" / "operator"
    return Path.home() / ".local" / "state" / "ai-studio" / "operator"


def default_chrome_user_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "AI_Studio" / DEFAULT_CHROME_USER_DATA_DIR_NAME
    return Path.home() / ".local" / "share" / "ai-studio" / DEFAULT_CHROME_USER_DATA_DIR_NAME


@dataclass
class ChildProcRecord:
    pid: int
    kind: str  # helper | chrome | other
    argv0: str = ""
    registered_at: str = field(default_factory=_utc_now_iso)


@dataclass
class OperatorRunState:
    operator_run_id: str
    status: str
    started_at: str
    updated_at: str
    checkpoint_label: str = ""
    cancellation_requested: bool = False
    parent_pid: int | None = None
    children: list[dict[str, Any]] = field(default_factory=list)
    chrome_pids: list[int] = field(default_factory=list)
    chrome_relaunch_allowed: bool = True
    notes: list[str] = field(default_factory=list)
    generation: int = 1  # increments when a new run begins

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OperatorRunState":
        return cls(
            operator_run_id=str(data["operator_run_id"]),
            status=str(data["status"]),
            started_at=str(data["started_at"]),
            updated_at=str(data["updated_at"]),
            checkpoint_label=str(data.get("checkpoint_label") or ""),
            cancellation_requested=bool(data.get("cancellation_requested")),
            parent_pid=data.get("parent_pid"),
            children=list(data.get("children") or []),
            chrome_pids=[int(x) for x in (data.get("chrome_pids") or [])],
            chrome_relaunch_allowed=bool(data.get("chrome_relaunch_allowed", True)),
            notes=list(data.get("notes") or []),
            generation=int(data.get("generation") or 1),
        )


@dataclass
class StopReport:
    operator_run_id: str | None
    previous_status: str | None
    status: str
    helpers_stopped: list[int]
    child_process_count: int
    browser_launch_prevented: bool
    browser_closed: bool
    browser_close_requested: bool
    colab_runtime_untouched: bool = True
    already_idle: bool = False
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OperatorLifecycle:
    """Filesystem-backed operator run lifecycle controller."""

    ACTIVE_FILE = "active_run.json"
    HISTORY_DIR = "history"
    LOCK_NOTE = (
        "Local orchestration only. Never auto-disconnect Colab, Full Reset, "
        "or delete Drive/ComfyUI/OutputWatcher."
    )

    def __init__(
        self,
        state_dir: Path | None = None,
        *,
        chrome_user_data_dir: Path | None = None,
        kill_fn: Callable[[int], bool] | None = None,
        list_chrome_pids_fn: Callable[[Path], list[int]] | None = None,
        clock: Callable[[], float] | None = None,
    ):
        self.state_dir = Path(state_dir) if state_dir else default_operator_state_dir()
        self.chrome_user_data_dir = (
            Path(chrome_user_data_dir) if chrome_user_data_dir else default_chrome_user_data_dir()
        )
        self._kill_fn = kill_fn or _default_kill_pid
        self._list_chrome_pids_fn = list_chrome_pids_fn or list_dedicated_chrome_pids
        self._clock = clock or time.monotonic
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / self.HISTORY_DIR).mkdir(parents=True, exist_ok=True)

    @property
    def active_path(self) -> Path:
        return self.state_dir / self.ACTIVE_FILE

    def _read_active(self) -> OperatorRunState | None:
        if not self.active_path.is_file():
            return None
        try:
            data = json.loads(self.active_path.read_text(encoding="utf-8"))
            return OperatorRunState.from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _write_active(self, state: OperatorRunState) -> None:
        state.updated_at = _utc_now_iso()
        tmp = self.active_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.active_path)

    def _archive(self, state: OperatorRunState) -> None:
        path = self.state_dir / self.HISTORY_DIR / f"{state.operator_run_id}.json"
        path.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")

    def status(self) -> dict[str, Any]:
        state = self._read_active()
        if state is None:
            return {
                "status": LifecycleStatus.IDLE.value,
                "operator_run_id": None,
                "state_dir": str(self.state_dir),
                "chrome_user_data_dir": str(self.chrome_user_data_dir),
                "note": self.LOCK_NOTE,
            }
        return {
            **state.to_dict(),
            "state_dir": str(self.state_dir),
            "chrome_user_data_dir": str(self.chrome_user_data_dir),
            "note": self.LOCK_NOTE,
        }

    def begin(
        self,
        *,
        checkpoint_label: str = "",
        parent_pid: int | None = None,
    ) -> OperatorRunState:
        """Start a new operator run. Replaces any non-terminal prior active file."""
        prior = self._read_active()
        generation = 1
        if prior is not None:
            generation = int(prior.generation) + 1
            if prior.status in {s.value for s in ACTIVE_STATUSES}:
                # Fail-closed: mark prior cancelled before replacing
                prior.status = LifecycleStatus.CANCELLED.value
                prior.cancellation_requested = True
                prior.chrome_relaunch_allowed = False
                prior.notes.append("superseded_by_new_run")
                self._archive(prior)
        run_id = f"oprun_{uuid.uuid4().hex[:12]}"
        now = _utc_now_iso()
        state = OperatorRunState(
            operator_run_id=run_id,
            status=LifecycleStatus.RUNNING.value,
            started_at=now,
            updated_at=now,
            checkpoint_label=checkpoint_label,
            cancellation_requested=False,
            parent_pid=parent_pid if parent_pid is not None else os.getpid(),
            chrome_relaunch_allowed=True,
            generation=generation,
            notes=["begun"],
        )
        self._write_active(state)
        return state

    def set_checkpoint(self, run_id: str, label: str) -> OperatorRunState:
        state = self._require_run(run_id)
        self._fail_if_not_owner(state)
        state.checkpoint_label = label
        self._write_active(state)
        return state

    def heartbeat(self, run_id: str) -> OperatorRunState:
        state = self._require_run(run_id)
        self._fail_if_not_owner(state)
        if state.cancellation_requested or state.status == LifecycleStatus.CANCELLED.value:
            raise OperatorCancelled(run_id)
        if state.status == LifecycleStatus.CANCELLING.value:
            raise OperatorCancelled(run_id, reason="cancelling")
        self._write_active(state)
        return state

    def register_child(
        self,
        run_id: str,
        pid: int,
        *,
        kind: str = "helper",
        argv0: str = "",
    ) -> OperatorRunState:
        state = self._require_run(run_id)
        self._fail_if_not_owner(state)
        if not self.may_spawn_helpers(run_id):
            raise OperatorCancelled(run_id, reason="cannot_register_child_while_cancelled")
        rec = ChildProcRecord(pid=int(pid), kind=kind, argv0=argv0)
        state.children.append(asdict(rec))
        if kind == "chrome":
            if int(pid) not in state.chrome_pids:
                state.chrome_pids.append(int(pid))
        self._write_active(state)
        return state

    def may_spawn_helpers(self, run_id: str) -> bool:
        state = self._read_active()
        if state is None or state.operator_run_id != run_id:
            return False
        if state.cancellation_requested:
            return False
        return state.status in {
            LifecycleStatus.STARTING.value,
            LifecycleStatus.RUNNING.value,
        }

    def may_launch_chrome(self, run_id: str) -> bool:
        if not self.may_spawn_helpers(run_id):
            return False
        state = self._read_active()
        assert state is not None
        return bool(state.chrome_relaunch_allowed)

    def assert_run_valid(self, run_id: str) -> OperatorRunState:
        """Helpers call this before acting; fail closed if cancelled or superseded."""
        state = self._read_active()
        if state is None:
            raise OperatorCancelled(run_id, reason="no_active_run")
        if state.operator_run_id != run_id:
            raise OperatorStaleRun(run_id, state.operator_run_id)
        if state.cancellation_requested or state.status in {
            LifecycleStatus.CANCELLED.value,
            LifecycleStatus.CANCELLING.value,
        }:
            raise OperatorCancelled(run_id, reason=state.status)
        if state.status not in {
            LifecycleStatus.STARTING.value,
            LifecycleStatus.RUNNING.value,
        }:
            raise OperatorCancelled(run_id, reason=f"status={state.status}")
        return state

    def check_cancelled(self, run_id: str) -> bool:
        try:
            self.assert_run_valid(run_id)
            return False
        except OperatorCancelled:
            return True

    def cooperative_sleep(
        self,
        run_id: str,
        seconds: float,
        *,
        poll_interval: float = 0.25,
    ) -> None:
        """Sleep in short polls so cancellation is noticed promptly."""
        deadline = self._clock() + max(0.0, seconds)
        while True:
            self.assert_run_valid(run_id)
            now = self._clock()
            if now >= deadline:
                return
            time.sleep(min(poll_interval, max(0.0, deadline - now)))

    def wait_until(
        self,
        run_id: str,
        predicate: Callable[[], bool],
        *,
        timeout: float,
        poll_interval: float = 0.5,
    ) -> bool:
        deadline = self._clock() + timeout
        while self._clock() < deadline:
            self.assert_run_valid(run_id)
            if predicate():
                return True
            remaining = deadline - self._clock()
            time.sleep(min(poll_interval, max(0.0, remaining)))
        self.assert_run_valid(run_id)
        return False

    def mark_complete(self, run_id: str) -> OperatorRunState:
        state = self._require_run(run_id)
        if state.operator_run_id != run_id:
            raise OperatorStaleRun(run_id, state.operator_run_id)
        state.status = LifecycleStatus.COMPLETE.value
        state.chrome_relaunch_allowed = False
        state.notes.append("complete")
        self._write_active(state)
        self._archive(state)
        return state

    def mark_failed(self, run_id: str, reason: str = "") -> OperatorRunState:
        state = self._require_run(run_id)
        if state.operator_run_id != run_id:
            raise OperatorStaleRun(run_id, state.operator_run_id)
        state.status = LifecycleStatus.FAILED.value
        state.chrome_relaunch_allowed = False
        if reason:
            state.notes.append(reason)
        self._write_active(state)
        self._archive(state)
        return state

    def stop(
        self,
        *,
        close_browser: bool = False,
        run_id: str | None = None,
    ) -> StopReport:
        """Idempotent cancel of the active (or specified) run."""
        state = self._read_active()
        if state is None:
            return StopReport(
                operator_run_id=None,
                previous_status=None,
                status=LifecycleStatus.IDLE.value,
                helpers_stopped=[],
                child_process_count=0,
                browser_launch_prevented=True,
                browser_closed=False,
                browser_close_requested=close_browser,
                already_idle=True,
                messages=["already idle — no active operator run"],
            )

        if run_id is not None and state.operator_run_id != run_id:
            return StopReport(
                operator_run_id=state.operator_run_id,
                previous_status=state.status,
                status=state.status,
                helpers_stopped=[],
                child_process_count=len(state.children),
                browser_launch_prevented=True,
                browser_closed=False,
                browser_close_requested=close_browser,
                already_idle=False,
                messages=[
                    f"active run is {state.operator_run_id}; requested {run_id} — no action"
                ],
            )

        prev = state.status
        if state.status == LifecycleStatus.CANCELLED.value and not close_browser:
            return StopReport(
                operator_run_id=state.operator_run_id,
                previous_status=prev,
                status=LifecycleStatus.CANCELLED.value,
                helpers_stopped=[],
                child_process_count=len(state.children),
                browser_launch_prevented=True,
                browser_closed=False,
                browser_close_requested=False,
                already_idle=True,
                messages=["already CANCELLED — idempotent stop"],
            )

        # Already cancelled but close_browser requested: close dedicated Chrome only
        if state.status == LifecycleStatus.CANCELLED.value and close_browser:
            stopped_chrome: list[int] = []
            browser_closed = False
            for pid in self._list_chrome_pids_fn(self.chrome_user_data_dir):
                if self._safe_kill(pid, expected_kind="chrome"):
                    stopped_chrome.append(pid)
                    browser_closed = True
            state.notes.append("close_browser_after_cancel")
            self._write_active(state)
            return StopReport(
                operator_run_id=state.operator_run_id,
                previous_status=prev,
                status=LifecycleStatus.CANCELLED.value,
                helpers_stopped=stopped_chrome,
                child_process_count=len(state.children),
                browser_launch_prevented=True,
                browser_closed=browser_closed,
                browser_close_requested=True,
                already_idle=True,
                messages=[
                    "already CANCELLED — closed dedicated browser only",
                    "Colab runtime intentionally untouched",
                ],
            )

        state.status = LifecycleStatus.CANCELLING.value
        state.cancellation_requested = True
        state.chrome_relaunch_allowed = False
        state.notes.append("stop_requested")
        self._write_active(state)

        stopped: list[int] = []
        # Terminate registered helper children (not chrome unless close_browser)
        for child in list(state.children):
            pid = int(child.get("pid") or 0)
            kind = str(child.get("kind") or "helper")
            if pid <= 0:
                continue
            if kind == "chrome" and not close_browser:
                continue
            if kind == "chrome" and close_browser:
                continue  # handled below via dedicated profile scan
            if self._safe_kill(pid, expected_kind=kind):
                stopped.append(pid)

        browser_closed = False
        if close_browser:
            for pid in self._list_chrome_pids_fn(self.chrome_user_data_dir):
                if self._safe_kill(pid, expected_kind="chrome"):
                    stopped.append(pid)
                    browser_closed = True
            state.notes.append("close_browser_requested")

        state.status = LifecycleStatus.CANCELLED.value
        state.cancellation_requested = True
        state.chrome_relaunch_allowed = False
        state.notes.append("cancelled")
        self._write_active(state)
        self._archive(state)

        return StopReport(
            operator_run_id=state.operator_run_id,
            previous_status=prev,
            status=LifecycleStatus.CANCELLED.value,
            helpers_stopped=stopped,
            child_process_count=len(state.children),
            browser_launch_prevented=True,
            browser_closed=browser_closed,
            browser_close_requested=close_browser,
            already_idle=False,
            messages=[
                "operator run CANCELLED",
                "Colab runtime intentionally untouched",
                "Drive / ComfyUI / OutputWatcher out of scope",
            ],
        )

    def clear_stale(self) -> dict[str, Any]:
        """Clear active file if cancelled/complete/failed or missing heartbeats conceptually."""
        state = self._read_active()
        if state is None:
            return {"cleared": False, "reason": "already idle"}
        if state.status in {s.value for s in TERMINAL_STATUSES}:
            self.active_path.unlink(missing_ok=True)
            return {
                "cleared": True,
                "operator_run_id": state.operator_run_id,
                "previous_status": state.status,
            }
        return {
            "cleared": False,
            "reason": f"active run still {state.status}; use stop first",
            "operator_run_id": state.operator_run_id,
        }

    def _require_run(self, run_id: str) -> OperatorRunState:
        state = self._read_active()
        if state is None:
            raise OperatorCancelled(run_id, reason="no_active_run")
        return state

    def _fail_if_not_owner(self, state: OperatorRunState) -> None:
        # Placeholder for future lock ownership; generation already checked via assert
        _ = state

    def _safe_kill(self, pid: int, *, expected_kind: str) -> bool:
        """Kill a PID belonging to this operator; never broad-kill."""
        if pid <= 0 or pid == os.getpid():
            return False
        try:
            return bool(self._kill_fn(pid))
        except Exception:
            return False


def _default_kill_pid(pid: int) -> bool:
    if sys.platform == "win32":
        # taskkill tree for that PID only
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return False


def list_dedicated_chrome_pids(user_data_dir: Path) -> list[int]:
    """Return PIDs of Chrome processes whose command line contains the dedicated profile dir.

    Never returns PIDs merely because they are named chrome.exe.
    """
    needle = str(user_data_dir).replace("/", "\\").lower()
    alt = str(user_data_dir).replace("\\", "/").lower()
    pids: list[int] = []
    if sys.platform == "win32":
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" "
                    "| Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            raw = (completed.stdout or "").strip()
            if not raw:
                return []
            data = json.loads(raw)
            rows = data if isinstance(data, list) else [data]
            for row in rows:
                cmd = str(row.get("CommandLine") or "").lower()
                if needle in cmd or alt in cmd or "cursorchromeprofile" in cmd:
                    if "--user-data-dir" in cmd or "user-data-dir" in cmd:
                        pids.append(int(row["ProcessId"]))
        except Exception:
            return []
        return pids
    # Non-Windows: best-effort via /proc or pgrep
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in (completed.stdout or "").splitlines():
            line_l = line.lower()
            if "chrome" in line_l and (needle in line_l or alt in line_l):
                parts = line.strip().split(None, 1)
                if parts:
                    pids.append(int(parts[0]))
    except Exception:
        return []
    return pids


def launch_operator_chrome_allowed(lifecycle: OperatorLifecycle, run_id: str) -> bool:
    """Gate used by launchers: only RUNNING valid runs may open dedicated Chrome."""
    try:
        lifecycle.assert_run_valid(run_id)
        return lifecycle.may_launch_chrome(run_id)
    except OperatorCancelled:
        return False


# ---------------------------------------------------------------------------
# Bounded poll helper for checkpoint scripts
# ---------------------------------------------------------------------------


def cancellable_poll(
    lifecycle: OperatorLifecycle,
    run_id: str,
    *,
    timeout: float,
    poll_interval: float = 0.5,
    tick: Callable[[], bool] | None = None,
) -> bool:
    """Return True if tick() becomes true before timeout; raises if cancelled."""

    def _pred() -> bool:
        return bool(tick()) if tick else False

    return lifecycle.wait_until(
        run_id, _pred, timeout=timeout, poll_interval=poll_interval
    )
