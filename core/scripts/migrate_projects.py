#!/usr/bin/env python3
"""Migrate legacy AI Studio project metadata to Package 4.6 schema."""

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
    parser = argparse.ArgumentParser(description="Migrate AI Studio project metadata safely.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing.")
    parser.add_argument("--apply", action="store_true", help="Apply non-destructive metadata updates.")
    parser.add_argument("--project", default=None, help="Optional single project slug.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run or --apply.")
    if args.dry_run and args.apply:
        parser.error("Choose only one of --dry-run or --apply.")

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    workspace = ProjectWorkspace(bundle.path("drive_root"))
    apply = bool(args.apply)
    if args.project:
        results = [workspace.migrate_project(args.project, apply=apply)]
    else:
        results = workspace.migrate_all(apply=apply)

    if args.json:
        print(json.dumps({"apply": apply, "results": results}, indent=2))
        return 0
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"AI Studio — Project Migration ({mode})")
    print("=" * 40)
    if not results:
        print("No projects found.")
        return 0
    for item in results:
        if item.get("error"):
            print(f"{item.get('slug')}: ERROR {item['error']}")
            continue
        changed = item.get("changed_fields") or []
        print(f"{item.get('slug')}: {len(changed)} field(s) {'updated' if apply else 'would update'}")
        if changed:
            print(f"  {', '.join(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
