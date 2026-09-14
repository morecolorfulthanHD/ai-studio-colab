#!/usr/bin/env python3
"""Real CLI-surface E2E tests for colab_operator_control.py run-helper.

Tests the ACTUAL control CLI (subprocess), not only class-level APIs:

  A) Abrupt run-helper parent death → contained helper dies (Windows Job Object)
  B) Explicit stop → helper exits promptly; run-helper returns CANCELLED

Abrupt Job Object death proof is REQUIRED on Windows; skipped elsewhere.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

REPO = Path(__file__).resolve().parents[2]
CONTROL = REPO / "core" / "scripts" / "colab_operator_control.py"
LAUNCH_CHROME = REPO / "core" / "scripts" / "launch_operator_chrome.py"


def _pass(results: list[tuple[str, str]], label: str) -> None:
    results.append(("PASS", label))
    print(f"  [PASS] {label}")


def _assert_true(label: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {label}")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        out = (completed.stdout or "").strip()
        return str(pid) in out and "No tasks" not in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _wait_pid_dead(pid: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    return not _pid_alive(pid)


def _control(state_dir: Path, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CONTROL), "--state-dir", str(state_dir), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO),
        timeout=timeout,
    )


def _begin(state_dir: Path, checkpoint: str) -> str:
    completed = _control(state_dir, "begin", "--checkpoint", checkpoint)
    _assert_true(f"begin exit 0 ({checkpoint})", completed.returncode == 0)
    data = json.loads(completed.stdout)
    run_id = data.get("operator_run_id") or (data.get("run") or {}).get("operator_run_id")
    _assert_true("begin returned operator_run_id", bool(run_id))
    return str(run_id)


def _parse_run_helper_meta(stdout: str) -> dict:
    # First JSON object printed by run-helper before child output.
    text = (stdout or "").strip()
    # Find first {...} block
    start = text.find("{")
    if start < 0:
        raise AssertionError(f"run-helper produced no JSON meta: {stdout!r}")
    decoder = json.JSONDecoder()
    obj, _end = decoder.raw_decode(text[start:])
    if not isinstance(obj, dict):
        raise AssertionError(f"run-helper meta not a dict: {obj!r}")
    return obj


def _start_run_helper(
    state_dir: Path,
    run_id: str,
    helper_argv: list[str],
) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            str(CONTROL),
            "--state-dir",
            str(state_dir),
            "run-helper",
            "--run-id",
            run_id,
            "--",
            *helper_argv,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO),
    )


def _read_meta_from_proc(proc: subprocess.Popen, timeout: float = 15.0) -> dict:
    """Read stdout until JSON meta is available (parent stays alive)."""
    deadline = time.time() + timeout
    buf = ""
    assert proc.stdout is not None
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line:
            buf += line
            if "{" in buf and "}" in buf:
                try:
                    return _parse_run_helper_meta(buf)
                except Exception:
                    pass
        elif proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            raise AssertionError(
                f"run-helper exited early rc={proc.returncode} stdout={buf!r} stderr={err!r}"
            )
        else:
            time.sleep(0.05)
    raise AssertionError(f"timeout waiting for run-helper meta; buf={buf!r}")


def test_a_abrupt_parent_death(results: list[tuple[str, str]]) -> None:
    if sys.platform != "win32":
        print("  [SKIP] Test A abrupt run-helper parent death (Windows only)")
        results.append(("SKIP", "Test A abrupt run-helper parent death (non-Windows)"))
        return

    with tempfile.TemporaryDirectory(prefix="op_runhelper_a_") as td:
        state_dir = Path(td) / "operator"
        run_id = _begin(state_dir, "RUNHELPER_ABRUPT")

        helper = [
            sys.executable,
            "-c",
            "import time; time.sleep(300)",
        ]
        parent = _start_run_helper(state_dir, run_id, helper)
        meta = _read_meta_from_proc(parent)
        helper_pid = int(meta["helper_pid"])
        parent_pid = int(parent.pid)
        _assert_true("helper contained True", meta.get("contained") is True)
        _assert_true("helper alive after start", _pid_alive(helper_pid))
        _assert_true("run-helper parent alive", _pid_alive(parent_pid))

        # Abruptly kill containment parent WITHOUT stop().
        kill = subprocess.run(
            ["taskkill", "/PID", str(parent_pid), "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        _assert_true("taskkill parent ok", kill.returncode == 0)
        _assert_true("parent dead", _wait_pid_dead(parent_pid, timeout=10))
        _assert_true("helper died after parent death", _wait_pid_dead(helper_pid, timeout=15))

        # Lifecycle still has the old run until superseded; begin a new run and
        # prove the old run_id is stale / cannot relaunch helpers or Chrome.
        new_id = _begin(state_dir, "RUNHELPER_AFTER_ABRUPT")
        _assert_true("new run id differs", new_id != run_id)

        refused = _control(
            state_dir,
            "run-helper",
            "--run-id",
            run_id,
            "--",
            sys.executable,
            "-c",
            "print('should-not-run')",
            timeout=30,
        )
        _assert_true("stale run-helper refused", refused.returncode == 3)
        _assert_true(
            "stale message present",
            "REFUSED" in (refused.stderr or "") or "stale" in (refused.stderr or "").lower(),
        )

        chrome = subprocess.run(
            [
                sys.executable,
                str(LAUNCH_CHROME),
                "--state-dir",
                str(state_dir),
                "--run-id",
                run_id,
                "--colab-url",
                "https://example.invalid/colab",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(REPO),
            timeout=30,
            env={**os.environ, "CHROME_PATH": sys.executable},
        )
        _assert_true("stale chrome launch refused", chrome.returncode == 3)

        # Cleanup active run
        _control(state_dir, "stop")
        _pass(results, "Test A: abrupt run-helper parent death kills helper + stale gate")


def test_b_explicit_stop(results: list[tuple[str, str]]) -> None:
    with tempfile.TemporaryDirectory(prefix="op_runhelper_b_") as td:
        state_dir = Path(td) / "operator"
        run_id = _begin(state_dir, "RUNHELPER_STOP")

        helper = [
            sys.executable,
            "-c",
            "import time; time.sleep(300)",
        ]
        parent = _start_run_helper(state_dir, run_id, helper)
        meta = _read_meta_from_proc(parent)
        helper_pid = int(meta["helper_pid"])
        _assert_true("B helper alive", _pid_alive(helper_pid))
        if sys.platform == "win32":
            _assert_true("B helper contained", meta.get("contained") is True)

        stop = _control(state_dir, "stop", timeout=30)
        _assert_true("stop exit 0", stop.returncode == 0)
        stop_data = json.loads(stop.stdout)
        _assert_true("stop CANCELLED", stop_data.get("status") == "CANCELLED")

        _assert_true("B helper exited promptly", _wait_pid_dead(helper_pid, timeout=15))

        try:
            parent.wait(timeout=20)
        except subprocess.TimeoutExpired:
            parent.kill()
            raise AssertionError("FAIL: run-helper did not exit after stop")

        # Drain pipes
        out, err = parent.communicate(timeout=5)
        _assert_true(
            "run-helper CANCELLED exit",
            parent.returncode == 130,
        )
        combined = (err or "") + (out or "")
        _assert_true(
            "CANCELLED message",
            "CANCELLED" in combined or parent.returncode == 130,
        )

        status = _control(state_dir, "status")
        st = json.loads(status.stdout)
        _assert_true("status CANCELLED", st.get("status") == "CANCELLED")

        # Chrome relaunch blocked after cancel
        chrome = subprocess.run(
            [
                sys.executable,
                str(LAUNCH_CHROME),
                "--state-dir",
                str(state_dir),
                "--run-id",
                run_id,
                "--colab-url",
                "https://example.invalid/colab",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(REPO),
            timeout=30,
            env={**os.environ, "CHROME_PATH": sys.executable},
        )
        _assert_true("chrome blocked after cancel", chrome.returncode == 3)

        _pass(results, "Test B: explicit stop kills helper; run-helper exits CANCELLED")


def test_run_helper_propagates_exit_code(results: list[tuple[str, str]]) -> None:
    with tempfile.TemporaryDirectory(prefix="op_runhelper_c_") as td:
        state_dir = Path(td) / "operator"
        run_id = _begin(state_dir, "RUNHELPER_EXIT")
        completed = _control(
            state_dir,
            "run-helper",
            "--run-id",
            run_id,
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(42)",
            timeout=30,
        )
        _assert_true("propagates child exit 42", completed.returncode == 42)
        meta = _parse_run_helper_meta(completed.stdout)
        _assert_true("meta ok", meta.get("ok") is True)
        _control(state_dir, "stop")
        _pass(results, "run-helper propagates child exit code")


def main() -> int:
    results: list[tuple[str, str]] = []
    test_run_helper_propagates_exit_code(results)
    test_b_explicit_stop(results)
    test_a_abrupt_parent_death(results)
    passed = sum(1 for s, _ in results if s == "PASS")
    skipped = sum(1 for s, _ in results if s == "SKIP")
    print(
        f"\nsimulate_operator_run_helper_cli: {passed} passed, {skipped} skipped, "
        f"{len(results)} total"
    )
    if sys.platform == "win32" and not any(
        "abrupt run-helper parent death" in label for status, label in results if status == "PASS"
    ):
        raise AssertionError("FAIL: Windows abrupt run-helper parent-death proof missing")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
