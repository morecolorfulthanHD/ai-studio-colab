#!/usr/bin/env python3
"""Rebuild the generation index from evidence and on-disk snapshots."""

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

from core.runtime.generation_index import rebuild_index_from_sources
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild AI Studio generation index.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run or --apply.")
    if args.dry_run and args.apply:
        parser.error("Choose only one of --dry-run or --apply.")

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    result = rebuild_index_from_sources(
        evidence_path=bundle.path("drive_logs") / "generation_evidence.jsonl",
        drive_root=bundle.path("drive_root"),
        apply=bool(args.apply),
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        mode = "apply" if args.apply else "dry-run"
        print(f"Generation index rebuild ({mode}): {result['records']} record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
