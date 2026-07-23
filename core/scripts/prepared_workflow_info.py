#!/usr/bin/env python3
"""Show details for one prepared workflow."""

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
from core.runtime.prepared_workflow_index import find_by_preparation_id, preparations_log_path
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _load_metadata(prepared_dir: Path, preparation_id: str) -> dict:
    metadata_path = prepared_dir / f"{preparation_id}.metadata.json"
    if not metadata_path.is_file():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Show prepared workflow details.")
    parser.add_argument("--preparation-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    try:
        preparation_id = normalize_preparation_id(args.preparation_id)
    except InvalidPreparationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    log_path = preparations_log_path(bundle.path("drive_root"))
    record = find_by_preparation_id(log_path, preparation_id)
    if record is None:
        print(f"ERROR: Preparation not found: {preparation_id}", file=sys.stderr)
        return 1

    prepared_dir = Path(str(record.get("drive_prepared_dir") or record.get("runtime_prepared_dir") or ""))
    metadata = _load_metadata(prepared_dir, preparation_id) if prepared_dir.is_dir() else {}
    payload = {"index_record": record, "metadata": metadata}

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("AI Studio — Prepared Workflow Info")
    print("=" * 40)
    print(f"Preparation ID: {preparation_id}")
    print(f"Workflow:       {record.get('workflow_identifier')}")
    print(f"Readiness:      {record.get('readiness_status')}")
    if args.summary:
        print(f"Prepared hash:  {record.get('prepared_workflow_hash')}")
    else:
        print(f"Drive dir:      {record.get('drive_prepared_dir')}")
        print(f"Runtime dir:    {record.get('runtime_prepared_dir')}")
        if metadata:
            print(f"Parameters:     {json.dumps(metadata.get('parameters', {}), sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
