#!/usr/bin/env python3
"""Create a NEW preparation that reproduces an executed generation (Package 4.10).

Does not mutate the source generation snapshot or the original preparation.
Does not queue or run ComfyUI — creates a fixed reproduction preparation only.
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

from core.runtime.generation_identity import InvalidGenerationIdError, normalize_generation_id
from core.runtime.generation_reproduction import prepare_from_generation
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_manifest import load_workflow_manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a fixed reproduction preparation from a completed generation. "
            "Does not execute ComfyUI."
        )
    )
    parser.add_argument(
        "--generation-id",
        required=True,
        help="Generation ID as gen_<UUID> or bare UUID.",
    )
    parser.add_argument("--project", default=None, help="Explicit project slug or id.")
    parser.add_argument("--global", dest="use_global", action="store_true")
    parser.add_argument("--use-active-project", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.use_global and (args.project or args.use_active_project):
        print("ERROR: Conflicting project flags with --global.", file=sys.stderr)
        return 1

    try:
        generation_id = normalize_generation_id(args.generation_id)
    except InvalidGenerationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    drive_root = bundle.path("drive_root")

    project_ref = args.project
    use_global = bool(args.use_global)
    if args.use_active_project and not project_ref and not use_global:
        project_ref = None

    try:
        manifest = load_workflow_manifest(repo_root, "base/txt2img")
        comfy_object_info = {str(node): {} for node in (manifest.get("required_nodes") or [])}
    except (OSError, ValueError, json.JSONDecodeError):
        comfy_object_info = None

    result = prepare_from_generation(
        repo_root,
        generation_id=generation_id,
        runtime_prepared_root=bundle.path("runtime_root") / "prepared_workflows",
        drive_prepared_root=bundle.path("drive_workflows") / "prepared",
        comfyui_input_dir=bundle.path("comfyui_runtime") / "input",
        drive_root=drive_root,
        use_global=use_global,
        project_ref=project_ref,
        dry_run=args.dry_run,
        allowed_input_roots=[bundle.path("drive_inputs"), repo_root / "inputs"],
        comfy_object_info=comfy_object_info,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.ok else 1

    print("AI Studio — Prepare From Generation")
    print("=" * 40)
    print(f"Source generation: {result.generation_id or generation_id}")
    if result.ok:
        print()
        print("Reproduction preparation created:")
        print(result.preparation_id)
        print()
        print(f"Source generation:  {result.generation_id}")
        lineage = result.lineage or {}
        if lineage.get("reproduction_source_prompt_id"):
            print(f"Source prompt:      {lineage.get('reproduction_source_prompt_id')}")
        if lineage.get("reproduction_source_preparation_id"):
            print(f"Source preparation: {lineage.get('reproduction_source_preparation_id')}")
        print(f"Workflow:           {result.workflow_identifier}")
        print(f"Execution seed:     {result.parameters.get('seed')}")
        print(f"Seed mode:          {result.parameters.get('seed_mode')}")
        print(f"Control after gen:  {result.parameters.get('control_after_generate')}")
        print(f"Batch size:         {result.parameters.get('batch_size')}")
        if result.reproduction_scope:
            scope_label = (
                "original batch execution"
                if result.reproduction_scope == "source_batch_execution"
                else "single generation"
            )
            print(f"Reproduction scope: {scope_label}")
        if result.source_batch_size is not None and result.source_batch_size > 1:
            print()
            print("Source generation is part of a batch execution:")
            print(f"  source batch size: {result.source_batch_size}")
            print("Reproduction scope:")
            print("  original batch execution")
            print(
                f"This preparation will generate {result.source_batch_size} "
                "images when manually Run."
            )
        print(f"Save prefix:        {result.parameters.get('save_prefix')}")
        if result.preparation and result.preparation.drive_prepared_dir:
            print(f"Global Drive path:  {result.preparation.drive_prepared_dir}")
        if result.preparation and result.preparation.project_prepared_dir:
            print(f"Project path:       {result.preparation.project_prepared_dir}")
        print()
        print("Next:")
        print("  Open prepared workflow to inspect and manually Run.")
        print("  This operation does not queue or execute ComfyUI.")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    for message in result.messages:
        if message in result.warnings:
            continue
        print(f"Note: {message}")
    for error in result.errors:
        print(error, file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
