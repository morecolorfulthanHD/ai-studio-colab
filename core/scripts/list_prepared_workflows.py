#!/usr/bin/env python3
"""List prepared workflow library preparations."""

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

from core.runtime.prepared_workflow_index import preparations_log_path, read_preparation_records
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="List prepared workflow library preparations.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--project", default="", help="Filter by project slug substring.")
    parser.add_argument("--workflow", default="", help="Filter by workflow identifier.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    log_path = preparations_log_path(bundle.path("drive_root"))
    rows = read_preparation_records(log_path)

    filtered: list[dict] = []
    for row in reversed(rows):
        if args.workflow and str(row.get("workflow_identifier") or "") != args.workflow:
            continue
        if args.project and args.project not in str(row.get("project_prepared_dir") or ""):
            continue
        filtered.append(row)
        if len(filtered) >= args.limit:
            break

    if args.json:
        print(json.dumps(filtered, indent=2))
        return 0

    print("AI Studio — Prepared Workflows")
    print("=" * 40)
    if not filtered:
        print("No prepared workflows found.")
        return 0
    for row in filtered:
        if args.summary:
            print(
                f"{row.get('preparation_id', ''):40} "
                f"{row.get('workflow_identifier', ''):20} "
                f"{row.get('readiness_status', '')}"
            )
        else:
            print(f"{row.get('preparation_id')} — {row.get('workflow_identifier')}")
            print(f"  drive: {row.get('drive_prepared_dir', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
