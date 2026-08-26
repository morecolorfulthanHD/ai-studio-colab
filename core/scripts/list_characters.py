#!/usr/bin/env python3
"""List Drive-backed character identities (Package 4.12)."""

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

from core.runtime.character_identity import list_characters, verify_character_face
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="List registered character identities.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    drive_root = RegistryLoader(repo_root).load_all().path("drive_root")
    rows = list_characters(drive_root)
    payload = []
    for row in rows:
        ok, err = verify_character_face(drive_root, row)
        payload.append(
            {
                **row.to_dict(),
                "face_ok": ok,
                "face_error": err,
            }
        )
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — Characters")
        print("=" * 40)
        if not payload:
            print("(none)")
        for row in payload:
            status = "OK" if row["face_ok"] else "SHA/FACE FAIL"
            print(f"{row['character_id']}  {row['display_name']}  [{status}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
