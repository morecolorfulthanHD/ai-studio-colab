#!/usr/bin/env python3
"""Validate prepared workflow library artifacts."""

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

from core.runtime.preparation_identity import InvalidPreparationIdError, normalize_preparation_id
from core.runtime.prepared_workflow_index import find_by_preparation_id, preparations_log_path, read_preparation_records
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_provenance import hash_ui_workflow


def validate_prepared_dir(prepared_dir: Path, preparation_id: str) -> list[str]:
    errors: list[str] = []
    workflow_path = prepared_dir / f"{preparation_id}.workflow.json"
    metadata_path = prepared_dir / f"{preparation_id}.metadata.json"
    manifest_path = prepared_dir / f"{preparation_id}.manifest.json"
    for path in (workflow_path, metadata_path, manifest_path):
        if not path.is_file():
            errors.append(f"missing file: {path.name}")
    if errors:
        return errors

    try:
        workflow_data = json.loads(workflow_path.read_text(encoding="utf-8"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid JSON: {exc}"]

    computed_hash = hash_ui_workflow(workflow_data)
    declared = str(manifest.get("prepared_workflow_hash") or metadata.get("prepared_workflow_hash") or "")
    if declared and computed_hash != declared:
        errors.append("prepared_workflow_hash mismatch")
    if str(manifest.get("preparation_id") or "") != preparation_id:
        errors.append("preparation_id mismatch in manifest")
    if str(metadata.get("preparation_id") or "") != preparation_id:
        errors.append("preparation_id mismatch in metadata")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate prepared workflow artifacts.")
    parser.add_argument("--preparation-id", default="")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    if not args.all and not args.preparation_id:
        print("ERROR: Provide --preparation-id or --all.", file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    log_path = preparations_log_path(bundle.path("drive_root"))

    targets: list[tuple[str, Path]] = []
    if args.all:
        for row in read_preparation_records(log_path):
            prep_id = str(row.get("preparation_id") or "")
            prepared_dir = Path(str(row.get("drive_prepared_dir") or row.get("runtime_prepared_dir") or ""))
            if prep_id and prepared_dir.is_dir():
                targets.append((prep_id, prepared_dir))
    else:
        try:
            prep_id = normalize_preparation_id(args.preparation_id)
        except InvalidPreparationIdError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        record = find_by_preparation_id(log_path, prep_id)
        if record is None:
            print(f"ERROR: Preparation not found: {prep_id}", file=sys.stderr)
            return 1
        prepared_dir = Path(str(record.get("drive_prepared_dir") or record.get("runtime_prepared_dir") or ""))
        targets.append((prep_id, prepared_dir))

    results = []
    failed = 0
    for prep_id, prepared_dir in targets:
        errors = validate_prepared_dir(prepared_dir, prep_id)
        ok = not errors
        if not ok:
            failed += 1
        results.append({"preparation_id": prep_id, "ok": ok, "errors": errors, "path": str(prepared_dir)})

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("AI Studio — Validate Prepared Workflows")
        print("=" * 40)
        for item in results:
            status = "PASS" if item["ok"] else "FAIL"
            if args.summary:
                print(f"{item['preparation_id']:40} {status}")
            else:
                print(f"{status} {item['preparation_id']}")
                for err in item["errors"]:
                    print(f"  - {err}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
