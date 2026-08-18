#!/usr/bin/env python3
"""Create a NEW img2img variation preparation from a generation (Package 4.11).

Does not mutate the source generation snapshot or the original preparation.
Does not queue or run ComfyUI — creates a variation preparation only.
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

from core.runtime.generation_derivation import prepare_variation_from_generation
from core.runtime.generation_identity import InvalidGenerationIdError, normalize_generation_id
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_manifest import load_workflow_manifest


def _parse_param(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"Invalid --param (expected key=value): {raw}")
    key, value = raw.split("=", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"Invalid --param key: {raw}")
    return key, value


def _load_param_overrides(args: argparse.Namespace) -> dict:
    params: dict = {}
    for raw in args.param:
        key, value = _parse_param(raw)
        params[key] = value
    if args.params_json:
        loaded = json.loads(args.params_json)
        if not isinstance(loaded, dict):
            raise ValueError("--params-json must be a JSON object")
        params.update(loaded)
    if args.params_file:
        loaded = json.loads(Path(args.params_file).read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("--params-file must contain a JSON object")
        params.update(loaded)
    return params


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create an img2img variation preparation from a verified generation image. "
            "Does not execute ComfyUI."
        )
    )
    parser.add_argument(
        "--generation-id",
        required=True,
        help="Generation ID as gen_<UUID> or bare UUID.",
    )
    parser.add_argument("--project", default=None, help="Explicit project slug or id override.")
    parser.add_argument("--global", dest="use_global", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--param", action="append", default=[], help="Parameter key=value (repeatable).")
    parser.add_argument("--params-json", default="", help="JSON object of workflow parameters.")
    parser.add_argument("--params-file", type=Path, default=None, help="JSON file of workflow parameters.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.use_global and args.project:
        print("ERROR: Conflicting project flags with --global.", file=sys.stderr)
        return 1

    try:
        generation_id = normalize_generation_id(args.generation_id)
    except InvalidGenerationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        overrides = _load_param_overrides(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    drive_root = bundle.path("drive_root")

    try:
        manifest = load_workflow_manifest(repo_root, "base/img2img")
        comfy_object_info = {str(node): {} for node in (manifest.get("required_nodes") or [])}
        model_files_present = {
            str(name): True for name in (manifest.get("required_model_files") or [])
        }
    except (OSError, ValueError, json.JSONDecodeError):
        comfy_object_info = None
        model_files_present = None

    result = prepare_variation_from_generation(
        repo_root,
        generation_id=generation_id,
        runtime_prepared_root=bundle.path("runtime_root") / "prepared_workflows",
        drive_prepared_root=bundle.path("drive_workflows") / "prepared",
        comfyui_input_dir=bundle.path("comfyui_runtime") / "input",
        drive_root=drive_root,
        use_global=bool(args.use_global),
        project_ref=args.project,
        parameter_overrides=overrides,
        dry_run=args.dry_run,
        comfy_object_info=comfy_object_info,
        model_files_present=model_files_present,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.ok else 1

    print("AI Studio — Prepare Variation From Generation")
    print("=" * 40)
    print(f"Source generation: {result.generation_id or generation_id}")
    if result.ok:
        print()
        print("Variation preparation created:")
        print(result.preparation_id)
        print()
        print(f"Source generation:  {result.generation_id}")
        lineage = result.lineage or {}
        if lineage.get("derivation_source_prompt_id"):
            print(f"Source prompt:      {lineage.get('derivation_source_prompt_id')}")
        if lineage.get("derivation_source_preparation_id"):
            print(f"Source preparation: {lineage.get('derivation_source_preparation_id')}")
        print(f"Workflow:           {result.workflow_identifier}")
        print(f"Derivation type:    {result.derivation_type}")
        print(f"Seed:               {result.parameters.get('seed')}")
        print(f"Seed mode:          {result.parameters.get('seed_mode')}")
        print(f"Control after gen:  {result.parameters.get('control_after_generate')}")
        print(f"Denoise:            {result.parameters.get('denoise')}")
        print(f"Save prefix:        {result.parameters.get('save_prefix')}")
        if lineage.get("derivation_source_archived_path"):
            print(f"Archived source:    {lineage.get('derivation_source_archived_path')}")
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
