#!/usr/bin/env python3
"""Report identity architecture benchmark ledger (+ optional QA summary)."""

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

from core.runtime.identity_architecture_benchmark import (
    architecture_ledger_path,
    format_architecture_benchmark_report,
    load_architecture_benchmark_records,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Report Package 4.12.3 identity architecture benchmark.")
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--qa-report", type=Path, default=None, help="Optional QA JSON report to summarize.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    ledger = args.ledger or architecture_ledger_path(bundle.path("drive_root"))
    records = load_architecture_benchmark_records(ledger)

    qa_summary = None
    if args.qa_report and args.qa_report.is_file():
        try:
            qa_summary = json.loads(args.qa_report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            qa_summary = {"error": "unreadable qa report"}

    if args.json:
        print(
            json.dumps(
                {
                    "ledger": str(ledger),
                    "records": records,
                    "qa_summary": qa_summary,
                },
                indent=2,
            )
        )
    else:
        print(format_architecture_benchmark_report(records))
        if qa_summary is not None:
            print("\nQA summary")
            print("-" * 40)
            if isinstance(qa_summary, dict):
                print(f"all_required_suites_pass: {qa_summary.get('all_required_suites_pass')}")
                totals = qa_summary.get("totals") or {}
                print(f"passed: {totals.get('passed')} / {totals.get('total')}")
            else:
                print(str(qa_summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
