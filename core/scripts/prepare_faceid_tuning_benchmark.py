#!/usr/bin/env python3
"""Prepare a FaceID conditioning-sweep tuning benchmark (Package 4.12.2).

Benchmark-only. First phase: S2/S3 × variants A–D.
Does not overwrite frozen baseline prep IDs. Does not auto-run. Does not promote.
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

from core.runtime.identity_benchmark_tuning import (
    FACEID_TUNING_VARIANTS,
    FIRST_PHASE_SCENARIOS,
    prepare_faceid_tuning_benchmark,
    resolve_tuning_variant_id,
)
from core.runtime.identity_benchmark import normalize_scenario_id
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _register_open_instructions(repo_root: Path, preparation_id: str) -> int:
    import subprocess

    script = repo_root / "core" / "scripts" / "open_prepared_workflow.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--preparation-id", preparation_id],
        cwd=str(repo_root),
    )
    return int(proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare Package 4.12.2 FaceID conditioning sweep (S2/S3 only). "
            "Requires --allow-benchmark. Does not execute ComfyUI."
        )
    )
    parser.add_argument(
        "--scenario",
        required=True,
        help="S2 or S3 (or full IDs). S1/S4 refused in first-phase sweep.",
    )
    parser.add_argument(
        "--variant",
        required=True,
        help="A–D or variant_id (e.g. faceid_v2_1p5_full).",
    )
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--allow-benchmark", action="store_true")
    parser.add_argument("--allow-missing-models", action="store_true")
    parser.add_argument("--allow-missing-nodes", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-open-registration", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    canonical = normalize_scenario_id(args.scenario)
    if canonical is None:
        print(f"ERROR: Unknown scenario: {args.scenario}", file=sys.stderr)
        return 1
    if canonical not in FIRST_PHASE_SCENARIOS:
        print(
            f"ERROR: First-phase sweep only allows S2/S3; refused {canonical}.",
            file=sys.stderr,
        )
        return 1
    if resolve_tuning_variant_id(args.variant) is None:
        print(
            f"ERROR: Unknown variant: {args.variant}. "
            f"Use A–D or: {', '.join(FACEID_TUNING_VARIANTS)}",
            file=sys.stderr,
        )
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    comfy_runtime = bundle.path("comfyui_runtime")
    result = prepare_faceid_tuning_benchmark(
        repo_root=repo_root,
        drive_root=bundle.path("drive_root"),
        runtime_prepared_root=bundle.path("runtime_root") / "prepared_workflows",
        drive_prepared_root=bundle.path("drive_workflows") / "prepared",
        comfyui_input_dir=comfy_runtime / "input",
        character_id=args.character_id,
        scenario=canonical,
        variant_id=args.variant,
        bundle_models=list(bundle.models),
        bundle_nodes=list(bundle.nodes),
        comfyui_custom_nodes=comfy_runtime / "custom_nodes",
        allow_benchmark=args.allow_benchmark,
        require_models=not args.allow_missing_models,
        require_nodes=not args.allow_missing_nodes,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("AI Studio — FaceID Tuning Benchmark Preparation (4.12.2)")
        print("=" * 50)
        print(f"Candidate:        ipadapter_faceid_sd15_benchmark")
        print(f"Scenario:         {result.scenario}")
        print(f"Tuning variant:   {result.tuning_variant_id}")
        print(f"Parameters:       {json.dumps(result.tuning_parameters)}")
        print(f"Character:        {result.character_id}")
        print(f"Baseline prep:    {result.baseline_preparation_id}")
        print(f"Baseline seed:    {result.baseline_seed}")
        print(f"Prompt:           {result.positive_prompt}")
        print(f"New prep ID:      {result.preparation_id or '(none)'}")
        print(f"Graph hash:       {result.prepared_workflow_hash or '(none)'}")
        print(f"Runtime path:     {result.prepared_dir or '(none)'}")
        print(f"Drive path:       {result.drive_prepared_dir or '(none)'}")
        print("WARNING: Benchmark-only. No auto-run. No quality claim. Promotion=pending.")
        print("WARNING: Operational execution pass ≠ visual scenario pass.")
        for message in result.messages:
            print(f"- {message}")
        for warning in result.warnings:
            print(f"WARN: {warning}")
        for error in result.errors:
            print(error, file=sys.stderr)

    if not result.ok:
        return 1
    if args.dry_run or args.skip_open_registration or not result.preparation_id:
        return 0

    print("\n--- ComfyUI registration (does not auto-run) ---")
    open_rc = _register_open_instructions(repo_root, result.preparation_id)
    if open_rc == 0:
        print("\nPreparation registered. Hard-reload ComfyUI and open the workflow.")
        print("Run ONE operator Run at a time; inspect before the next variant.")
    elif open_rc == 2:
        print(
            "\nPreparation indexed; ComfyUI registration partial. "
            f"Retry: python core/scripts/open_prepared_workflow.py --preparation-id {result.preparation_id}",
            file=sys.stderr,
        )
        return 2
    return open_rc


if __name__ == "__main__":
    raise SystemExit(main())
