#!/usr/bin/env python3
"""List workflow JSON files under workflows/, grouped by category."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.registry_loader import find_repo_root


def category_for(workflows_root: Path, json_path: Path) -> str:
    rel = json_path.relative_to(workflows_root)
    parts = rel.parts
    return parts[0] if len(parts) > 1 else "root"


def main() -> int:
    parser = argparse.ArgumentParser(description="List workflow JSON files in workflows/.")
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args()

    print("AI Studio Colab — Workflow Listing")
    print("=" * 40)

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    workflows_root = repo_root / "workflows"
    print(f"Workflows root: {workflows_root}\n")

    json_files = sorted(workflows_root.rglob("*.json"))
    if not json_files:
        print("No workflow JSON files found.")
        print("  [info] Workflow JSON assets will appear here as phases are implemented.")
        print("\nRESULT: OK (empty registry on disk).")
        return 0

    by_category: dict[str, list[Path]] = defaultdict(list)
    for path in json_files:
        by_category[category_for(workflows_root, path)].append(path)

    for category in sorted(by_category):
        print(f"[{category}]")
        for path in by_category[category]:
            rel = path.relative_to(repo_root)
            print(f"  {rel.as_posix()}")
        print()

    print(f"RESULT: Found {len(json_files)} workflow JSON file(s) in {len(by_category)} categor(ies).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
