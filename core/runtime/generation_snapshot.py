#!/usr/bin/env python3
"""Generation snapshot archival for Package 4.7 reproducibility."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .generation_evidence_ledger import EvidenceRecord, file_sha256, utc_now
from .generation_index import GenerationIndex, GenerationIndexRecord
from .project_workspace import ProjectManifest
from .workflow_provenance import (
    ExecutionProvenance,
    HASH_TYPE_API,
    HASH_TYPE_UI,
    hash_api_prompt,
    hash_ui_workflow,
)

PACKAGE_VERSION = "4.7"
SNAPSHOT_SCHEMA_VERSION = 1
METADATA_SCHEMA_VERSION = 1
WORKFLOW_SNAPSHOT_SCHEMA_VERSION = 1
EXPORT_SCHEMA_VERSION = 1

METADATA_FILENAME = "metadata.json"
WORKFLOW_FILENAME = "workflow.json"
MANIFEST_FILENAME = "manifest.json"


def new_generation_id() -> str:
    return f"gen_{uuid.uuid4()}"


def global_generations_root(drive_root: Path) -> Path:
    return drive_root / "generations"


def project_generations_root(drive_root: Path, project_slug: str) -> Path:
    return drive_root / "projects" / project_slug / "generations"


def resolve_snapshot_root(
    drive_root: Path,
    generation_id: str,
    *,
    project_slug: str = "",
) -> Path:
    if project_slug:
        return project_generations_root(drive_root, project_slug) / generation_id
    return global_generations_root(drive_root) / generation_id


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_sha256(data: Any) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def file_content_sha256(path: Path) -> str:
    return file_sha256(path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def is_snapshot_complete(snapshot_root: Path) -> bool:
    manifest = snapshot_root / MANIFEST_FILENAME
    metadata = snapshot_root / METADATA_FILENAME
    if not manifest.is_file() or not metadata.is_file():
        return False
    try:
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return str(manifest_data.get("snapshot_status") or "") == "complete"


def capture_repository_metadata(repo_root: Path | None) -> dict[str, Any]:
    result = {
        "repository_commit": None,
        "repository_branch": None,
        "repository_dirty": None,
    }
    if repo_root is None or not (repo_root / ".git").exists():
        return result
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if commit.returncode == 0:
            result["repository_commit"] = commit.stdout.strip()
        branch = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if branch.returncode == 0:
            result["repository_branch"] = branch.stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if dirty.returncode == 0:
            result["repository_dirty"] = bool(dirty.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return result


def build_workflow_snapshot(
    *,
    generation_id: str,
    ui_workflow: dict[str, Any] | None,
    api_prompt: dict[str, Any] | None,
    provenance: ExecutionProvenance | None,
) -> tuple[dict[str, Any], str]:
    ui_available = isinstance(ui_workflow, dict) and bool(ui_workflow)
    api_available = isinstance(api_prompt, dict) and bool(api_prompt)
    if ui_available:
        workflow_status = "complete"
    elif api_available:
        workflow_status = "partial"
    else:
        workflow_status = "unavailable"

    prov = provenance or ExecutionProvenance()
    payload: dict[str, Any] = {
        "workflow_schema_version": WORKFLOW_SNAPSHOT_SCHEMA_VERSION,
        "generation_id": generation_id,
        "ui_workflow_available": ui_available,
        "api_prompt_available": api_available,
        "ui_workflow": ui_workflow if ui_available else None,
        "api_prompt": api_prompt if api_available else None,
        "workflow_identifier": prov.workflow_identifier or None,
        "workflow_source": prov.workflow_source or None,
        "workflow_hash_type": prov.workflow_hash_type or None,
        "workflow_hash": prov.workflow_hash or None,
        "api_prompt_hash": prov.api_prompt_hash or None,
        "workflow_snapshot_status": workflow_status,
    }
    if ui_available:
        payload["computed_ui_hash"] = hash_ui_workflow(ui_workflow)
    if api_available:
        payload["computed_api_hash"] = hash_api_prompt(api_prompt)
    return payload, workflow_status


def build_metadata_snapshot(
    *,
    generation_id: str,
    record: EvidenceRecord,
    provenance: ExecutionProvenance | None,
    active_project: ProjectManifest | None,
    workflow_snapshot_status: str,
    runtime_id: str = "",
    repo_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prov = provenance or ExecutionProvenance()
    repo_meta = repo_meta or {}
    project_slug = active_project.slug if active_project else None
    project_name = active_project.display_name if active_project else None
    project_id = record.project_id or (active_project.project_id if active_project else None)

    def _nullable(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, list) and not value:
            return None
        return value

    return {
        "schema_version": METADATA_SCHEMA_VERSION,
        "generation_id": generation_id,
        "prompt_id": record.prompt_id,
        "output_node_id": record.output_node_id,
        "created_timestamp": record.created_timestamp or None,
        "synchronized_timestamp": record.synchronized_timestamp or None,
        "project_id": _nullable(project_id),
        "project_slug": _nullable(project_slug),
        "project_name": _nullable(project_name),
        "capability": _nullable(record.capability or prov.capability),
        "workflow_identifier": _nullable(record.workflow_identifier or prov.workflow_identifier),
        "workflow_source": _nullable(record.workflow_source or prov.workflow_source),
        "workflow_hash": _nullable(record.workflow_hash or prov.workflow_hash),
        "workflow_hash_type": _nullable(record.workflow_hash_type or prov.workflow_hash_type),
        "api_prompt_hash": _nullable(record.api_prompt_hash or prov.api_prompt_hash),
        "model_family": _nullable(record.model_family or prov.model_family),
        "model_files": record.model_files or prov.model_files or None,
        "positive_prompt": _nullable(record.positive_prompt or prov.positive_prompt),
        "negative_prompt": _nullable(record.negative_prompt or prov.negative_prompt),
        "seed": record.seed if record.seed is not None else prov.seed,
        "steps": record.steps if record.steps is not None else prov.steps,
        "cfg": record.cfg if record.cfg is not None else prov.cfg,
        "sampler_name": _nullable(record.sampler_name or prov.sampler_name),
        "scheduler": _nullable(record.scheduler or prov.scheduler),
        "denoise": record.denoise if record.denoise is not None else prov.denoise,
        "width": record.width if record.width is not None else prov.width,
        "height": record.height if record.height is not None else prov.height,
        "batch_size": None,
        "source_filename": _nullable(record.source_filename),
        "drive_filename": _nullable(record.drive_filename),
        "canonical_output_path": _nullable(record.drive_path),
        "project_output_path": _nullable(record.project_output_path),
        "image_sha256": _nullable(record.drive_sha256 or record.local_sha256),
        "byte_size": record.byte_size or None,
        "sync_status": record.sync_status,
        "provenance_status": _nullable(record.provenance_status or prov.provenance_status),
        "runtime_id": _nullable(runtime_id),
        "repository_commit": repo_meta.get("repository_commit"),
        "repository_branch": repo_meta.get("repository_branch"),
        "repository_dirty": repo_meta.get("repository_dirty"),
        "package_version": PACKAGE_VERSION,
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "workflow_snapshot_status": workflow_snapshot_status,
    }


@dataclass
class SnapshotResult:
    generation_id: str
    snapshot_root: Path
    snapshot_status: str
    workflow_snapshot_status: str
    manifest_path: Path
    metadata_path: Path
    workflow_path: Path
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.snapshot_status == "snapshot_complete" and not self.error


def create_generation_snapshot(
    *,
    drive_root: Path,
    record: EvidenceRecord,
    dedupe_key: str,
    provenance: ExecutionProvenance | None,
    active_project: ProjectManifest | None,
    index_path: Path,
    ui_workflow: dict[str, Any] | None = None,
    api_prompt: dict[str, Any] | None = None,
    runtime_id: str = "",
    repo_root: Path | None = None,
    existing_generation_id: str = "",
) -> SnapshotResult:
    """Create or reuse a generation snapshot for a verified output."""
    index = GenerationIndex(index_path)
    generation_id = existing_generation_id or index.generation_id_for_dedupe_key(dedupe_key)
    if not generation_id:
        generation_id = new_generation_id()

    project_slug = active_project.slug if active_project else ""
    snapshot_root = resolve_snapshot_root(drive_root, generation_id, project_slug=project_slug)

    if is_snapshot_complete(snapshot_root):
        return SnapshotResult(
            generation_id=generation_id,
            snapshot_root=snapshot_root,
            snapshot_status="snapshot_complete",
            workflow_snapshot_status=str(
                json.loads((snapshot_root / METADATA_FILENAME).read_text(encoding="utf-8")).get(
                    "workflow_snapshot_status", "unknown"
                )
            ),
            manifest_path=snapshot_root / MANIFEST_FILENAME,
            metadata_path=snapshot_root / METADATA_FILENAME,
            workflow_path=snapshot_root / WORKFLOW_FILENAME,
        )

    try:
        workflow_payload, workflow_status = build_workflow_snapshot(
            generation_id=generation_id,
            ui_workflow=ui_workflow,
            api_prompt=api_prompt,
            provenance=provenance,
        )
        repo_meta = capture_repository_metadata(repo_root)
        metadata_payload = build_metadata_snapshot(
            generation_id=generation_id,
            record=record,
            provenance=provenance,
            active_project=active_project,
            workflow_snapshot_status=workflow_status,
            runtime_id=runtime_id,
            repo_meta=repo_meta,
        )

        snapshot_root.mkdir(parents=True, exist_ok=True)
        metadata_path = snapshot_root / METADATA_FILENAME
        workflow_path = snapshot_root / WORKFLOW_FILENAME
        manifest_path = snapshot_root / MANIFEST_FILENAME

        _atomic_write_json(metadata_path, metadata_payload)
        _atomic_write_json(workflow_path, workflow_payload)

        metadata_hash = file_content_sha256(metadata_path)
        workflow_hash = file_content_sha256(workflow_path)
        image_hash = str(record.drive_sha256 or record.local_sha256 or "")

        manifest_payload = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "generation_id": generation_id,
            "created_timestamp": utc_now(),
            "snapshot_status": "complete",
            "metadata_file": METADATA_FILENAME,
            "workflow_file": WORKFLOW_FILENAME,
            "canonical_output_path": record.drive_path or None,
            "project_output_path": record.project_output_path or None,
            "image_sha256": image_hash or None,
            "workflow_sha256": workflow_hash,
            "metadata_sha256": metadata_hash,
        }
        _atomic_write_json(manifest_path, manifest_payload)

        index.append(
            GenerationIndexRecord(
                generation_id=generation_id,
                dedupe_key=dedupe_key,
                prompt_id=record.prompt_id,
                output_node_id=record.output_node_id,
                project_id=record.project_id or (active_project.project_id if active_project else ""),
                project_slug=project_slug,
                capability=record.capability,
                created_timestamp=record.synchronized_timestamp or record.created_timestamp,
                canonical_output_path=record.drive_path,
                snapshot_root=str(snapshot_root),
                snapshot_status="snapshot_complete",
                image_sha256=image_hash,
                drive_filename=record.drive_filename,
            )
        )

        return SnapshotResult(
            generation_id=generation_id,
            snapshot_root=snapshot_root,
            snapshot_status="snapshot_complete",
            workflow_snapshot_status=workflow_status,
            manifest_path=manifest_path,
            metadata_path=metadata_path,
            workflow_path=workflow_path,
        )
    except (OSError, TypeError, ValueError) as exc:
        return SnapshotResult(
            generation_id=generation_id,
            snapshot_root=snapshot_root,
            snapshot_status="snapshot_failed",
            workflow_snapshot_status="unavailable",
            manifest_path=snapshot_root / MANIFEST_FILENAME,
            metadata_path=snapshot_root / METADATA_FILENAME,
            workflow_path=snapshot_root / WORKFLOW_FILENAME,
            error=str(exc),
        )


def load_snapshot_by_id(drive_root: Path, generation_id: str) -> dict[str, Any] | None:
    """Find snapshot manifest by generation_id under global or project trees."""
    candidates = [global_generations_root(drive_root) / generation_id]
    projects_root = drive_root / "projects"
    if projects_root.is_dir():
        for project_dir in projects_root.iterdir():
            if project_dir.is_dir():
                candidates.append(project_generations_root(drive_root, project_dir.name) / generation_id)
    for root in candidates:
        manifest = root / MANIFEST_FILENAME
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            data["snapshot_root"] = str(root)
            return data
    return None


def validate_snapshot(snapshot_root: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = snapshot_root / MANIFEST_FILENAME
    metadata_path = snapshot_root / METADATA_FILENAME
    workflow_path = snapshot_root / WORKFLOW_FILENAME
    if not manifest_path.is_file():
        errors.append("Missing manifest.json")
        return errors
    if not metadata_path.is_file():
        errors.append("Missing metadata.json")
    if not workflow_path.is_file():
        errors.append("Missing workflow.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Invalid manifest.json: {exc}")
        return errors
    gid = str(manifest.get("generation_id") or "")
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Invalid metadata.json: {exc}")
            metadata = {}
        if gid and str(metadata.get("generation_id") or "") != gid:
            errors.append("generation_id mismatch between manifest and metadata")
        declared_meta_hash = str(manifest.get("metadata_sha256") or "")
        if declared_meta_hash and file_content_sha256(metadata_path) != declared_meta_hash:
            errors.append("metadata_sha256 mismatch")
        canonical = str(metadata.get("canonical_output_path") or manifest.get("canonical_output_path") or "")
        image_hash = str(metadata.get("image_sha256") or manifest.get("image_sha256") or "")
        if canonical and Path(canonical).is_file() and image_hash:
            if file_sha256(Path(canonical)) != image_hash:
                errors.append("canonical image SHA-256 mismatch")
        elif canonical and not Path(canonical).is_file():
            errors.append(f"canonical output missing: {canonical}")
    if workflow_path.is_file():
        declared_wf_hash = str(manifest.get("workflow_sha256") or "")
        if declared_wf_hash and file_content_sha256(workflow_path) != declared_wf_hash:
            errors.append("workflow_sha256 mismatch")
    return errors
