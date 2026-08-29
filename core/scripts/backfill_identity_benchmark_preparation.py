#!/usr/bin/env python3
"""Backfill Drive mirror + preparation index for an existing identity benchmark prep."""

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

from core.runtime.identity_benchmark import backfill_identity_benchmark_preparation
from core.runtime.preparation_identity import InvalidPreparationIdError, normalize_preparation_id
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _default_runtime_dir(bundle, preparation_id: str) -> Path:
    return bundle.path("runtime_root") / "prepared_workflows" / preparation_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mirror an existing runtime identity-benchmark preparation to Drive and "
            "append workflow_preparations.jsonl without recreating the prep."
        )
    )
    parser.add_argument("--preparation-id", required=True)
    parser.add_argument(
        "--runtime-prepared-dir",
        type=Path,
        default=None,
        help="Runtime prepared directory containing workflow + metadata (default: runtime_root/prepared_workflows/<id>).",
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        preparation_id = normalize_preparation_id(args.preparation_id)
    except InvalidPreparationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    runtime_dir = (
        args.runtime_prepared_dir.resolve()
        if args.runtime_prepared_dir
        else _default_runtime_dir(bundle, preparation_id)
    )
    result = backfill_identity_benchmark_preparation(
        drive_root=bundle.path("drive_root"),
        preparation_id=preparation_id,
        runtime_prepared_dir=runtime_dir,
        drive_prepared_root=bundle.path("drive_workflows") / "prepared",
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("AI Studio — Identity Benchmark Preparation Backfill")
        print("=" * 40)
        print(f"Preparation:   {result.preparation_id}")
        print(f"Runtime dir:   {result.runtime_prepared_dir}")
        print(f"Drive dir:     {result.drive_prepared_dir or '(pending)'}")
        print(f"Index appended:{result.index_appended}")
        for message in result.messages:
            print(f"- {message}")
        for warning in result.warnings:
            print(f"WARN: {warning}")
        for error in result.errors:
            print(error, file=sys.stderr)
    if not result.ok:
        return 1
    print(
        "\nNext: python core/scripts/open_prepared_workflow.py "
        f"--preparation-id {preparation_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
