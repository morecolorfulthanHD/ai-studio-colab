#!/usr/bin/env python3
"""Append an identity-method benchmark ledger record (metadata only)."""

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

from core.runtime.identity_benchmark import (
    HUMAN_REVIEW_RUBRIC,
    IdentityBenchmarkRecord,
    LIVE_CANDIDATES,
    SCENARIO_IDS,
    append_identity_benchmark_record,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Append one identity benchmark ledger record (no invented perceptual scores)."
    )
    parser.add_argument("--candidate", required=True, choices=list(LIVE_CANDIDATES))
    parser.add_argument("--scenario", required=True, choices=list(SCENARIO_IDS))
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--seed", default="")
    parser.add_argument("--preparation-id", default="")
    parser.add_argument("--output-path", default="")
    parser.add_argument("--output-sha256", default="")
    parser.add_argument("--success", choices=["true", "false", "unknown"], default="unknown")
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--human-review-json", default="{}", help="JSON object of rubric key->pass|marginal|fail|not_applicable")
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        human_review = json.loads(args.human_review_json)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid --human-review-json: {exc}", file=sys.stderr)
        return 1
    if not isinstance(human_review, dict):
        print("ERROR: --human-review-json must be an object", file=sys.stderr)
        return 1
    for key in human_review:
        if key not in HUMAN_REVIEW_RUBRIC:
            print(f"ERROR: Unknown rubric key: {key}", file=sys.stderr)
            return 1

    success: bool | None
    if args.success == "true":
        success = True
    elif args.success == "false":
        success = False
    else:
        success = None

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    ledger = args.ledger or (RegistryLoader(repo_root).load_all().path("drive_logs") / "identity_benchmark.jsonl")
    record = IdentityBenchmarkRecord(
        candidate=args.candidate,
        scenario=args.scenario,
        character_id=args.character_id,
        seed=args.seed or None,
        preparation_id=args.preparation_id,
        output_path=args.output_path,
        output_sha256=args.output_sha256,
        success=success,
        human_review={str(k): str(v) for k, v in human_review.items()},
        notes=list(args.note),
    )
    append_identity_benchmark_record(ledger, record)
    if args.json:
        print(json.dumps({"ledger": str(ledger), "record": record.to_dict()}, indent=2))
    else:
        print(f"Appended identity benchmark record to {ledger}")
        print("RESULT: OK — identity benchmark record written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
