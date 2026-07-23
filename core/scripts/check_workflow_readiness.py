#!/usr/bin/env python3
"""Check workflow library readiness."""

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

from core.runtime.registry_loader import find_repo_root
from core.runtime.workflow_readiness import evaluate_workflow_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description="Check workflow library readiness.")
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--allow-experimental", action="store_true")
    parser.add_argument("--allow-benchmark", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    try:
        readiness = evaluate_workflow_readiness(
            repo_root,
            args.workflow,
            allow_experimental=args.allow_experimental,
            allow_benchmark=args.allow_benchmark,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(readiness.to_dict(), indent=2))
    else:
        print("AI Studio — Workflow Readiness")
        print("=" * 40)
        print(f"Workflow: {args.workflow}")
        print(f"Status:   {readiness.status}")
        if args.summary or readiness.reasons:
            for reason in readiness.reasons:
                print(f"  - {reason}")

    if readiness.status in {"ready", "partial", "experimental", "benchmark_only"} and not readiness.reasons:
        print("\nRESULT: OK")
        return 0
    if readiness.status == "blocked" or readiness.reasons:
        print("\nRESULT: FAIL", file=sys.stderr)
        return 1
    print("\nRESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
