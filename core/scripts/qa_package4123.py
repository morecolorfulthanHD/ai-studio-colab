#!/usr/bin/env python3
"""Package 4.12.3 consolidated automated QA runner."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.package4123_qa import run_consolidated_package4123_qa
from core.runtime.registry_loader import find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Package 4.12.3 consolidated QA.")
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="JSON report path (default: logs/qa/package_4_12_3_latest.json under Drive or repo).",
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    report = run_consolidated_package4123_qa(
        repo_root,
        report_path=args.report_path,
        print_summary=True,
        write_reports=True,
    )
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
