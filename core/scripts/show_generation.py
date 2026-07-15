#!/usr/bin/env python3
"""Show generation evidence for a specific prompt ID."""

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

from core.runtime.generation_history import find_generation_by_prompt_id, provenance_label
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Show generation evidence for a prompt ID.")
    parser.add_argument("--prompt-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    ledger_path = bundle.path("drive_logs") / "generation_evidence.jsonl"
    rows = find_generation_by_prompt_id(ledger_path, args.prompt_id)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0 if rows else 1

    print(f"AI Studio — Generation {args.prompt_id}")
    print("=" * 40)
    if not rows:
        print("No records found.")
        return 1
    for row in rows:
        print(json.dumps(row, indent=2))
        print(f"provenance_label={provenance_label(row)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
