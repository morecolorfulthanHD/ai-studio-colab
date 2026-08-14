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
from core.runtime.seed_mode import resolve_seed_mode


def _project_label(row: dict) -> str:
    slug = str(row.get("project_slug") or "").strip()
    if slug:
        return slug
    project_dir = str(row.get("project_prepared_dir") or row.get("prepared_project_path") or "").strip()
    if project_dir:
        parts = Path(project_dir).parts
        if "projects" in parts:
            idx = parts.index("projects")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        return project_dir
    return "Global"


def _summary_value(row: dict, key: str):
    summary = row.get("parameter_summary") if isinstance(row.get("parameter_summary"), dict) else {}
    return summary.get(key)


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
        prep_id = str(row.get("preparation_id") or "")
        workflow_id = str(row.get("workflow_identifier") or "")
        project = _project_label(row)
        readiness = str(row.get("readiness_status") or "")
        drive_path = str(row.get("drive_prepared_dir") or row.get("prepared_drive_path") or "")
        project_path = str(row.get("project_prepared_dir") or row.get("prepared_project_path") or "")
        seed = _summary_value(row, "seed")
        seed_mode = resolve_seed_mode(index_record=row)
        created = str(row.get("created_timestamp") or row.get("created") or "").strip()
        if args.summary:
            print(
                f"{prep_id}  {workflow_id}  project={project}  "
                f"readiness={readiness}  seed_mode={seed_mode}"
            )
        else:
            print(f"{prep_id} — {workflow_id}")
            kind = str(row.get("preparation_kind") or row.get("kind") or "ordinary")
            if kind == "generation_reproduction":
                print("  kind: reproduction")
                source = str(row.get("source_generation_id") or "").strip()
                if source:
                    print(f"  source: {source}")
            print(f"  Project:      {project}")
            print(f"  Readiness:    {readiness}")
            print(f"  Created:      {created or '(unavailable)'}")
            if seed not in (None, ""):
                print(f"  seed: {seed}")
            print(f"  seed_mode: {seed_mode}")
            print(f"  Global path:  {drive_path or '(none)'}")
            if project_path:
                print(f"  Project path: {project_path}")
            else:
                print("  Project path: (none)")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
