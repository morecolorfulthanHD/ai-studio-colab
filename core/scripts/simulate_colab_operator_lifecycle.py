#!/usr/bin/env python3
"""Deterministic simulations for Colab operator lifecycle / cancellation."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.colab_operator_lifecycle import (
    LifecycleStatus,
    OperatorCancelled,
    OperatorLifecycle,
    OperatorStaleRun,
    launch_operator_chrome_allowed,
)


def _pass(results: list[tuple[str, str]], label: str) -> None:
    results.append(("PASS", label))
    print(f"  [PASS] {label}")


def _assert_true(label: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {label}")


def main() -> int:
    results: list[tuple[str, str]] = []
    killed: list[int] = []

    def kill_fn(pid: int) -> bool:
        killed.append(int(pid))
        return True

    with tempfile.TemporaryDirectory(prefix="op_life_") as td:
        state_dir = Path(td) / "operator"
        chrome_dir = Path(td) / "CursorChromeProfile"
        chrome_dir.mkdir(parents=True)
        fake_chrome_pids = {9001, 9002}

        def list_chrome(_path: Path) -> list[int]:
            return sorted(fake_chrome_pids)

        life = OperatorLifecycle(
            state_dir=state_dir,
            chrome_user_data_dir=chrome_dir,
            kill_fn=kill_fn,
            list_chrome_pids_fn=list_chrome,
        )

        # A. begin -> RUNNING
        run = life.begin(checkpoint_label="TEST_A")
        _assert_true("A status RUNNING", run.status == LifecycleStatus.RUNNING.value)
        _assert_true("A has run id", run.operator_run_id.startswith("oprun_"))
        _pass(results, "A. begin run -> RUNNING")

        # B. cancellation -> CANCELLING -> CANCELLED
        killed.clear()
        life.register_child(run.operator_run_id, 4242, kind="helper", argv0="_checkpoint_x.py")
        report = life.stop()
        _assert_true("B cancelled", report.status == LifecycleStatus.CANCELLED.value)
        _assert_true("B stopped helper", 4242 in report.helpers_stopped)
        st = life.status()
        _assert_true("B active CANCELLED", st["status"] == LifecycleStatus.CANCELLED.value)
        _assert_true("B cancellation_requested", st["cancellation_requested"] is True)
        _pass(results, "B. cancellation -> CANCELLED")

        # C. long polling exits promptly when cancelled
        life2 = OperatorLifecycle(
            state_dir=Path(td) / "operator2",
            chrome_user_data_dir=chrome_dir,
            kill_fn=kill_fn,
            list_chrome_pids_fn=lambda _p: [],
        )
        run2 = life2.begin(checkpoint_label="POLL")
        t0 = time.monotonic()

        def cancel_soon() -> None:
            time.sleep(0.15)
            life2.stop()

        threading.Thread(target=cancel_soon, daemon=True).start()
        raised = False
        try:
            life2.cooperative_sleep(run2.operator_run_id, 30.0, poll_interval=0.05)
        except OperatorCancelled:
            raised = True
        elapsed = time.monotonic() - t0
        _assert_true("C raised cancelled", raised)
        _assert_true("C exited promptly", elapsed < 2.0)
        _pass(results, "C. long polling loop exits promptly when cancelled")

        # D/E. child terminated; unrelated not
        killed.clear()
        life3 = OperatorLifecycle(
            state_dir=Path(td) / "operator3",
            chrome_user_data_dir=chrome_dir,
            kill_fn=kill_fn,
            list_chrome_pids_fn=lambda _p: [],
        )
        run3 = life3.begin()
        life3.register_child(run3.operator_run_id, 111, kind="helper")
        unrelated = 999999
        life3.stop()
        _assert_true("D helper killed", 111 in killed)
        _assert_true("E unrelated not killed", unrelated not in killed)
        _pass(results, "D/E. owned helper terminated; unrelated not")

        # F/G. cancelled cannot launch chrome / enqueue helper
        life4 = OperatorLifecycle(
            state_dir=Path(td) / "operator4",
            chrome_user_data_dir=chrome_dir,
            kill_fn=kill_fn,
            list_chrome_pids_fn=lambda _p: [],
        )
        run4 = life4.begin()
        life4.stop()
        _assert_true("F no chrome launch", not launch_operator_chrome_allowed(life4, run4.operator_run_id))
        _assert_true("G no spawn helpers", not life4.may_spawn_helpers(run4.operator_run_id))
        reg_failed = False
        try:
            life4.register_child(run4.operator_run_id, 222, kind="helper")
        except OperatorCancelled:
            reg_failed = True
        _assert_true("G register helper fails closed", reg_failed)
        _pass(results, "F/G. cancelled cannot launch Chrome or enqueue helpers")

        # H. manual close does not reopen (relaunch gate stays false)
        _assert_true(
            "H relaunch still denied after cancel",
            not life4.may_launch_chrome(run4.operator_run_id),
        )
        _pass(results, "H. cancelled run cannot reopen dedicated Chrome")

        # I. stop idempotent
        r1 = life4.stop()
        r2 = life4.stop()
        _assert_true("I first already cancelled or cancel", r1.status == LifecycleStatus.CANCELLED.value)
        _assert_true("I second idempotent", r2.already_idle or r2.status == LifecycleStatus.CANCELLED.value)
        _pass(results, "I. stop is idempotent")

        # J. new explicit run gets new id
        life5 = OperatorLifecycle(
            state_dir=Path(td) / "operator5",
            chrome_user_data_dir=chrome_dir,
            kill_fn=kill_fn,
            list_chrome_pids_fn=lambda _p: [],
        )
        a = life5.begin(checkpoint_label="J1")
        life5.stop()
        b = life5.begin(checkpoint_label="J2")
        _assert_true("J new id", a.operator_run_id != b.operator_run_id)
        _assert_true("J running", b.status == LifecycleStatus.RUNNING.value)
        _assert_true("J chrome allowed for new", life5.may_launch_chrome(b.operator_run_id))
        _pass(results, "J. new explicit run receives new run_id")

        # K. stale old-run cannot act after newer run
        old_id = a.operator_run_id
        stale = False
        try:
            life5.assert_run_valid(old_id)
        except (OperatorStaleRun, OperatorCancelled):
            stale = True
        _assert_true("K stale fails closed", stale)
        _pass(results, "K. stale old-run process cannot act after newer run")

        # L. stop without --close-browser leaves chrome open
        killed.clear()
        life6 = OperatorLifecycle(
            state_dir=Path(td) / "operator6",
            chrome_user_data_dir=chrome_dir,
            kill_fn=kill_fn,
            list_chrome_pids_fn=list_chrome,
        )
        run6 = life6.begin()
        life6.register_child(run6.operator_run_id, 9001, kind="chrome")
        life6.register_child(run6.operator_run_id, 333, kind="helper")
        rep = life6.stop(close_browser=False)
        _assert_true("L helper stopped", 333 in rep.helpers_stopped)
        _assert_true("L chrome not closed", rep.browser_closed is False)
        _assert_true("L chrome not in helpers_stopped", 9001 not in rep.helpers_stopped)
        _assert_true("L chrome pid not killed", 9001 not in killed)
        _pass(results, "L. stop without --close-browser leaves dedicated Chrome open")

        # M. stop --close-browser targets only dedicated profile pids
        killed.clear()
        life7 = OperatorLifecycle(
            state_dir=Path(td) / "operator7",
            chrome_user_data_dir=chrome_dir,
            kill_fn=kill_fn,
            list_chrome_pids_fn=list_chrome,
        )
        run7 = life7.begin()
        rep7 = life7.stop(close_browser=True)
        _assert_true("M browser closed flag", rep7.browser_closed is True)
        _assert_true("M dedicated pids killed", 9001 in killed and 9002 in killed)
        _assert_true("M no magic unrelated", 123456 not in killed)
        _pass(results, "M. stop --close-browser targets only dedicated Chrome PIDs")

        # N. Colab runtime outside destructive scope (documented in report)
        _assert_true("N untouched flag", rep7.colab_runtime_untouched is True)
        _assert_true(
            "N message mentions untouched",
            any("untouched" in m.lower() for m in rep7.messages),
        )
        _pass(results, "N. Colab runtime/Drive/ComfyUI out of local cancellation scope")

        # clear-stale
        cleared = life7.clear_stale()
        _assert_true("clear-stale ok", cleared.get("cleared") is True)
        _pass(results, "clear-stale removes terminal active_run.json")

    print(f"\nsimulate_colab_operator_lifecycle: {len(results)} checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
