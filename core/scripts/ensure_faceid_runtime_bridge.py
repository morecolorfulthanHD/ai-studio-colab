#!/usr/bin/env python3
"""Ensure IPAdapter-visible FaceID assets bridge from Drive canonical storage.

Pinned IPAdapter resolves CLIP Vision via ``folder_paths.get_filename_list("clip_vision")``
(not extra_model_paths). FaceID Plus v2 also requires discovery-compatible ipadapter/lora
basenames. Full Launch must recreate this bridge after Full Reset removes runtime staging.
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

from core.runtime.faceid_model_bridge import (
    default_canonical_clip_vision_dir,
    default_canonical_ipadapter_dir,
    default_canonical_lora_dir,
    ensure_faceid_runtime_bridge,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bridge Drive-canonical FaceID assets into ComfyUI/models/{clip_vision,ipadapter,loras} "
            "for pinned IPAdapter discovery. Prefer symlink; never download; never mutate Drive."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--comfyui-runtime", type=Path, default=None)
    parser.add_argument("--canonical-clip-vision-dir", type=Path, default=None)
    parser.add_argument("--canonical-ipadapter-dir", type=Path, default=None)
    parser.add_argument("--canonical-lora-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true", help="Apply bridge (default is dry-run).")
    parser.add_argument("--dry-run", action="store_true", help="Plan only (default).")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    comfyui_runtime = Path(args.comfyui_runtime or bundle.path("comfyui_runtime"))
    drive_models = bundle.path("drive_models")
    clip_dir = Path(args.canonical_clip_vision_dir or default_canonical_clip_vision_dir(drive_models))
    ipa_dir = Path(args.canonical_ipadapter_dir or default_canonical_ipadapter_dir(drive_models))
    lora_dir = Path(args.canonical_lora_dir or default_canonical_lora_dir(drive_models))

    dry_run = not args.execute or args.dry_run
    result = ensure_faceid_runtime_bridge(
        comfyui_runtime=comfyui_runtime,
        canonical_clip_vision_dir=clip_dir,
        canonical_ipadapter_dir=ipa_dir,
        canonical_lora_dir=lora_dir,
        dry_run=dry_run,
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — FaceID Runtime Bridge")
        print("=" * 40)
        print(f"Mode: {'dry-run' if dry_run else 'execute'}")
        print(f"CLIP canonical:     {result.canonical_clip_vision_dir}")
        print(f"IPAdapter canonical:{result.canonical_ipadapter_dir}")
        print(f"LoRA canonical:     {result.canonical_lora_dir}")
        print(f"clip verified:      {result.clip_vision_verified}")
        print(f"ipadapter verified: {result.ipadapter_verified}")
        print(f"lora verified:      {result.lora_verified}")
        print(f"resolver verified:  {result.resolver_verified}")
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
