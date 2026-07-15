#!/usr/bin/env python3
"""Show one AI Studio project workspace."""

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

from core.runtime.project_workspace import ProjectWorkspace, validate_manifest
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Show an AI Studio project.")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    workspace = ProjectWorkspace(bundle.path("drive_root"))
    manifest = workspace.load_project(args.slug)
    if manifest is None:
        print(f"ERROR: Unknown project slug: {args.slug}", file=sys.stderr)
        return 1

    data = manifest.to_dict()
    errors = validate_manifest(data)
    payload = {"manifest": data, "validation_errors": errors}

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("AI Studio — Project")
    print("=" * 40)
    print(json.dumps(data, indent=2))
    if errors:
        print("\nValidation errors:")
        for error in errors:
            print(f"  - {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
