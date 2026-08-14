#!/usr/bin/env python3
"""Compare a source generation to a reproduction preparation (Package 4.10)."""

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
from core.runtime.generation_reproduction import compare_generation_to_preparation
from core.runtime.generation_snapshot import METADATA_FILENAME, WORKFLOW_FILENAME, load_snapshot_by_id
from core.runtime.preparation_identity import InvalidPreparationIdError, normalize_preparation_id
from core.runtime.prepared_workflow_index import find_by_preparation_id, preparations_log_path
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare source generation executed state to a reproduction preparation."
    )
    parser.add_argument("--source-generation", required=True)
    parser.add_argument("--reproduction-preparation", required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        generation_id = normalize_generation_id(args.source_generation)
    except InvalidGenerationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        preparation_id = normalize_preparation_id(args.reproduction_preparation)
    except InvalidPreparationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    drive_root = bundle.path("drive_root")

    manifest = load_snapshot_by_id(drive_root, generation_id)
    if manifest is None:
        print(f"ERROR: Generation not found:\n{generation_id}", file=sys.stderr)
        return 1
    snapshot_root = Path(str(manifest.get("snapshot_root") or ""))
    gen_metadata = _load_json(snapshot_root / METADATA_FILENAME)
    gen_workflow = _load_json(snapshot_root / WORKFLOW_FILENAME)

    record = find_by_preparation_id(preparations_log_path(drive_root), preparation_id)
    if record is None:
        print(f"ERROR: Preparation not found: {preparation_id}", file=sys.stderr)
        return 1
    prepared_dir = Path(str(record.get("drive_prepared_dir") or record.get("runtime_prepared_dir") or ""))
    prep_metadata = _load_json(prepared_dir / f"{preparation_id}.metadata.json")
    prep_workflow = _load_json(prepared_dir / f"{preparation_id}.workflow.json")
    if not prep_metadata:
        print(f"ERROR: Preparation metadata missing: {prepared_dir}", file=sys.stderr)
        return 1

    report = compare_generation_to_preparation(
        generation_metadata=gen_metadata,
        generation_workflow=gen_workflow,
        preparation_metadata=prep_metadata,
        preparation_workflow=prep_workflow,
    )
    report["source_generation_id"] = generation_id
    report["reproduction_preparation_id"] = preparation_id

    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report.get("all_match") else 1

    print("AI Studio — Generation / Reproduction Comparison")
    print("=" * 40)
    print(f"Source generation:           {generation_id}")
    print(f"Reproduction preparation:    {preparation_id}")
    print(f"Lineage OK:                  {'yes' if report.get('lineage_ok') else 'no'}")
    print(f"All checks match:            {'yes' if report.get('all_match') else 'no'}")
    if report.get("reproduction_scope"):
        print(f"Reproduction scope:          {report.get('reproduction_scope')}")
    if report.get("source_batch_size") is not None:
        print(f"Source batch size:           {report.get('source_batch_size')}")
    if report.get("expected_batch_size") is not None:
        print(f"Expected prep batch size:    {report.get('expected_batch_size')}")
    print()
    for check in report.get("checks") or []:
        status = "MATCH" if check.get("match") else "DIFF"
        print(
            f"  [{status}] {check.get('field')}: "
            f"source={check.get('source')!r} prep={check.get('preparation')!r}"
        )
    return 0 if report.get("all_match") else 1


if __name__ == "__main__":
    raise SystemExit(main())
