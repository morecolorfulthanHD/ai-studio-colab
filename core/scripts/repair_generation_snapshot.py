#!/usr/bin/env python3
"""Repair generation snapshots from intact metadata/workflow files."""

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

from core.runtime.generation_evidence_ledger import file_sha256, utc_now
from core.runtime.generation_identity import InvalidGenerationIdError, normalize_generation_id
from core.runtime.generation_snapshot import (
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    SNAPSHOT_SCHEMA_VERSION,
    WORKFLOW_FILENAME,
    file_content_sha256,
    load_snapshot_by_id,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def repair_manifest(snapshot_root: Path, *, dry_run: bool) -> dict:
    metadata_path = snapshot_root / METADATA_FILENAME
    workflow_path = snapshot_root / WORKFLOW_FILENAME
    manifest_path = snapshot_root / MANIFEST_FILENAME
    if not metadata_path.is_file() or not workflow_path.is_file():
        return {"repaired": False, "reason": "metadata or workflow missing"}
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    manifest_payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generation_id": metadata.get("generation_id"),
        "created_timestamp": utc_now(),
        "snapshot_status": "complete",
        "metadata_file": METADATA_FILENAME,
        "workflow_file": WORKFLOW_FILENAME,
        "canonical_output_path": metadata.get("canonical_output_path"),
        "project_output_path": metadata.get("project_output_path"),
        "image_sha256": metadata.get("image_sha256"),
        "workflow_sha256": file_content_sha256(workflow_path),
        "metadata_sha256": file_content_sha256(metadata_path),
    }
    if dry_run:
        return {"repaired": True, "dry_run": True, "manifest": manifest_payload}
    manifest_path.write_text(json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8")
    return {"repaired": True, "manifest_path": str(manifest_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair AI Studio generation snapshots.")
    parser.add_argument(
        "--generation-id",
        required=True,
        help="Generation ID as gen_<UUID> or bare UUID.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        generation_id = normalize_generation_id(args.generation_id)
    except InvalidGenerationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    try:
        manifest = load_snapshot_by_id(bundle.path("drive_root"), generation_id)
    except InvalidGenerationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if manifest is None:
        print(f"ERROR: Generation not found:\n{generation_id}", file=sys.stderr)
        return 1

    snapshot_root = Path(str(manifest.get("snapshot_root") or ""))
    result = repair_manifest(snapshot_root, dry_run=args.dry_run)
    result["generation_id"] = generation_id
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result.get("repaired"):
            print("Manifest repair preview OK." if args.dry_run else "Manifest repaired.")
            print(f"generation_id: {generation_id}")
        else:
            print(f"Repair skipped: {result.get('reason')}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
