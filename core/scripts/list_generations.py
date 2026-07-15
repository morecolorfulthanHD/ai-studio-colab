#!/usr/bin/env python3
"""List recent generation evidence records."""

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

from core.runtime.generation_history import list_recent_generations, prompt_excerpt, provenance_label
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="List recent generation evidence records.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--verified-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    ledger_path = bundle.path("drive_logs") / "generation_evidence.jsonl"
    rows = list_recent_generations(ledger_path, limit=args.limit, verified_only=args.verified_only)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print("AI Studio — Recent Generations")
    print("=" * 40)
    if not rows:
        print("No generation records found.")
        return 0
    for row in rows:
        print(
            f"{row.get('created_timestamp', '')} | {row.get('sync_status', '')} | "
            f"{row.get('capability') or 'unknown'} | {row.get('workflow_identifier') or 'unknown'} | "
            f"{prompt_excerpt(row)}"
        )
        print(f"  prompt_id={row.get('prompt_id')} provenance={provenance_label(row)}")
        if row.get("drive_path"):
            print(f"  drive={row.get('drive_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
