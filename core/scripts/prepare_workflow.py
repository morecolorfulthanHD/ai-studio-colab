#!/usr/bin/env python3
"""Prepare ephemeral runtime workflow copies with selected inputs."""

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

from core.runtime.registry_loader import find_repo_root
from core.runtime.workflow_preparation import prepare_workflow


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare runtime workflow JSON with selected inputs.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--workflow", required=True, choices=["img2img", "inpainting", "outpainting"])
    parser.add_argument("--input", required=True, type=Path, help="Persistent source image path.")
    parser.add_argument("--mask", type=Path, default=None, help="Persistent mask image path (inpainting).")
    parser.add_argument("--left", type=int, default=0)
    parser.add_argument("--right", type=int, default=0)
    parser.add_argument("--top", type=int, default=0)
    parser.add_argument("--bottom", type=int, default=0)
    parser.add_argument("--runtime-dir", type=Path, default=None)
    parser.add_argument("--comfyui-input-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--inspect", action="store_true", help="Print inpainting diagnostics after preparation.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
        from core.runtime.registry_loader import RegistryLoader

        bundle = RegistryLoader(repo_root).load_all()
        runtime_dir = args.runtime_dir or bundle.path("runtime_workflows")
        comfyui_input_dir = args.comfyui_input_dir or (bundle.path("comfyui_runtime") / "input")
        expansion = {
            "left": args.left,
            "right": args.right,
            "top": args.top,
            "bottom": args.bottom,
        }
        result = prepare_workflow(
            repo_root,
            runtime_dir,
            comfyui_input_dir=comfyui_input_dir,
            workflow=args.workflow,
            input_path=args.input.resolve(),
            mask_path=args.mask.resolve() if args.mask else None,
            expansion=expansion if args.workflow == "outpainting" else None,
            dry_run=args.dry_run,
            diagnostics=args.inspect and args.workflow == "inpainting",
        )
    except (FileNotFoundError, KeyError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — Workflow Preparation")
        print("=" * 40)
        print(f"Workflow:   {result.workflow} ({result.workflow_id})")
        print(f"Canonical:  {result.canonical_path}")
        print(f"ComfyUI input dir: {result.comfyui_input_dir}")
        print(f"Persistent source: {result.input_image}")
        if result.mask_image:
            print(f"Persistent mask:   {result.mask_image}")
        if result.staged_input_path:
            print(f"Staged source:     {result.staged_input_path}")
        if result.staged_mask_path:
            print(f"Staged mask:       {result.staged_mask_path}")
        if result.prepared_path:
            print(f"Prepared workflow: {result.prepared_path}")
        if result.expansion:
            print(f"Expansion:         {result.expansion}")
        for message in result.messages:
            print(f"Note: {message}")
        for error in result.errors:
            print(f"Error: {error}", file=sys.stderr)
        if args.inspect and result.diagnostic_details:
            print("\nInspection:")
            from core.runtime.inpainting_inspection import format_inpainting_inspection

            print(format_inpainting_inspection(result.diagnostic_details))

    if not result.ok:
        print("\nRESULT: FAIL — workflow preparation failed.", file=sys.stderr)
        return 1

    print("\nRESULT: OK — workflow preparation complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
