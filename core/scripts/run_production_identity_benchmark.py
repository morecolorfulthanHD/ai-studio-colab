#!/usr/bin/env python3
"""One-action production identity benchmark (Package 4.12.3 UX orchestrator).

Wraps InstantID prepare/execute/capture/QA/report. Emits machine-readable status:
COMPLETE | HUMAN_REVIEW_REQUIRED | FAILED.

Lower-level runner still requires --execute-benchmark --allow-benchmark
--i-acknowledge-gpu-cost; this wrapper is the controlled user/operator gate.
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

from core.runtime.production_identity_benchmark import (
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_HUMAN_REVIEW,
    parse_production_scenarios,
    run_production_identity_benchmark,
)
from core.runtime.registry_loader import find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run production InstantID identity benchmark (one-action S1–S4)."
    )
    parser.add_argument("--character-id", default=None, help="Explicit character ID.")
    parser.add_argument(
        "--scenario",
        default="S1-S4",
        help="Default S1-S4. Comma list or shorthand also accepted.",
    )
    parser.add_argument(
        "--user-confirmed-gpu-run",
        action="store_true",
        help="Interactive confirmation already obtained (or menu y confirmed).",
    )
    parser.add_argument(
        "--operator-live-intent",
        action="store_true",
        help=(
            "Cursor/operator: originating user request explicitly asked to RUN "
            "the live production identity benchmark. Satisfies routine confirmation only."
        ),
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt; require character-id when multiple characters exist.",
    )
    parser.add_argument("--continue-after-fail", action="store_true")
    parser.add_argument("--completion-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--allow-missing-models", action="store_true")
    parser.add_argument("--allow-missing-nodes", action="store_true")
    parser.add_argument(
        "--allow-unverified-assets",
        action="store_true",
        help="Investigation only; does not unlock promotion.",
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="Emit structured JSON result.")
    args = parser.parse_args()

    try:
        scenarios = parse_production_scenarios(args.scenario)
    except ValueError as exc:
        print(f"ERROR: Unknown scenario: {exc}", file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    payload = run_production_identity_benchmark(
        repo_root,
        character_id=args.character_id,
        scenarios=scenarios,
        user_confirmed_gpu_run=bool(args.user_confirmed_gpu_run),
        operator_live_intent=bool(args.operator_live_intent),
        interactive=not args.non_interactive,
        continue_after_fail=bool(args.continue_after_fail),
        completion_timeout_seconds=args.completion_timeout_seconds,
        allow_missing_models=bool(args.allow_missing_models),
        allow_missing_nodes=bool(args.allow_missing_nodes),
        allow_unverified_assets=bool(args.allow_unverified_assets),
        seed=args.seed,
    )

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("\nAI Studio — Production Identity Benchmark")
        print("=" * 50)
        print(f"status:           {payload.get('status')}")
        print(f"character:        {payload.get('display_name')} ({payload.get('character_id')})")
        print(f"scenarios:        {', '.join(payload.get('scenarios_requested') or [])}")
        print(f"completed:        {', '.join(payload.get('scenarios_completed') or []) or '-'}")
        print(f"reused:           {', '.join(payload.get('scenarios_skipped_reuse') or []) or '-'}")
        print(f"prompt_ids:       {', '.join(payload.get('prompt_ids') or []) or '-'}")
        print(f"ledger:           {payload.get('ledger_path')}")
        for path in payload.get("report_paths") or []:
            print(f"report:           {path}")
        if payload.get("human_review_required"):
            print("human_review:     REQUIRED")
        if payload.get("failure_reason"):
            print(f"failure_reason:   {payload.get('failure_reason')}")

    status = str(payload.get("status") or STATUS_FAILED)
    if status == STATUS_COMPLETE:
        return 0
    if status == STATUS_HUMAN_REVIEW:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
