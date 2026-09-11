#!/usr/bin/env python3
"""Report FaceID conditioning-sweep tuning ledger (Package 4.12.2)."""

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

from core.runtime.identity_benchmark_tuning import (
    default_tuning_ledger_path,
    format_tuning_report,
    load_tuning_records,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report Package 4.12.2 FaceID tuning ledger. "
            "Operational capture ≠ visual scenario pass."
        )
    )
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    ledger = args.ledger or default_tuning_ledger_path(bundle.path("drive_root"))
    records = load_tuning_records(ledger)

    if args.json:
        print(json.dumps({"records": records, "ledger": str(ledger)}, indent=2))
        return 0

    print(format_tuning_report(records))
    print()
    print(f"Ledger: {ledger}")
    print(f"Loaded: {len(records)} record(s)")
    print("NOTE: Do not treat operational capture as visual scenario PASS.")
    print("NOTE: FaceID promotion remains pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
