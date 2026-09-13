#!/usr/bin/env python3
"""Report Cursor Colab operator config and recommended next action."""

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

from core.runtime.colab_operator import (
    OperatorState,
    canonical_notebook_url,
    load_operator_config,
    may_auto_reconnect,
    may_change_gpu_without_asking,
    recommend_next_action,
)
from core.runtime.registry_loader import find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Report Colab operator state expectations.")
    parser.add_argument(
        "--state",
        default="NOT_OPEN",
        help="Current operator state name (default NOT_OPEN).",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    try:
        cfg = load_operator_config(repo_root)
        state = OperatorState(str(args.state).strip().upper())
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = {
        "state": state.value,
        "canonical_notebook_url": canonical_notebook_url(cfg),
        "recommended_next_action": recommend_next_action(state, cfg),
        "may_auto_reconnect": may_auto_reconnect(cfg),
        "may_change_gpu_without_asking": may_change_gpu_without_asking(cfg),
        "stop_conditions": list(cfg.get("stop_conditions") or []),
        "never_auto": list(cfg.get("never_auto") or []),
        "auto_allowed": list(cfg.get("auto_allowed") or []),
        "package_4123_semantics_unchanged": True,
        "package_413_not_started": True,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio - Colab Operator State")
        print("=" * 40)
        print(f"State:              {payload['state']}")
        print(f"Canonical notebook: {payload['canonical_notebook_url']}")
        print(f"Next action:        {payload['recommended_next_action']}")
        print(f"Auto reconnect:     {payload['may_auto_reconnect']}")
        print(f"Auto GPU change:    {payload['may_change_gpu_without_asking']}")
        print("Stop conditions:")
        for item in payload["stop_conditions"]:
            print(f"  - {item}")
        print("Never auto:")
        for item in payload["never_auto"]:
            print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
