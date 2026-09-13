#!/usr/bin/env python3
"""Cursor Colab operator state machine (orchestration only).

No browser scraping framework. Cursor Agent performs UI actions; this module
provides deterministic states, transitions, policies, and config loading.
Does not alter Package 4.12.3 benchmark semantics.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class OperatorState(str, Enum):
    NOT_OPEN = "NOT_OPEN"
    COLAB_OPEN = "COLAB_OPEN"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"
    REPO_SYNCED = "REPO_SYNCED"
    AI_STUDIO_READY = "AI_STUDIO_READY"
    FULL_LAUNCH_RUNNING = "FULL_LAUNCH_RUNNING"
    FULL_LAUNCH_READY = "FULL_LAUNCH_READY"
    LIVE_QA_RUNNING = "LIVE_QA_RUNNING"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    FAILED = "FAILED"
    COMPLETE = "COMPLETE"


class OperatorEvent(str, Enum):
    NOTEBOOK_OPENED = "NOTEBOOK_OPENED"
    AUTH_BLOCKER_SEEN = "AUTH_BLOCKER_SEEN"
    AUTH_RESOLVED = "AUTH_RESOLVED"
    RUNTIME_DISCONNECTED = "RUNTIME_DISCONNECTED"
    CONNECT_CLICKED = "CONNECT_CLICKED"
    RUNTIME_CONNECTED = "RUNTIME_CONNECTED"
    REPO_SYNC_OK = "REPO_SYNC_OK"
    RUN_ALL_DONE = "RUN_ALL_DONE"
    FULL_LAUNCH_STARTED = "FULL_LAUNCH_STARTED"
    FULL_LAUNCH_WARNINGS = "FULL_LAUNCH_WARNINGS"
    FULL_LAUNCH_FAILED = "FULL_LAUNCH_FAILED"
    FULL_LAUNCH_OK = "FULL_LAUNCH_OK"
    LIVE_QA_STARTED = "LIVE_QA_STARTED"
    LIVE_QA_HUMAN_REVIEW = "LIVE_QA_HUMAN_REVIEW"
    LIVE_QA_FAILED = "LIVE_QA_FAILED"
    LIVE_QA_OK = "LIVE_QA_OK"
    RUNTIME_DIED = "RUNTIME_DIED"
    DESTRUCTIVE_ACTION_REQUESTED = "DESTRUCTIVE_ACTION_REQUESTED"


# Allowed transitions: (state, event) -> next_state
_TRANSITIONS: dict[tuple[OperatorState, OperatorEvent], OperatorState] = {
    (OperatorState.NOT_OPEN, OperatorEvent.NOTEBOOK_OPENED): OperatorState.COLAB_OPEN,
    (OperatorState.COLAB_OPEN, OperatorEvent.AUTH_BLOCKER_SEEN): OperatorState.AUTH_REQUIRED,
    (OperatorState.COLAB_OPEN, OperatorEvent.RUNTIME_DISCONNECTED): OperatorState.DISCONNECTED,
    (OperatorState.COLAB_OPEN, OperatorEvent.RUNTIME_CONNECTED): OperatorState.CONNECTED,
    (OperatorState.AUTH_REQUIRED, OperatorEvent.AUTH_RESOLVED): OperatorState.COLAB_OPEN,
    (OperatorState.DISCONNECTED, OperatorEvent.CONNECT_CLICKED): OperatorState.DISCONNECTED,
    (OperatorState.DISCONNECTED, OperatorEvent.AUTH_BLOCKER_SEEN): OperatorState.AUTH_REQUIRED,
    (OperatorState.DISCONNECTED, OperatorEvent.RUNTIME_CONNECTED): OperatorState.CONNECTED,
    (OperatorState.CONNECTED, OperatorEvent.REPO_SYNC_OK): OperatorState.REPO_SYNCED,
    (OperatorState.CONNECTED, OperatorEvent.RUNTIME_DIED): OperatorState.DISCONNECTED,
    (OperatorState.CONNECTED, OperatorEvent.AUTH_BLOCKER_SEEN): OperatorState.AUTH_REQUIRED,
    (OperatorState.REPO_SYNCED, OperatorEvent.RUN_ALL_DONE): OperatorState.AI_STUDIO_READY,
    (OperatorState.REPO_SYNCED, OperatorEvent.RUNTIME_DIED): OperatorState.DISCONNECTED,
    (OperatorState.AI_STUDIO_READY, OperatorEvent.FULL_LAUNCH_STARTED): OperatorState.FULL_LAUNCH_RUNNING,
    (OperatorState.AI_STUDIO_READY, OperatorEvent.RUNTIME_DIED): OperatorState.DISCONNECTED,
    (OperatorState.FULL_LAUNCH_RUNNING, OperatorEvent.FULL_LAUNCH_WARNINGS): OperatorState.FULL_LAUNCH_READY,
    (OperatorState.FULL_LAUNCH_RUNNING, OperatorEvent.FULL_LAUNCH_OK): OperatorState.FULL_LAUNCH_READY,
    (OperatorState.FULL_LAUNCH_RUNNING, OperatorEvent.FULL_LAUNCH_FAILED): OperatorState.FAILED,
    (OperatorState.FULL_LAUNCH_RUNNING, OperatorEvent.RUNTIME_DIED): OperatorState.DISCONNECTED,
    (OperatorState.FULL_LAUNCH_READY, OperatorEvent.LIVE_QA_STARTED): OperatorState.LIVE_QA_RUNNING,
    (OperatorState.FULL_LAUNCH_READY, OperatorEvent.RUNTIME_DIED): OperatorState.DISCONNECTED,
    (OperatorState.LIVE_QA_RUNNING, OperatorEvent.LIVE_QA_HUMAN_REVIEW): OperatorState.HUMAN_REVIEW_REQUIRED,
    (OperatorState.LIVE_QA_RUNNING, OperatorEvent.LIVE_QA_OK): OperatorState.COMPLETE,
    (OperatorState.LIVE_QA_RUNNING, OperatorEvent.LIVE_QA_FAILED): OperatorState.FAILED,
    (OperatorState.LIVE_QA_RUNNING, OperatorEvent.RUNTIME_DIED): OperatorState.DISCONNECTED,
    # Resume after reconnect/relaunch path
    (OperatorState.DISCONNECTED, OperatorEvent.REPO_SYNC_OK): OperatorState.REPO_SYNCED,
}


TERMINAL_STOP_STATES = frozenset(
    {
        OperatorState.AUTH_REQUIRED,
        OperatorState.HUMAN_REVIEW_REQUIRED,
        OperatorState.FAILED,
        OperatorState.COMPLETE,
    }
)

DESTRUCTIVE_ACTIONS = frozenset(
    {
        "full_reset",
        "drive_deletion",
        "model_deletion",
        "project_deletion",
        "history_deletion",
        "benchmark_evidence_deletion",
    }
)


def default_config_path(repo_root: Path) -> Path:
    return Path(repo_root) / "configs" / "operator" / "colab_operator.json"


def load_operator_config(repo_root: Path | None = None) -> dict[str, Any]:
    if repo_root is None:
        # Walk up from this file
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidate = parent / "configs" / "operator" / "colab_operator.json"
            if candidate.is_file():
                repo_root = parent
                break
        if repo_root is None:
            raise FileNotFoundError("configs/operator/colab_operator.json not found")
    path = default_config_path(Path(repo_root))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("colab_operator.json must be an object")
    return data


def canonical_notebook_url(config: dict[str, Any] | None = None) -> str:
    cfg = config or load_operator_config()
    return str((cfg.get("canonical_notebook") or {}).get("colab_url") or "")


def is_auto_allowed(action: str, config: dict[str, Any] | None = None) -> bool:
    cfg = config or load_operator_config()
    action_l = str(action or "").strip().lower()
    for item in cfg.get("auto_allowed") or []:
        if action_l == str(item).strip().lower() or action_l in str(item).strip().lower():
            return True
    return False


def is_never_auto(action: str, config: dict[str, Any] | None = None) -> bool:
    cfg = config or load_operator_config()
    key = str(action or "").strip().lower().replace(" ", "_")
    if key in DESTRUCTIVE_ACTIONS:
        return True
    for item in cfg.get("never_auto") or []:
        item_l = str(item).strip().lower().replace(" ", "_")
        if key == item_l or key in item_l or str(item).strip().lower() in str(action).lower():
            return True
    return False


def may_auto_reconnect(config: dict[str, Any] | None = None) -> bool:
    cfg = config or load_operator_config()
    policy = cfg.get("restart_policy") or {}
    return bool(policy.get("may_reconnect", True))


def may_change_gpu_without_asking(config: dict[str, Any] | None = None) -> bool:
    cfg = config or load_operator_config()
    policy = cfg.get("restart_policy") or {}
    return bool(policy.get("may_change_gpu_runtime_without_asking", False))


def may_satisfy_benchmark_confirmation(*, explicit_live_run_request: bool) -> bool:
    """Routine GPU confirmation may be auto-satisfied only on explicit live-run intent.

    Merely opening the Characters menu never authorizes benchmark GPU execution.
    """
    return bool(explicit_live_run_request)


@dataclass
class TransitionResult:
    ok: bool
    from_state: str
    event: str
    to_state: str = ""
    stopped: bool = False
    human_required: bool = False
    refused_destructive: bool = False
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ColabOperatorSession:
    state: OperatorState = OperatorState.NOT_OPEN
    history: list[dict[str, str]] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)

    def apply(self, event: OperatorEvent | str) -> TransitionResult:
        ev = OperatorEvent(event) if not isinstance(event, OperatorEvent) else event

        if ev == OperatorEvent.DESTRUCTIVE_ACTION_REQUESTED:
            return TransitionResult(
                ok=False,
                from_state=self.state.value,
                event=ev.value,
                to_state=self.state.value,
                stopped=True,
                human_required=True,
                refused_destructive=True,
                errors=[
                    "ERROR: Destructive Colab/Drive action is never auto-invoked. "
                    "Ask the user explicitly."
                ],
            )

        key = (self.state, ev)
        if key not in _TRANSITIONS:
            return TransitionResult(
                ok=False,
                from_state=self.state.value,
                event=ev.value,
                to_state=self.state.value,
                errors=[
                    f"ERROR: Illegal operator transition {self.state.value} + {ev.value}."
                ],
            )

        nxt = _TRANSITIONS[key]
        prev = self.state
        self.state = nxt
        self.history.append({"from": prev.value, "event": ev.value, "to": nxt.value})

        human = nxt in {
            OperatorState.AUTH_REQUIRED,
            OperatorState.HUMAN_REVIEW_REQUIRED,
        }
        stopped = nxt in TERMINAL_STOP_STATES
        messages: list[str] = [f"{prev.value} --{ev.value}--> {nxt.value}"]
        if nxt == OperatorState.AUTH_REQUIRED:
            messages.append("STOP: auth/consent required — wait for user.")
        if nxt == OperatorState.HUMAN_REVIEW_REQUIRED:
            messages.append("STOP: HUMAN_REVIEW_REQUIRED — do not silently continue.")
        if nxt == OperatorState.FAILED:
            messages.append("STOP: FAILED — report and await user direction.")
        if nxt == OperatorState.FULL_LAUNCH_READY and ev == OperatorEvent.FULL_LAUNCH_WARNINGS:
            messages.append("Full Launch warnings only — proceed (not a hard fail).")
        if prev == OperatorState.DISCONNECTED and ev == OperatorEvent.CONNECT_CLICKED:
            if may_auto_reconnect(self.config or None):
                messages.append(
                    "Connect requested; wait for runtime-connected evidence "
                    "(CONNECT_CLICKED does not imply CONNECTED)."
                )
            else:
                messages.append("Connect requested; wait for runtime-connected evidence.")
            # Stay DISCONNECTED until RUNTIME_CONNECTED.
            stopped = False
            human = False
        if prev == OperatorState.DISCONNECTED and ev == OperatorEvent.RUNTIME_CONNECTED:
            messages.append("Runtime-connected evidence observed → CONNECTED.")
        return TransitionResult(
            ok=True,
            from_state=prev.value,
            event=ev.value,
            to_state=nxt.value,
            stopped=stopped,
            human_required=human,
            messages=messages,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "history": list(self.history),
            "canonical_notebook_url": canonical_notebook_url(self.config or None)
            if self.config
            else "",
        }


def recommend_next_action(state: OperatorState | str, config: dict[str, Any] | None = None) -> str:
    st = OperatorState(state) if not isinstance(state, OperatorState) else state
    cfg = config or {}
    url = canonical_notebook_url(cfg) if cfg else "(configure configs/operator/colab_operator.json)"
    mapping = {
        OperatorState.NOT_OPEN: f"Open canonical notebook: {url}",
        OperatorState.COLAB_OPEN: "Detect runtime; Connect if disconnected; stop if auth.",
        OperatorState.AUTH_REQUIRED: "STOP — ask user to complete Google/Drive/GPU consent.",
        OperatorState.DISCONNECTED: (
            "Click Connect if needed, then wait for connected UI evidence "
            "(RAM/Disk/Connected) before treating runtime as CONNECTED."
        ),
        OperatorState.CONNECTED: "Run Repository Sync; verify HEAD on origin/main.",
        OperatorState.REPO_SYNCED: "Runtime → Run all; wait for control_panel ready.",
        OperatorState.AI_STUDIO_READY: "control_panel → 1 Launch → full; wait for ComfyUI + watcher.",
        OperatorState.FULL_LAUNCH_RUNNING: "Observe launch output; proceed on warnings; stop on fail.",
        OperatorState.FULL_LAUNCH_READY: (
            "Navigate Main 9 Workspace/Projects → verify title → 13 Characters → "
            "verify Characters title → requested action (e.g. 12 execute)."
        ),
        OperatorState.LIVE_QA_RUNNING: "Collect logs/QA reports; wait for completion.",
        OperatorState.HUMAN_REVIEW_REQUIRED: "STOP — human visual/license review required.",
        OperatorState.FAILED: "STOP — report failure; do not invent recovery beyond policy.",
        OperatorState.COMPLETE: "Report outcome; stop.",
    }
    return mapping.get(st, "Unknown state — ask user.")


def navigation_sequence(
    intent: str,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return nested menu navigation steps for a named live-QA intent.

    After every select, Cursor must verify ``verify_title`` (when present) in the
    visible UI before continuing. Never blindly replay numbers on the wrong screen.
    """
    cfg = config if config is not None else load_operator_config()
    sequences = cfg.get("navigation_sequences") or {}
    key = str(intent or "").strip()
    steps = sequences.get(key)
    if not isinstance(steps, list) or not steps:
        raise KeyError(
            f"Unknown navigation intent {key!r}. "
            f"Known: {', '.join(sorted(sequences)) or '(none)'}"
        )
    out: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError(f"Invalid navigation step for {key!r}: {step!r}")
        row = {
            "menu": str(step.get("menu") or ""),
            "select": str(step.get("select") or ""),
        }
        if step.get("label"):
            row["label"] = str(step.get("label"))
        if step.get("verify_title"):
            row["verify_title"] = str(step.get("verify_title"))
        out.append(row)
    return out


def assert_expected_menu_title(visible_text: str, expected_title: str) -> bool:
    """True when expected submenu title appears in visible browser/notebook text."""
    needle = str(expected_title or "").strip()
    hay = str(visible_text or "")
    return bool(needle) and needle in hay
