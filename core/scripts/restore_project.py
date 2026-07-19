#!/usr/bin/env python3
"""Restore an archived AI Studio project."""

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
    parser = argparse.ArgumentParser(description="Restore an archived AI Studio project.")
    parser.add_argument("--project", required=True, help="Project slug or project_id.")
    parser.add_argument("--set-active", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    workspace = ProjectWorkspace(bundle.path("drive_root"))
    try:
        restored = workspace.restore_project(args.project, set_active=args.set_active)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(restored.to_dict(), indent=2))
        return 0
    print(f"Restored project: {restored.slug}")
    print(f"Status: {restored.status}")
    if args.set_active:
        print("Project activated.")
    else:
        print("Project remains inactive until activated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
