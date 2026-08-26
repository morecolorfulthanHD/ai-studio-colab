#!/usr/bin/env python3
"""Show one character identity record (Package 4.12)."""

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

from core.runtime.character_identity import (
    InvalidCharacterIdError,
    character_dir,
    load_character,
    normalize_character_id,
    resolve_primary_face_path,
    verify_character_face,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Show character identity details.")
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        cid = normalize_character_id(args.character_id)
    except InvalidCharacterIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    drive_root = RegistryLoader(repo_root).load_all().path("drive_root")
    record = load_character(drive_root, cid)
    if record is None:
        print(f"ERROR: Character not found: {cid}", file=sys.stderr)
        return 1
    ok, err = verify_character_face(drive_root, record)
    face = resolve_primary_face_path(drive_root, record)
    payload = {
        **record.to_dict(),
        "character_dir": str(character_dir(drive_root, cid)),
        "primary_face_path": str(face) if face else None,
        "face_ok": ok,
        "face_error": err,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — Character Info")
        print("=" * 40)
        print(f"Character ID:     {record.character_id}")
        print(f"Display name:     {record.display_name}")
        print(f"Directory:        {payload['character_dir']}")
        print(f"Primary face:     {payload['primary_face_path']}")
        print(f"Face SHA256:      {record.primary_face_ref.get('sha256')}")
        print(f"Face verified:    {'yes' if ok else 'no'}")
        if err:
            print(err, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
