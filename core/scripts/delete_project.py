#!/usr/bin/env python3
"""Delete an AI Studio project folder with exact-slug confirmation."""

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
    parser = argparse.ArgumentParser(
        description="Delete a managed AI Studio project folder. Canonical global outputs are preserved."
    )
    parser.add_argument("--project", required=True, help="Project slug or project_id.")
    parser.add_argument(
        "--confirm-slug",
        default=None,
        help="Exact project slug confirmation for noninteractive deletion.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Read-only preview; no deletions.")
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

    confirm = args.confirm_slug
    if not args.dry_run and not confirm:
        print(f"Delete project: {manifest.slug}")
        print(f"This permanently removes the managed project folder:")
        print(f"  {workspace.project_dir(manifest.slug)}")
        print("This includes project metadata, outputs, inputs, masks, references, and workflows.")
        print("The canonical files in AI_Studio/outputs/ will NOT be deleted.")
        confirm = input("Type the exact project slug to confirm: ").strip()

    try:
        result = workspace.delete_project(
            args.project,
            confirm_slug=confirm or "",
            dry_run=args.dry_run,
        )
    except (PermissionError, ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    if args.dry_run:
        print("Delete dry-run (read-only)")
        print(f"Would delete: {result['path']}")
        print(f"Files: {result['files']} | Directories: {result['directories']}")
        print("Global outputs and evidence would be preserved.")
        return 0
    print(f"Deleted project: {result['slug']}")
    print(f"Removed {result['files']} files / {result['directories']} directories.")
    print("Canonical global outputs and generation evidence were preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
