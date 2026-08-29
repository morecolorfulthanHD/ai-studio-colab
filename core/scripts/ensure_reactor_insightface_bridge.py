#!/usr/bin/env python3
"""Ensure ReActor-visible InsightFace assets bridge from Drive canonical storage.

Pinned ReActor resolves ``inswapper_128.onnx`` under
``{ComfyUI}/models/insightface/`` (not via extra_model_paths). Full Launch must
recreate this bridge after Full Reset removes runtime staging.
"""

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

from core.runtime.reactor_model_bridge import (
    default_canonical_insightface_dir,
    ensure_reactor_insightface_bridge,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bridge Drive-canonical InsightFace assets into ComfyUI/models/insightface "
            "for ReActor. Prefer symlink; never download; never mutate Drive canonical files."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--comfyui-runtime", type=Path, default=None)
    parser.add_argument("--canonical-insightface-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true", help="Apply bridge (default is dry-run).")
    parser.add_argument("--dry-run", action="store_true", help="Plan only (default).")
    parser.add_argument("--require-buffalo", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    comfyui_runtime = Path(args.comfyui_runtime or bundle.path("comfyui_runtime"))
    if args.canonical_insightface_dir:
        canonical_dir = Path(args.canonical_insightface_dir)
    else:
        canonical_dir = default_canonical_insightface_dir(bundle.path("drive_models"))

    dry_run = not args.execute or args.dry_run
    result = ensure_reactor_insightface_bridge(
        comfyui_runtime=comfyui_runtime,
        canonical_insightface_dir=canonical_dir,
        dry_run=dry_run,
        require_inswapper=True,
        require_buffalo=bool(args.require_buffalo),
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — ReActor InsightFace Runtime Bridge")
        print("=" * 40)
        print(f"Mode: {'dry-run' if dry_run else 'execute'}")
        print(f"Canonical: {result.canonical_insightface_dir}")
        print(f"Runtime:   {result.runtime_insightface_dir}")
        print(f"inswapper verified: {result.inswapper_verified}")
        print(f"buffalo verified:   {result.buffalo_verified}")
        for action in result.actions:
            print(f"  [{action.action}] {action.path}")
            if action.target:
                print(f"    -> {action.target}")
            if action.notes:
                print(f"    notes: {action.notes}")
        for msg in result.messages:
            print(msg)
        for err in result.errors:
            print(err, file=sys.stderr)
        print(f"RESULT: {'OK' if result.ok else 'FAIL'}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
