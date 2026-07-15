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

from core.runtime.project_workspace import ProjectWorkspace, slugify
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an AI Studio project workspace.")
    parser.add_argument("--name", required=True, help="Display name for the project.")
    parser.add_argument("--slug", default=None, help="Optional slug (collision-safe if omitted).")
    parser.add_argument("--description", default="")
    parser.add_argument("--default-workflow", default="")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    workspace = ProjectWorkspace(bundle.path("drive_root"))
    slug = slugify(args.slug or args.name)

    try:
        manifest = workspace.create_project(
            display_name=args.name,
            slug=slug,
            description=args.description,
            default_workflow=args.default_workflow,
        )
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(manifest.to_dict(), indent=2))
    else:
        print("AI Studio — Project Created")
        print("=" * 40)
        print(f"slug:   {manifest.slug}")
        print(f"id:     {manifest.project_id}")
        print(f"outputs:{manifest.outputs_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
