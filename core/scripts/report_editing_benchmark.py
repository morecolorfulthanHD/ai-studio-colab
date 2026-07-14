#!/usr/bin/env python3
"""Report editing benchmark ledger contents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.editing_benchmark import format_benchmark_report, load_benchmark_records
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Report modern editing benchmark ledger.")
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    repo_root = find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    ledger = args.ledger or (bundle.path("drive_logs") / "editing_benchmark.jsonl")
    records = load_benchmark_records(ledger)
    if args.json:
        print(json.dumps({"ledger": str(ledger), "records": records}, indent=2))
    else:
        print(format_benchmark_report(records))
        print(f"\nLedger: {ledger}")
    print("\nRESULT: OK — benchmark report complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
