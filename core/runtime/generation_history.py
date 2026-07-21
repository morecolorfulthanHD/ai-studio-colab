#!/usr/bin/env python3
"""Read and summarize generation evidence (legacy Package 4.4 and enriched Package 4.5+ rows)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .generation_evidence_ledger import EvidenceLedger


def is_legacy_row(row: dict[str, Any]) -> bool:
    return int(row.get("schema_version") or 1) < 2


def provenance_label(row: dict[str, Any]) -> str:
    if is_legacy_row(row):
        return "legacy"
    status = str(row.get("provenance_status") or "")
    if status:
        return status
    if row.get("workflow_identifier") and row.get("workflow_hash"):
        return "partial"
    return "legacy"


def prompt_excerpt(row: dict[str, Any], *, max_len: int = 60) -> str:
    text = str(row.get("positive_prompt") or row.get("prompt_excerpt") or "")
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


@dataclass
class GenerationHistorySummary:
    total: int = 0
    verified: int = 0
    pending: int = 0
    failed: int = 0
    legacy: int = 0
    complete_provenance: int = 0
    partial_provenance: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "verified": self.verified,
            "pending": self.pending,
            "failed": self.failed,
            "legacy": self.legacy,
            "complete_provenance": self.complete_provenance,
            "partial_provenance": self.partial_provenance,
        }


def summarize_ledger(path: Path) -> GenerationHistorySummary:
    rows = EvidenceLedger(path).read_all()
    summary = GenerationHistorySummary(total=len(rows))
    for row in rows:
        status = str(row.get("sync_status") or "")
        if status == "verified":
            summary.verified += 1
        elif status == "pending":
            summary.pending += 1
        elif status == "failed":
            summary.failed += 1
        label = provenance_label(row)
        if label == "legacy":
            summary.legacy += 1
        elif label == "complete":
            summary.complete_provenance += 1
        elif label == "partial":
            summary.partial_provenance += 1
    return summary


def generation_key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("prompt_id") or ""),
            str(row.get("output_node_id") or ""),
            str(row.get("local_path") or ""),
            str(row.get("local_sha256") or ""),
        ]
    )


def snapshot_status_label(row: dict[str, Any]) -> str:
    status = str(row.get("snapshot_status") or "")
    if status == "snapshot_complete":
        return "complete"
    if status == "snapshot_failed":
        return "failed"
    if status:
        return status.replace("snapshot_", "")
    if row.get("generation_id"):
        return "legacy"
    return "none"


def generation_display_id(row: dict[str, Any]) -> str:
    gid = str(row.get("generation_id") or "")
    if gid:
        return gid
    return "legacy"


def collapse_generations(
    path: Path,
    *,
    generation_id: str = "",
    project: str = "",
    project_id: str = "",
    capability: str = "",
    workflow: str = "",
    model_family: str = "",
    model_file: str = "",
    seed: str = "",
    date_from: str = "",
    date_to: str = "",
    prompt_contains: str = "",
    sync_status: str = "verified",
    provenance_status: str = "",
    snapshot_status: str = "",
    image_sha256: str = "",
    drive_filename: str = "",
    verified_only: bool = True,
    raw: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return resolved generation views (latest status per execution key by default)."""
    from .generation_identity import InvalidGenerationIdError, normalize_generation_id

    rows = EvidenceLedger(path).read_all()
    if raw:
        selected = list(rows)
    else:
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest[generation_key(row)] = row
        selected = list(latest.values())

    filter_gid = ""
    if generation_id:
        try:
            filter_gid = normalize_generation_id(generation_id)
        except InvalidGenerationIdError:
            raise

    filtered: list[dict[str, Any]] = []
    needle = prompt_contains.lower().strip()
    seed_needle = seed.strip()
    for row in selected:
        status = str(row.get("sync_status") or "")
        if verified_only and status != "verified":
            continue
        if sync_status and status != sync_status:
            continue
        if filter_gid and str(row.get("generation_id") or "") != filter_gid:
            continue
        if project or project_id:
            row_project_id = str(row.get("project_id") or "")
            project_path = str(row.get("project_output_path") or "").replace("\\", "/")
            slug_hit = bool(project) and f"/projects/{project}/" in project_path
            id_hit = bool(project_id) and row_project_id == project_id
            # --project may be a raw project_id.
            slug_as_id_hit = bool(project) and row_project_id == project
            if project_id:
                # project_id is authoritative; allow legacy rows with empty project_id
                # that still reference the slug path.
                legacy_slug_hit = (not row_project_id) and slug_hit
                if not (id_hit or legacy_slug_hit or slug_as_id_hit):
                    continue
            elif not (slug_hit or slug_as_id_hit):
                continue
        if capability and str(row.get("capability") or "") != capability:
            continue
        if workflow and str(row.get("workflow_identifier") or "") != workflow:
            continue
        if model_family and str(row.get("model_family") or "") != model_family:
            continue
        if model_file:
            files = [str(item) for item in (row.get("model_files") or [])]
            if model_file not in files:
                continue
        if seed_needle:
            row_seed = row.get("seed")
            if row_seed is None or str(row_seed) != seed_needle:
                continue
        if snapshot_status:
            label = snapshot_status_label(row)
            if label != snapshot_status and str(row.get("snapshot_status") or "") != snapshot_status:
                continue
        if image_sha256:
            digest = str(row.get("drive_sha256") or row.get("local_sha256") or "")
            if digest != image_sha256:
                continue
        if drive_filename and str(row.get("drive_filename") or "") != drive_filename:
            continue
        if provenance_status and provenance_label(row) != provenance_status:
            continue
        stamp = str(row.get("synchronized_timestamp") or row.get("created_timestamp") or "")
        day = stamp[:10]
        if date_from and (not day or day < date_from):
            continue
        if date_to and (not day or day > date_to):
            continue
        if needle and needle not in str(row.get("positive_prompt") or "").lower():
            continue
        filtered.append(row)

    filtered.sort(
        key=lambda row: str(row.get("synchronized_timestamp") or row.get("created_timestamp") or ""),
        reverse=True,
    )
    return filtered[: max(0, limit)]


def list_recent_generations(
    path: Path,
    *,
    limit: int = 20,
    verified_only: bool = False,
) -> list[dict[str, Any]]:
    return collapse_generations(
        path,
        verified_only=verified_only,
        sync_status="verified" if verified_only else "",
        limit=limit,
        raw=False,
    )


def find_generation_by_prompt_id(path: Path, prompt_id: str) -> list[dict[str, Any]]:
    return [row for row in EvidenceLedger(path).read_all() if str(row.get("prompt_id") or "") == prompt_id]


def list_project_assets(
    path: Path,
    *,
    project: str,
    project_id: str = "",
    capability: str = "",
    prompt_contains: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = collapse_generations(
        path,
        project=project,
        project_id=project_id,
        capability=capability,
        prompt_contains=prompt_contains,
        verified_only=True,
        limit=limit,
    )
    assets: list[dict[str, Any]] = []
    for row in rows:
        assets.append(
            {
                "prompt_id": row.get("prompt_id"),
                "drive_filename": row.get("drive_filename") or Path(str(row.get("drive_path") or "")).name,
                "capability": row.get("capability"),
                "workflow": row.get("workflow_identifier"),
                "model_family": row.get("model_family"),
                "prompt_excerpt": prompt_excerpt(row),
                "created_timestamp": row.get("synchronized_timestamp") or row.get("created_timestamp"),
                "sync_status": row.get("sync_status"),
                "canonical_global_path": row.get("drive_path"),
                "project_mirror_path": row.get("project_output_path"),
                "local_sha256": row.get("local_sha256"),
                "drive_sha256": row.get("drive_sha256"),
                "sha256_verified": bool(
                    row.get("local_sha256")
                    and row.get("drive_sha256")
                    and row.get("local_sha256") == row.get("drive_sha256")
                ),
                "provenance": provenance_label(row),
            }
        )
    return assets
