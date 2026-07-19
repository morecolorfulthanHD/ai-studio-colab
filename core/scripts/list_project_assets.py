#!/usr/bin/env python3
"""List project-associated generation assets from the evidence ledger."""

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

from core.runtime.generation_history import list_project_assets
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="List AI Studio project generation assets.")
    parser.add_argument("--project", required=True, help="Project slug or project_id.")
    parser.add_argument("--capability", default="")
    parser.add_argument("--prompt-contains", default="")
    parser.add_argument("--limit", type=int, default=50)
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

    evidence = bundle.path("drive_logs") / "generation_evidence.jsonl"
    assets = list_project_assets(
        evidence,
        project=manifest.slug,
        project_id=manifest.project_id,
        capability=args.capability,
        prompt_contains=args.prompt_contains,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps({"project": manifest.to_dict(), "assets": assets}, indent=2))
        return 0
    print(f"AI Studio — Project Assets ({manifest.slug})")
    print("=" * 40)
    if not assets:
        print("No verified project assets found.")
        return 0
    for asset in assets:
        print(
            f"{asset.get('created_timestamp')} | {asset.get('capability')} | "
            f"{asset.get('drive_filename')} | {asset.get('prompt_excerpt')}"
        )
        print(f"  canonical={asset.get('canonical_global_path')}")
        print(f"  mirror={asset.get('project_mirror_path')}")
        print(
            f"  sha_verified={asset.get('sha256_verified')} provenance={asset.get('provenance')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
