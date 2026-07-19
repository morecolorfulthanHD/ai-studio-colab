#!/usr/bin/env python3
"""Create a new AI Studio project workspace."""

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

from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an AI Studio project workspace.")
    parser.add_argument("--name", default=None, help="Human-readable project name.")
    parser.add_argument("--slug", default=None, help="Optional slug (auto-generated from name when omitted).")
    parser.add_argument("--description", default="")
    parser.add_argument("--tag", action="append", default=[], dest="tags")
    parser.add_argument("--default-workflow", default="")
    parser.add_argument("--set-active", action="store_true", help="Activate the new project.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.name and not args.slug:
        print("ERROR: Provide --name and/or --slug.", file=sys.stderr)
        return 1
    display_name = args.name or args.slug

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    workspace = ProjectWorkspace(bundle.path("drive_root"))

    try:
        manifest = workspace.create_project(
            display_name=display_name,
            slug=args.slug,
            description=args.description,
            default_workflow=args.default_workflow,
            tags=args.tags,
            set_active=args.set_active,
        )
    except (FileExistsError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(manifest.to_dict(), indent=2))
    else:
        print("AI Studio — Project Created")
        print("=" * 40)
        print(f"name:   {manifest.display_name}")
        print(f"slug:   {manifest.slug}")
        print(f"id:     {manifest.project_id}")
        print(f"status: {manifest.status}")
        print(f"outputs:{manifest.outputs_dir}")
        if args.set_active:
            print("Active project set to this project.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
