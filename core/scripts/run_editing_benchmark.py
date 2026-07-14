#!/usr/bin/env python3
"""Record a structured editing benchmark entry (metadata only; no invented scores)."""

from __future__ import annotations

import argparse
import hashlib
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

from core.runtime.editing_benchmark import (
    EditingBenchmarkRecord,
    append_benchmark_record,
    empty_human_review_template,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _sha(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Append one editing benchmark ledger record.")
    parser.add_argument("--candidate-model", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--mask", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--seed", default=None)
    parser.add_argument("--success", action="store_true")
    parser.add_argument("--failed", action="store_true")
    parser.add_argument("--drive-sync-status", default="unknown")
    parser.add_argument("--evidence-status", default="unknown")
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.success and args.failed:
        print("ERROR: use only one of --success/--failed", file=sys.stderr)
        return 1

    repo_root = find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    ledger = args.ledger or (bundle.path("drive_logs") / "editing_benchmark.jsonl")

    success = True if args.success else False if args.failed else None
    record = EditingBenchmarkRecord(
        candidate_model=args.candidate_model,
        workflow=args.workflow,
        task=args.task,
        prompt=args.prompt,
        source_hash=_sha(args.source),
        mask_hash=_sha(args.mask),
        seed=args.seed,
        success=success,
        output_path=str(args.output) if args.output else "",
        drive_sync_status=args.drive_sync_status,
        evidence_status=args.evidence_status,
        human_review=empty_human_review_template(),
    )
    append_benchmark_record(ledger, record)
    if args.json:
        print(json.dumps(record.to_dict(), indent=2))
    else:
        print(f"Appended benchmark record to {ledger}")
    print("RESULT: OK — benchmark record written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
