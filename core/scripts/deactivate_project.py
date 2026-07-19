#!/usr/bin/env python3
"""Deactivate the active AI Studio project (global-only mode)."""

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
    parser = argparse.ArgumentParser(description="Deactivate the active AI Studio project.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    workspace = ProjectWorkspace(bundle.path("drive_root"))
    before = workspace.get_active_project()
    payload = workspace.deactivate_active_project()
    payload["cleared"] = before.slug if before else None

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    if before is None:
        print("No active project; already in global mode.")
    else:
        print("Active project cleared.")
        print("Future outputs will be saved globally only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
