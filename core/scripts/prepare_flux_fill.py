#!/usr/bin/env python3
"""Prepare a temporary FLUX.1 Fill [dev] benchmark workflow."""

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

from core.runtime.modern_editing_preparation import prepare_modern_editing_workflow, resolve_runtime_dirs
from core.runtime.registry_loader import RegistryLoader, find_repo_root

FLUX_REQUIRED = [
    "flux_fill_dev_diffusion",
    "flux_clip_l",
    "flux_t5xxl",
    "flux_ae_vae",
]
FLUX_REFERENCE = "workflows/reference/flux_fill/workflow.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare temporary FLUX Fill [dev] benchmark workflow. "
            "FLUX weights are non-commercial; gated manual download only."
        )
    )
    parser.add_argument("--input", type=Path, required=True, help="RGB or RGBA source image.")
    parser.add_argument("--mask", type=Path, default=None, help="Optional separate mask if not using alpha.")
    parser.add_argument("--positive-prompt", required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--runtime-dir", type=Path, default=None)
    parser.add_argument("--comfyui-input-dir", type=Path, default=None)
    parser.add_argument("--allow-missing-models", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    runtime_dir, comfyui_input_dir = resolve_runtime_dirs(
        repo_root,
        runtime_dir=args.runtime_dir,
        comfyui_input_dir=args.comfyui_input_dir,
        bundle=bundle,
    )
    print("Resolved paths:")
    print(f"  ComfyUI input: {comfyui_input_dir}")
    print(f"  Prepared workflows: {runtime_dir}")
    print("License: FLUX.1-dev Non-Commercial — not a commercial production default.")

    result = prepare_modern_editing_workflow(
        repo_root,
        candidate="flux_fill_benchmark",
        reference_relpath=FLUX_REFERENCE,
        required_models=FLUX_REQUIRED,
        input_path=args.input.resolve(),
        runtime_dir=runtime_dir,
        comfyui_input_dir=comfyui_input_dir,
        positive_prompt=args.positive_prompt,
        mask_path=args.mask.resolve() if args.mask else None,
        dry_run=args.dry_run,
        require_models=not args.allow_missing_models,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("\nAI Studio — FLUX Fill Preparation")
        print("=" * 40)
        print(f"Candidate: {result.candidate}")
        print(f"Reference: {result.reference_path}")
        print(f"Input: {result.input_image}")
        if result.mask_image:
            print(f"Mask: {result.mask_image}")
        print(f"Prompt: {result.positive_prompt}")
        print(f"Staged input: {result.staged_input_filename}")
        print(f"Prepared: {result.prepared_path}")
        for message in result.messages:
            print(f"- {message}")
        for error in result.errors:
            print(f"ERROR: {error}", file=sys.stderr)

    if not result.ok:
        print("\nRESULT: FAIL — FLUX Fill preparation reported errors.", file=sys.stderr)
        return 1
    print("\nRESULT: OK — FLUX Fill preparation complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
