#!/usr/bin/env python3
"""Register a platform-generic character identity (Package 4.12)."""

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

from core.runtime.character_identity import register_character
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register a Drive-backed character identity with one SHA-verified face reference."
    )
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--primary-face", type=Path, required=True)
    parser.add_argument("--project", default=None)
    parser.add_argument("--character-id", default=None, help="Optional char_<uuid>; allocated if omitted.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    drive_root = RegistryLoader(repo_root).load_all().path("drive_root")
    result = register_character(
        drive_root,
        display_name=args.display_name,
        primary_face_image=args.primary_face.resolve(),
        project_slug=args.project,
        character_id=args.character_id,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("AI Studio — Register Character")
        print("=" * 40)
        if result.character:
            print(f"Character ID:   {result.character.character_id}")
            print(f"Display name:   {result.character.display_name}")
            print(f"Directory:      {result.character_dir}")
            print(f"Face SHA256:    {result.character.primary_face_ref.get('sha256')}")
        for message in result.messages:
            print(f"- {message}")
        for error in result.errors:
            print(error, file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
