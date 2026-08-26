#!/usr/bin/env python3
"""Prepare an identity-method benchmark workflow (Package 4.12).

Benchmark-only. Explicit --allow-benchmark required. No auto-download.
Prepare/open alone does not quality-benchmark the method.
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

from core.runtime.identity_benchmark import LIVE_CANDIDATES, SCENARIO_IDS, prepare_identity_benchmark
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare Package 4.12 identity-method benchmark (ReActor or FaceID). "
            "Requires --allow-benchmark. Does not execute ComfyUI."
        )
    )
    parser.add_argument("--candidate", required=True, choices=list(LIVE_CANDIDATES))
    parser.add_argument("--scenario", required=True, choices=list(SCENARIO_IDS))
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--allow-benchmark", action="store_true")
    parser.add_argument("--allow-missing-models", action="store_true")
    parser.add_argument("--allow-missing-nodes", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    comfy_runtime = bundle.path("comfyui_runtime")
    result = prepare_identity_benchmark(
        repo_root,
        drive_root=bundle.path("drive_root"),
        candidate=args.candidate,
        scenario=args.scenario,
        character_id=args.character_id,
        runtime_prepared_root=bundle.path("runtime_root") / "prepared_workflows",
        comfyui_input_dir=comfy_runtime / "input",
        bundle_models=list(bundle.models),
        bundle_nodes=list(bundle.nodes),
        comfyui_custom_nodes=comfy_runtime / "custom_nodes",
        seed=args.seed,
        require_models=not args.allow_missing_models,
        require_nodes=not args.allow_missing_nodes,
        dry_run=args.dry_run,
        allow_benchmark=args.allow_benchmark,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("AI Studio — Identity Benchmark Preparation")
        print("=" * 40)
        print(f"Candidate:     {result.candidate}")
        print(f"Scenario:      {result.scenario}")
        print(f"Character:     {result.character_id}")
        print(f"Preparation:   {result.preparation_id or '(none)'}")
        print(f"Workflow:      {result.workflow_identifier}")
        print(f"Seed:          {result.seed}")
        print(f"Prompt:        {result.positive_prompt}")
        for message in result.messages:
            print(f"- {message}")
        for warning in result.warnings:
            print(f"WARN: {warning}")
        for error in result.errors:
            print(error, file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
