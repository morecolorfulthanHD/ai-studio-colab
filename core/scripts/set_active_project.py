#!/usr/bin/env python3
"""Set or clear the active AI Studio project."""

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
    parser = argparse.ArgumentParser(description="Set or clear the active AI Studio project.")
    parser.add_argument("--slug", default=None, help="Project slug to activate.")
    parser.add_argument("--clear", action="store_true", help="Clear active project.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    workspace = ProjectWorkspace(bundle.path("drive_root"))

    try:
        if args.clear:
            payload = workspace.set_active_project(None)
        elif args.slug:
            payload = workspace.set_active_project(args.slug)
        else:
            active = workspace.get_active_project()
            payload = {"active_project": active.to_dict() if active else None}
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        if args.clear:
            print("Active project cleared.")
        elif args.slug:
            print(f"Active project set to: {args.slug}")
        else:
            active_slug = payload.get("active_project", {}).get("slug") if payload.get("active_project") else None
            print(f"Active project: {active_slug or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
