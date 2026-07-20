#!/usr/bin/env python3
"""Archive an AI Studio project."""

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
    parser = argparse.ArgumentParser(description="Archive an AI Studio project.")
    parser.add_argument("--project", required=True, help="Project slug or project_id.")
    parser.add_argument("--yes", action="store_true", help="Skip interactive confirmation.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    workspace = ProjectWorkspace(bundle.path("drive_root"))
    try:
        manifest = workspace.resolve_project(args.project)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    active = workspace.get_active_project()
    if active and active.slug == manifest.slug and not args.yes:
        print(f"Archiving {manifest.slug} will deactivate it.")
        print("Existing assets will remain in Drive.")
        print("Future outputs will not be mirrored to this project.")
        if not sys.stdin.isatty():
            print(
                "ERROR: Noninteractive archive of the active project requires --yes.",
                file=sys.stderr,
            )
            return 1
        try:
            confirm = input("Type YES to continue: ").strip()
        except EOFError:
            print(
                "ERROR: Confirmation input unavailable. Re-run with --yes.",
                file=sys.stderr,
            )
            return 1
        if confirm != "YES":
            print("Archive cancelled.")
            return 1

    try:
        archived = workspace.archive_project(args.project)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(archived.to_dict(), indent=2))
        return 0
    print(f"Archived project: {archived.slug}")
    if active and active.slug == manifest.slug:
        print("Active project cleared. Future outputs will be saved globally only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
