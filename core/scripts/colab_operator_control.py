#!/usr/bin/env python3
"""First-class Colab operator lifecycle control surface.

Commands:
  status
  begin [--checkpoint LABEL]
  stop [--close-browser] [--run-id ID]
  clear-stale

Local orchestration only. Never disconnects Colab, Full Resets, or deletes Drive.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.colab_operator_lifecycle import OperatorLifecycle


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2, default=str))


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

    args = parser.parse_args(argv)
    life = OperatorLifecycle(state_dir=Path(args.state_dir) if args.state_dir else None)

    if args.cmd == "status":
        _print(life.status())
        return 0
    if args.cmd == "begin":
        state = life.begin(checkpoint_label=args.checkpoint)
        _print({"ok": True, "run": state.to_dict()})
        return 0
    if args.cmd == "stop":
        report = life.stop(close_browser=bool(args.close_browser), run_id=args.run_id)
        _print(report.to_dict())
        return 0
    if args.cmd == "clear-stale":
        _print(life.clear_stale())
        return 0
    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
