#!/usr/bin/env python3
"""First-class Colab operator lifecycle control surface.

Commands:
  status
  begin [--checkpoint LABEL]
  stop [--close-browser] [--run-id ID]
  clear-stale
  run-helper --run-id ID -- <command...>

Local orchestration only. Never disconnects Colab, Full Resets, or deletes Drive.

``run-helper`` keeps this process alive as the Job Object containment owner for
the full lifetime of the child. Do not wrap it in a fire-and-forget launcher
that exits immediately — that would close the job and kill the helper.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.colab_operator_lifecycle import (
    OperatorCancelled,
    OperatorLifecycle,
    _default_kill_pid,
)

# Distinct exit code when cooperative cancellation stops a contained helper.
EXIT_CANCELLED = 130


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _strip_argv_separator(argv: list[str]) -> list[str]:
    if argv and argv[0] == "--":
        return list(argv[1:])
    return list(argv)


def _terminate_child(proc: subprocess.Popen) -> None:
    """Best-effort terminate helper process tree; never raises."""
    pid = int(getattr(proc, "pid", 0) or 0)
    if pid <= 0:
        return
    if proc.poll() is not None:
        return
    try:
        _default_kill_pid(pid)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass


def run_helper(
    life: OperatorLifecycle,
    run_id: str,
    helper_argv: list[str],
    *,
    poll_interval: float = 0.25,
) -> int:
    """Spawn a contained helper and stay alive until it exits or run cancels.

    CRITICAL: This function (and the calling process) must remain alive for the
    helper's full lifetime so the Windows Job Object handle stays open. Exiting
    early would close the job and kill the child under KILL_ON_JOB_CLOSE.
    """
    argv = _strip_argv_separator(helper_argv)
    if not argv:
        print("ERROR: run-helper requires a command after --", file=sys.stderr)
        return 2

    try:
        life.assert_run_valid(run_id)
    except OperatorCancelled as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3

    try:
        # Inherit stdout/stderr so Cursor terminals see helper output.
        spawn = life.spawn_owned_helper(
            run_id,
            argv,
            kind="helper",
            contain=True,
        )
    except OperatorCancelled as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3

    proc = spawn.popen
    meta = {
        "ok": True,
        "mode": "run-helper",
        "run_id": run_id,
        "helper_pid": spawn.pid,
        "contained": spawn.contained,
        "parent_pid": os.getpid(),
        "argv": list(spawn.argv),
        "note": "containment parent remains alive until helper exits or cancel",
    }
    _print(meta)
    sys.stdout.flush()
    sys.stderr.flush()

    cancelled = False
    try:
        while True:
            # Prefer cancellation over child-exit racing with stop()'s taskkill.
            if life.check_cancelled(run_id):
                cancelled = True
                print(
                    f"CANCELLED: run_id={run_id} terminating contained helper pid={spawn.pid}",
                    file=sys.stderr,
                )
                sys.stderr.flush()
                _terminate_child(proc)
                return EXIT_CANCELLED
            rc = proc.poll()
            if rc is not None:
                if life.check_cancelled(run_id):
                    cancelled = True
                    print(
                        f"CANCELLED: run_id={run_id} helper exited during cancel "
                        f"pid={spawn.pid} child_rc={rc}",
                        file=sys.stderr,
                    )
                    return EXIT_CANCELLED
                return int(rc)
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        cancelled = True
        print(
            f"CANCELLED: KeyboardInterrupt — terminating helper pid={spawn.pid}",
            file=sys.stderr,
        )
        _terminate_child(proc)
        return EXIT_CANCELLED
    finally:
        # Keep ``life`` (and its Job Object handle) referenced until here.
        if cancelled and proc.poll() is None:
            _terminate_child(proc)
        _ = life


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Colab operator lifecycle control")
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Override local operator state directory (tests)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show active operator run status")

    p_begin = sub.add_parser("begin", help="Start a new operator run id")
    p_begin.add_argument("--checkpoint", default="", help="Checkpoint / operation label")

    p_stop = sub.add_parser("stop", help="Cancel active operator run (idempotent)")
    p_stop.add_argument(
        "--close-browser",
        action="store_true",
        help="Also close dedicated AI Studio Chrome (CursorChromeProfile only)",
    )
    p_stop.add_argument("--run-id", default=None, help="Optional specific run id")

    sub.add_parser("clear-stale", help="Clear terminal active_run.json if cancelled/complete/failed")

    p_run = sub.add_parser(
        "run-helper",
        help=(
            "Run a long-lived operator helper under Job Object containment. "
            "This process stays alive as the containment parent until the helper exits."
        ),
    )
    p_run.add_argument("--run-id", required=True, help="Current RUNNING operator_run_id")
    p_run.add_argument(
        "helper_argv",
        nargs=argparse.REMAINDER,
        help="Helper command after -- (e.g. -- python core/scripts/_checkpoint_x.py)",
    )

    args = parser.parse_args(argv)
    life = OperatorLifecycle(state_dir=Path(args.state_dir) if args.state_dir else None)

    if args.cmd == "status":
        _print(life.status())
        return 0
    if args.cmd == "begin":
        state = life.begin(checkpoint_label=args.checkpoint)
        _print({"ok": True, "operator_run_id": state.operator_run_id, "run": state.to_dict()})
        return 0
    if args.cmd == "stop":
        report = life.stop(close_browser=bool(args.close_browser), run_id=args.run_id)
        _print(report.to_dict())
        return 0
    if args.cmd == "clear-stale":
        _print(life.clear_stale())
        return 0
    if args.cmd == "run-helper":
        return run_helper(life, args.run_id, list(args.helper_argv or []))
    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
