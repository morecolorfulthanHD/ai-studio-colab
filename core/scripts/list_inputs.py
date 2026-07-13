#!/usr/bin/env python3
"""List eligible Drive/runtime input images and masks (read-only)."""

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

from core.runtime.input_utils import ELIGIBLE_INPUT_SUFFIXES, list_eligible_inputs
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="List eligible input images and masks from Drive paths.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
        bundle = RegistryLoader(repo_root).load_all()
        images_dir = bundle.path("drive_inputs") / "images"
        masks_dir = bundle.path("drive_inputs") / "masks"
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    images = list_eligible_inputs(images_dir)
    masks = list_eligible_inputs(masks_dir)
    payload = {
        "images_dir": str(images_dir),
        "masks_dir": str(masks_dir),
        "supported_extensions": sorted(ELIGIBLE_INPUT_SUFFIXES),
        "images": [str(path) for path in images],
        "masks": [str(path) for path in masks],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — Input Listing")
        print("=" * 40)
        print(f"Images dir: {images_dir}")
        print(f"Masks dir:  {masks_dir}")
        print(f"Supported:  {', '.join(sorted(ELIGIBLE_INPUT_SUFFIXES))}")
        print("\nImages:")
        if images:
            for path in images:
                print(f"  {path}")
        else:
            print("  (none)")
        print("\nMasks:")
        if masks:
            for path in masks:
                print(f"  {path}")
        else:
            print("  (none)")

    print("\nRESULT: OK — input listing complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
