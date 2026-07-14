#!/usr/bin/env python3
"""Prepare a temporary official-reference inpainting workflow with an RGBA alpha mask."""

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

from core.runtime.inpainting_reference_preparation import (
    prepare_inpainting_reference,
    resolve_reference_runtime_paths,
)
from core.runtime.inpainting_workflow_compare import REFERENCE_PROVENANCE_PATH
from core.runtime.mask_diagnostics import analyze_mask, format_mask_summary
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a temporary official-reference inpainting workflow from one RGBA PNG "
            "with an embedded alpha mask. Uses configured Colab runtime paths by default. "
            "Does not modify the production canonical workflow or the extracted reference JSON."
        )
    )
    parser.add_argument("--input", type=Path, required=True, help="RGBA PNG with embedded alpha mask.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=None,
        help="Directory for prepared JSON (default: configs runtime_workflows path).",
    )
    parser.add_argument(
        "--comfyui-input-dir",
        type=Path,
        default=None,
        help="ComfyUI input directory (default: <comfyui_runtime>/input from configs).",
    )
    parser.add_argument(
        "--match-canonical-sampler",
        action="store_true",
        help="Copy seed/steps/CFG/sampler/scheduler/denoise from the canonical workflow.",
    )
    parser.add_argument(
        "--match-canonical-settings",
        action="store_true",
        help=(
            "Copy sampler settings and prompts from the canonical workflow "
            "(prompt flags still override when provided)."
        ),
    )
    parser.add_argument("--positive-prompt", type=str, default=None)
    parser.add_argument("--negative-prompt", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
        bundle = RegistryLoader(repo_root).load_all()
        resolved = resolve_reference_runtime_paths(
            repo_root,
            runtime_dir=args.runtime_dir,
            comfyui_input_dir=args.comfyui_input_dir,
            bundle=bundle,
        )
    except (FileNotFoundError, KeyError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Resolved live runtime paths:")
    print(f"  ComfyUI input:       {resolved.comfyui_input_dir}")
    print(f"    source:            {resolved.comfyui_input_dir_source}")
    print(f"  Prepared workflows:  {resolved.runtime_dir}")
    print(f"    source:            {resolved.runtime_dir_source}")

    result = prepare_inpainting_reference(
        repo_root,
        resolved.runtime_dir,
        input_path=args.input.resolve(),
        comfyui_input_dir=resolved.comfyui_input_dir,
        dry_run=args.dry_run,
        match_canonical_sampler=args.match_canonical_sampler,
        match_canonical_settings=args.match_canonical_settings,
        positive_prompt=args.positive_prompt,
        negative_prompt=args.negative_prompt,
        resolved_paths=resolved,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("\nAI Studio — Official Reference Inpainting Preparation")
        print("=" * 40)
        print(f"Reference: {result.reference_path}")
        print(f"Input:     {result.input_image}")
        print(f"ComfyUI input dir: {result.comfyui_input_dir}")
        print(f"Prepared workflow dir: {result.runtime_dir}")
        print(f"Staged:    {result.staged_input_filename or '(none)'}")
        print(f"Prepared:  {result.prepared_path or '(none)'}")
        print(f"Dry-run:   {result.dry_run}")
        print(f"Checkpoint: {result.checkpoint or '(unset)'}")
        print(f"Positive prompt: {result.positive_prompt!r}")
        print(f"Negative prompt: {result.negative_prompt!r}")
        if result.sampler_settings:
            print("Sampler settings:")
            for key, value in result.sampler_settings.items():
                print(f"  {key}: {value!r}")
        if result.grow_mask_by_note:
            print(f"grow_mask_by: {result.grow_mask_by!r} — {result.grow_mask_by_note}")
        if result.matched_canonical_settings:
            print("Alignment: canonical settings (sampler + prompts where not overridden)")
        elif result.matched_canonical_sampler:
            print("Alignment: canonical sampler only")
        if Path(result.input_image).is_file():
            print("\nEmbedded alpha (ComfyUI MASK semantics):")
            print(format_mask_summary(analyze_mask(Path(result.input_image), channel="alpha")))
        for message in result.messages:
            print(f"- {message}")
        for error in result.errors:
            print(f"ERROR: {error}", file=sys.stderr)

    provenance = repo_root / REFERENCE_PROVENANCE_PATH
    if not provenance.is_file():
        print("WARNING: reference provenance.json is missing.", file=sys.stderr)

    if not result.ok:
        print("\nRESULT: FAIL — reference preparation reported errors.", file=sys.stderr)
        return 1

    print("\nRESULT: OK — official reference preparation complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
