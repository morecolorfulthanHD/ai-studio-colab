#!/usr/bin/env python3
"""List AI Studio project workspaces."""

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

from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="List AI Studio projects.")
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    workspace = ProjectWorkspace(bundle.path("drive_root"))
    active = workspace.get_active_project()
    projects = workspace.list_projects(include_archived=args.include_archived)
    archived_count = len(workspace.list_projects(include_archived=True)) - len(
        workspace.list_projects(include_archived=False)
    )

    payload = {
        "mode": workspace.current_mode(),
        "active_project": active.to_dict() if active else None,
        "projects": [project.to_dict() for project in projects],
        "archived_projects": archived_count,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("AI Studio — Projects")
    print("=" * 40)
    print(f"Current mode: {workspace.current_mode()}")
    if args.summary:
        print(f"Projects shown: {len(projects)} | Archived: {archived_count}")
        return 0
    if not projects:
        print("No projects found.")
        if archived_count:
            print(f"Archived projects: {archived_count}")
            print('Use "Restore archived project" to view or restore them.')
        return 0
    for project in projects:
        marker = "*" if active and active.slug == project.slug else " "
        print(f"{marker} {project.slug}")
        print(f"  Name: {project.display_name}")
        print(f"  Status: {project.status}")
        print(f"  Generations: {project.generation_count}")
        print(f"  Updated: {project.updated_at or project.created_at}")
    if not args.include_archived:
        print(f"Archived projects: {archived_count}")
        if archived_count:
            print('Use "Restore archived project" to view or restore them.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
