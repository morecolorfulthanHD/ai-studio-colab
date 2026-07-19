#!/usr/bin/env python3
"""Rename an AI Studio project display name and/or slug."""

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
    parser = argparse.ArgumentParser(description="Rename an AI Studio project.")
    parser.add_argument("--project", required=True, help="Current project slug or project_id.")
    parser.add_argument("--name", default=None, help="New human-readable display name.")
    parser.add_argument("--new-slug", default=None, help="Optional new Drive folder slug.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.name is None and args.new_slug is None:
        print("ERROR: Provide --name and/or --new-slug.", file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    workspace = ProjectWorkspace(bundle.path("drive_root"))
    try:
        before = workspace.resolve_project(args.project)
        previous_slug = before.slug
        manifest = workspace.rename_project(
            args.project,
            display_name=args.name,
            new_slug=args.new_slug,
        )
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = {
        "project": manifest.to_dict(),
        "previous_slug": previous_slug,
        "note": (
            "Historical evidence rows may retain the original slug; "
            "project_id remains authoritative."
        ),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print("AI Studio — Project Renamed")
    print("=" * 40)
    print(f"id:            {manifest.project_id}")
    print(f"name:          {manifest.display_name}")
    print(f"slug:          {manifest.slug}")
    if previous_slug != manifest.slug:
        print(f"previous_slug: {previous_slug}")
        print("Folder renamed. Active pointer updated if this project was active.")
    print(payload["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
