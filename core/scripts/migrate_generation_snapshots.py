#!/usr/bin/env python3
"""Migrate legacy verified generations to metadata-only snapshots."""

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

from core.runtime.generation_evidence_ledger import EvidenceLedger, EvidenceRecord, utc_now
from core.runtime.generation_history import generation_key
from core.runtime.generation_index import GenerationIndex, GenerationIndexRecord
from core.runtime.generation_snapshot import (
    build_metadata_snapshot,
    global_generations_root,
    is_snapshot_complete,
    new_generation_id,
    resolve_snapshot_root,
    build_workflow_snapshot,
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    WORKFLOW_FILENAME,
    file_content_sha256,
    SNAPSHOT_SCHEMA_VERSION,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_provenance import ExecutionProvenance


def _row_to_provenance(row: dict) -> ExecutionProvenance:
    return ExecutionProvenance(
        workflow_identifier=str(row.get("workflow_identifier") or "unknown"),
        workflow_hash=str(row.get("workflow_hash") or ""),
        workflow_hash_type=str(row.get("workflow_hash_type") or ""),
        api_prompt_hash=str(row.get("api_prompt_hash") or ""),
        workflow_source=str(row.get("workflow_source") or ""),
        capability=str(row.get("capability") or ""),
        model_family=str(row.get("model_family") or ""),
        model_files=list(row.get("model_files") or []),
        candidate_model=str(row.get("candidate_model") or ""),
        positive_prompt=str(row.get("positive_prompt") or ""),
        negative_prompt=str(row.get("negative_prompt") or ""),
        seed=row.get("seed"),
        steps=row.get("steps"),
        cfg=row.get("cfg"),
        sampler_name=str(row.get("sampler_name") or ""),
        scheduler=str(row.get("scheduler") or ""),
        denoise=row.get("denoise"),
        width=row.get("width"),
        height=row.get("height"),
        provenance_status=str(row.get("provenance_status") or ""),
    )


def _row_to_record(row: dict) -> EvidenceRecord:
    fields = EvidenceRecord.__dataclass_fields__
    payload = {k: row[k] for k in row if k in fields}
    return EvidenceRecord(**payload)


def migrate(*, drive_root: Path, evidence_path: Path, index_path: Path, apply: bool) -> dict:
    latest: dict[str, dict] = {}
    for row in EvidenceLedger(evidence_path).read_all():
        latest[generation_key(row)] = row

    migrated = []
    skipped = []
    for key, row in latest.items():
        if str(row.get("sync_status") or "") != "verified":
            continue
        if row.get("generation_id") and row.get("snapshot_root"):
            skipped.append({"key": key, "reason": "already has snapshot"})
            continue
        gid = str(row.get("generation_id") or new_generation_id())
        slug = ""
        project_path = str(row.get("project_output_path") or "").replace("\\", "/")
        if "/projects/" in project_path:
            slug = project_path.split("/projects/", 1)[1].split("/", 1)[0]
        snapshot_root = resolve_snapshot_root(drive_root, gid, project_slug=slug)
        if is_snapshot_complete(snapshot_root):
            skipped.append({"key": key, "reason": "snapshot already on disk"})
            continue

        record = _row_to_record(row)
        provenance = _row_to_provenance(row)
        workflow_payload, workflow_status = build_workflow_snapshot(
            generation_id=gid,
            ui_workflow=None,
            api_prompt=None,
            provenance=provenance,
        )
        metadata_payload = build_metadata_snapshot(
            generation_id=gid,
            record=record,
            provenance=provenance,
            active_project=None,
            workflow_snapshot_status=workflow_status,
        )
        manifest_payload = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "generation_id": gid,
            "created_timestamp": utc_now(),
            "snapshot_status": "complete",
            "metadata_file": METADATA_FILENAME,
            "workflow_file": WORKFLOW_FILENAME,
            "canonical_output_path": record.drive_path or None,
            "project_output_path": record.project_output_path or None,
            "image_sha256": record.drive_sha256 or record.local_sha256 or None,
        }
        entry = {
            "generation_id": gid,
            "dedupe_key": key,
            "snapshot_root": str(snapshot_root),
            "workflow_snapshot_status": workflow_status,
        }
        migrated.append(entry)
        if apply:
            snapshot_root.mkdir(parents=True, exist_ok=True)
            (snapshot_root / METADATA_FILENAME).write_text(
                json.dumps(metadata_payload, indent=2) + "\n", encoding="utf-8"
            )
            (snapshot_root / WORKFLOW_FILENAME).write_text(
                json.dumps(workflow_payload, indent=2) + "\n", encoding="utf-8"
            )
            manifest_payload["metadata_sha256"] = file_content_sha256(snapshot_root / METADATA_FILENAME)
            manifest_payload["workflow_sha256"] = file_content_sha256(snapshot_root / WORKFLOW_FILENAME)
            (snapshot_root / MANIFEST_FILENAME).write_text(
                json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8"
            )
            GenerationIndex(index_path).append(
                GenerationIndexRecord(
                    generation_id=gid,
                    dedupe_key=key,
                    prompt_id=str(row.get("prompt_id") or ""),
                    output_node_id=str(row.get("output_node_id") or ""),
                    project_id=str(row.get("project_id") or ""),
                    project_slug=slug,
                    capability=str(row.get("capability") or ""),
                    created_timestamp=str(row.get("synchronized_timestamp") or row.get("created_timestamp") or ""),
                    canonical_output_path=str(row.get("drive_path") or ""),
                    snapshot_root=str(snapshot_root),
                    snapshot_status="snapshot_complete",
                    image_sha256=str(row.get("drive_sha256") or row.get("local_sha256") or ""),
                    drive_filename=str(row.get("drive_filename") or ""),
                )
            )

    return {"apply": apply, "migrated": len(migrated), "skipped": len(skipped), "entries": migrated}


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy generations to snapshots.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run or --apply.")
    if args.dry_run and args.apply:
        parser.error("Choose only one of --dry-run or --apply.")

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    result = migrate(
        drive_root=bundle.path("drive_root"),
        evidence_path=bundle.path("drive_logs") / "generation_evidence.jsonl",
        index_path=bundle.path("drive_logs") / "generation_index.jsonl",
        apply=bool(args.apply),
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        mode = "apply" if args.apply else "dry-run"
        print(f"Migration ({mode}): {result['migrated']} migrated, {result['skipped']} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
