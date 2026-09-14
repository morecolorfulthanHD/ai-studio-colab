#!/usr/bin/env python3
"""Windows Job Object abrupt-parent-death + Chrome launch-gate simulations.

- Abrupt death test is REQUIRED on Windows; skipped elsewhere.
- Chrome gate test runs everywhere (spawn mocked / no real Chrome UI required).
"""

from __future__ import annotations

import importlib.util
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

from core.runtime.colab_operator_lifecycle import OperatorLifecycle
from core.scripts.launch_operator_chrome import launch_chrome_for_run


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


def test_chrome_relaunch_gate(results: list[tuple[str, str]]) -> None:
    with tempfile.TemporaryDirectory(prefix="op_chrome_gate_") as td:
        state_dir = Path(td) / "operator"
        spawned: list[list[str]] = []

        def fake_popen(argv, **kwargs):  # noqa: ANN001
            class _P:
                pid = 55555

            spawned.append(list(argv))
            return _P()

        life = OperatorLifecycle(
            state_dir=state_dir,
            enable_job_containment=False,
            popen_fn=fake_popen,
            list_chrome_pids_fn=lambda _p: [],
            kill_fn=lambda _pid: True,
        )
        # Point chrome path at python so resolve succeeds without Chrome UI
        os.environ["CHROME_PATH"] = sys.executable
        run = life.begin(checkpoint_label="CHROME_GATE")
        out_ok = launch_chrome_for_run(
            life,
            run.operator_run_id,
            colab_url="https://example.invalid/colab",
            force=False,
        )
        _assert_true("RUNNING launch ok", out_ok.get("ok") is True)
        _assert_true("chrome not job-contained", out_ok.get("contained") is False)
        _assert_true("chrome spawn recorded", bool(spawned))
        life.stop()
        spawned.clear()
        out_block = launch_chrome_for_run(
            life,
            run.operator_run_id,
            colab_url="https://example.invalid/colab",
            force=False,
        )
        _assert_true("cancelled refused", out_block.get("refused") is True)
        _assert_true("no spawn after cancel", spawned == [])
        _pass(results, "Chrome relaunch blocked after cancellation (launcher gate)")


def test_abrupt_parent_death_job_kills_child(results: list[tuple[str, str]]) -> None:
    if sys.platform != "win32":
        print("  [SKIP] abrupt parent-death Job Object test (Windows only)")
        results.append(("SKIP", "abrupt parent-death Job Object (non-Windows)"))
        return

    with tempfile.TemporaryDirectory(prefix="op_job_") as td:
        td_path = Path(td)
        child_pid_file = td_path / "child_pid.txt"
        state_dir = td_path / "operator"
        parent_script = td_path / "parent_holder.py"
        repo = Path(__file__).resolve().parents[2]
        # Prove abrupt parent death via the real owned-spawn API (Job Object
        # assigned inside spawn_owned_helper). Exit WITHOUT stop().
        parent_script.write_text(
            "\n".join(
                [
                    "import sys",
                    "from pathlib import Path",
                    f"sys.path.insert(0, {str(repo)!r})",
                    "from core.runtime.colab_operator_lifecycle import OperatorLifecycle",
                    f"life = OperatorLifecycle(state_dir=Path(r'{state_dir}'))",
                    "run = life.begin(checkpoint_label='ABRUPT_DEATH')",
                    "res = life.spawn_owned_helper(",
                    "    run.operator_run_id,",
                    "    [sys.executable, '-c', 'import time; time.sleep(300)'],",
                    "    kind='helper',",
                    "    contain=True,",
                    ")",
                    f"Path(r'{child_pid_file}').write_text(",
                    "    f'{res.pid}|{int(res.contained)}', encoding='utf-8'",
                    ")",
                    "# Exit WITHOUT lifecycle.stop(); process exit closes job handle.",
                    "sys.exit(0)",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        parent = subprocess.Popen([sys.executable, str(parent_script)])
        parent.wait(timeout=30)
        _assert_true("parent exited", parent.returncode == 0)
        deadline = time.time() + 10
        while time.time() < deadline and not child_pid_file.is_file():
            time.sleep(0.05)
        _assert_true("child pid file written", child_pid_file.is_file())
        raw = child_pid_file.read_text(encoding="utf-8").strip()
        child_pid_s, assigned_s = raw.split("|", 1)
        child_pid = int(child_pid_s)
        _assert_true("job assign succeeded", assigned_s == "1")
        dead = False
        for _ in range(50):
            if not _pid_alive(child_pid):
                dead = True
                break
            time.sleep(0.1)
        _assert_true("child died after parent exit (Job Object)", dead)
        _pass(results, "abrupt parent-death child cleanup via Job Object (Windows)")


def test_spawn_owned_helper_wires_containment_flag(results: list[tuple[str, str]]) -> None:
    with tempfile.TemporaryDirectory(prefix="op_spawn_") as td:
        if sys.platform == "win32":
            life2 = OperatorLifecycle(state_dir=Path(td) / "operator_real")
            run2 = life2.begin(checkpoint_label="SPAWN_REAL")
            res = life2.spawn_owned_helper(
                run2.operator_run_id,
                [sys.executable, "-c", "import time; time.sleep(2)"],
                kind="helper",
                contain=True,
            )
            _assert_true("helper pid > 0", res.pid > 0)
            _assert_true("helper job_contained True", res.contained is True)
            life2.stop()
            time.sleep(0.2)
            _pass(results, "spawn_owned_helper assigns Job Object for helpers (Windows)")
        else:

            class _P:
                pid = 8881

            life = OperatorLifecycle(
                state_dir=Path(td) / "operator",
                enable_job_containment=False,
                popen_fn=lambda argv, **kw: _P(),
                list_chrome_pids_fn=lambda _p: [],
                kill_fn=lambda _pid: True,
            )
            run = life.begin(checkpoint_label="SPAWN")
            res = life.spawn_owned_helper(
                run.operator_run_id,
                [sys.executable, "-c", "pass"],
                kind="helper",
                contain=True,
            )
            _assert_true("spawn returns", res.pid == 8881)
            _pass(results, "spawn_owned_helper API available (non-Windows; no Job Object)")


def main() -> int:
    results: list[tuple[str, str]] = []
    test_chrome_relaunch_gate(results)
    test_spawn_owned_helper_wires_containment_flag(results)
    test_abrupt_parent_death_job_kills_child(results)
    passed = sum(1 for s, _ in results if s == "PASS")
    skipped = sum(1 for s, _ in results if s == "SKIP")
    print(
        f"\nsimulate_operator_job_containment: {passed} passed, {skipped} skipped, "
        f"{len(results)} total"
    )
    if sys.platform == "win32" and not any(
        "abrupt parent-death" in label for status, label in results if status == "PASS"
    ):
        raise AssertionError("FAIL: Windows abrupt parent-death proof missing")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
