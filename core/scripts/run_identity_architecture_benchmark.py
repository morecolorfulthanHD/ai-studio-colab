#!/usr/bin/env python3
"""Run identity architecture benchmark (Package 4.12.3).

Default: prepare/dry-run only.
Live execution requires:
  --execute-benchmark --allow-benchmark --i-acknowledge-gpu-cost
and posts to ComfyUI /prompt (no browser click for normal runs).
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

from core.runtime.identity_architecture_benchmark import (
    CANDIDATE_INSTANTID,
    SCENARIO_DIMENSIONS,
    prepare_identity_architecture_benchmark,
)
from core.runtime.identity_architecture_execution import (
    execute_architecture_scenario,
    should_fail_fast,
)
from core.runtime.identity_benchmark import SCENARIO_IDS, normalize_scenario_id
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _parse_scenarios(raw: str) -> list[str]:
    """Accept S1, S1-S4, comma list, or 'all'."""
    text = (raw or "").strip()
    if not text or text.lower() == "all":
        return list(SCENARIO_IDS)
    parts: list[str] = []
    for chunk in text.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk and chunk.upper().startswith("S") and chunk.count("-") == 1:
            left, right = chunk.split("-", 1)
            start = normalize_scenario_id(left)
            end = normalize_scenario_id(right)
            if start and end and start in SCENARIO_IDS and end in SCENARIO_IDS:
                i0 = SCENARIO_IDS.index(start)
                i1 = SCENARIO_IDS.index(end)
                parts.extend(SCENARIO_IDS[min(i0, i1) : max(i0, i1) + 1])
                continue
        canon = normalize_scenario_id(chunk)
        if canon is None:
            raise ValueError(chunk)
        parts.append(canon)
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for s in parts:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Package 4.12.3 identity architecture benchmark runner. "
            "Default is prepare/dry-run. --execute-benchmark requires "
            "--allow-benchmark and --i-acknowledge-gpu-cost."
        )
    )
    parser.add_argument(
        "--scenario",
        default="S1",
        help="Scenario ID, S1–S4 shorthand, comma list, S1-S4 range, or all.",
    )
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--allow-benchmark", action="store_true")
    parser.add_argument("--allow-missing-models", action="store_true")
    parser.add_argument("--allow-missing-nodes", action="store_true")
    parser.add_argument(
        "--allow-unverified-assets",
        action="store_true",
        help="Investigation only: skip InstantID hash verification fail-closed gate.",
    )
    parser.add_argument("--execute-benchmark", action="store_true")
    parser.add_argument("--i-acknowledge-gpu-cost", action="store_true")
    parser.add_argument("--continue-after-fail", action="store_true")
    parser.add_argument("--completion-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.execute_benchmark:
        if not args.allow_benchmark:
            print("ERROR: --execute-benchmark requires --allow-benchmark.", file=sys.stderr)
            return 1
        if not args.i_acknowledge_gpu_cost:
            print(
                "ERROR: --execute-benchmark requires --i-acknowledge-gpu-cost.",
                file=sys.stderr,
            )
            return 1

    try:
        scenarios = _parse_scenarios(args.scenario)
    except ValueError as exc:
        print(
            f"ERROR: Unknown scenario: {exc}. "
            f"Use S1–S4 or one of: {', '.join(SCENARIO_IDS)}",
            file=sys.stderr,
        )
        return 1
    if not scenarios:
        print("ERROR: No scenarios selected.", file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    comfy_runtime = bundle.path("comfyui_runtime")
    drive_root = bundle.path("drive_root")

    # Prepare-only path (default / dry-run).
    if not args.execute_benchmark or args.dry_run:
        canonical = scenarios[0]
        dry_run = True
        result = prepare_identity_architecture_benchmark(
            repo_root,
            drive_root=drive_root,
            scenario=canonical,
            character_id=args.character_id,
            runtime_prepared_root=bundle.path("runtime_root") / "prepared_workflows",
            drive_prepared_root=bundle.path("drive_workflows") / "prepared",
            comfyui_input_dir=comfy_runtime / "input",
            bundle_models=list(bundle.models),
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=comfy_runtime / "custom_nodes",
            seed=args.seed,
            require_models=not args.allow_missing_models,
            require_nodes=not args.allow_missing_nodes,
            dry_run=dry_run,
            allow_benchmark=args.allow_benchmark,
            candidate=CANDIDATE_INSTANTID,
        )
        payload = result.to_dict()
        payload["execute_benchmark"] = False
        payload["scenarios_requested"] = scenarios
        payload["fail_fast_policy"] = (
            "S1 identity fail → stop; S2/S3 clear fail → stop unless --continue-after-fail; "
            "S4 clear fail → stop; INCONCLUSIVE → pause for human review"
        )
        payload["scenario_dimensions"] = {
            "width": result.width,
            "height": result.height,
            "canonical": SCENARIO_DIMENSIONS.get(canonical),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("AI Studio — Identity Architecture Benchmark (PREPARE ONLY)")
            print("=" * 50)
            print(f"Scenario:      {result.scenario} ({result.width}x{result.height})")
            print(f"Preparation:   {result.preparation_id or '(dry-run/none)'}")
            for message in result.messages:
                print(f"- {message}")
            for warning in result.warnings:
                print(f"WARN: {warning}")
            for error in result.errors:
                print(error, file=sys.stderr)
            print("\nNOTE: Default is prepare-only. Live queue requires explicit ack flags.")
        return 0 if result.ok else 1

    # Live execution path — POST /prompt, poll history, capture, QA, fail-fast.
    scenario_results: list[dict] = []
    exit_code = 0
    stopped = False
    for scenario in scenarios:
        print(f"\n--- Executing {scenario} via ComfyUI /prompt ---", file=sys.stderr)
        exec_result = execute_architecture_scenario(
            repo_root=repo_root,
            drive_root=drive_root,
            character_id=args.character_id,
            scenario=scenario,
            bundle_models=list(bundle.models),
            bundle_nodes=list(bundle.nodes),
            runtime_prepared_root=bundle.path("runtime_root") / "prepared_workflows",
            comfyui_input_dir=comfy_runtime / "input",
            comfyui_runtime=comfy_runtime,
            comfyui_output_dir=comfy_runtime / "output",
            drive_prepared_root=bundle.path("drive_workflows") / "prepared",
            seed=args.seed,
            completion_timeout_seconds=args.completion_timeout_seconds,
            require_models=not args.allow_missing_models,
            require_nodes=not args.allow_missing_nodes,
            require_verified_assets=not args.allow_unverified_assets,
        )
        row = exec_result.to_dict()
        scenario_results.append(row)
        for message in exec_result.messages:
            print(f"- {message}")
        for error in exec_result.errors:
            print(error, file=sys.stderr)

        qa = exec_result.automated_qa or {}
        auto_status = str(qa.get("automated_quality_status") or "")
        if not exec_result.ok or auto_status == "fail":
            exit_code = 1
        if auto_status == "inconclusive":
            exit_code = 1
            print(
                f"INCONCLUSIVE on {scenario} — pausing for human review (fail-fast).",
                file=sys.stderr,
            )
            stopped = True
            break
        if should_fail_fast(scenario, qa, continue_after_fail=args.continue_after_fail):
            print(
                f"FAIL-FAST stop after {scenario} "
                f"(status={auto_status}; continue_after_fail={args.continue_after_fail}).",
                file=sys.stderr,
            )
            exit_code = 1
            stopped = True
            break
        if not exec_result.ok:
            # Execution infrastructure failure always stops.
            stopped = True
            break

    payload = {
        "execute_benchmark": True,
        "browser_required": False,
        "queue_invoked": True,
        "scenarios_requested": scenarios,
        "scenarios_completed": [r.get("scenario") for r in scenario_results],
        "stopped_fail_fast": stopped,
        "continue_after_fail": args.continue_after_fail,
        "results": scenario_results,
        "ok": exit_code == 0,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("\nAI Studio — Identity Architecture Benchmark (LIVE /prompt)")
        print("=" * 50)
        print(f"Scenarios: {', '.join(scenarios)}")
        print(f"Completed: {len(scenario_results)}  stopped_fail_fast={stopped}")
        for row in scenario_results:
            print(
                f"  {row.get('scenario')}: queue={row.get('queue_status')} "
                f"prompt_id={row.get('prompt_id') or '-'} "
                f"qa={(row.get('automated_qa') or {}).get('automated_quality_status')}"
            )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
