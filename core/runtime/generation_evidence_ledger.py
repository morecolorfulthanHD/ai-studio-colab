#!/usr/bin/env python3
"""Generation evidence ledger with SHA-256 verified Drive synchronization records.

Evidence status lifecycle (append-only):
  pending  → verified   (successful sync)
  pending  → failed     (bounded attempt exhausted or hard failure)
  failed   → verified   (recovery appends a new verified row for the same dedupe key)
  failed   → failed     (another bounded attempt appends another failed row)

Only *verified* rows permanently suppress retries (verified_keys / processed index).
Failed and pending rows remain retryable until a verified row exists for the same key,
or the local source is missing / hash-mismatched (reported, not faked as verified).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def dedupe_key_from_parts(
    prompt_id: str,
    output_node_id: str,
    local_path: str,
    local_sha256: str,
) -> str:
    return "|".join(
        [
            str(prompt_id or ""),
            str(output_node_id or ""),
            str(local_path or ""),
            str(local_sha256 or ""),
        ]
    )


def dedupe_key_from_row(row: dict[str, Any]) -> str:
    return dedupe_key_from_parts(
        str(row.get("prompt_id") or ""),
        str(row.get("output_node_id") or ""),
        str(row.get("local_path") or ""),
        str(row.get("local_sha256") or ""),
    )


@dataclass
class EvidenceRecord:
    prompt_id: str
    schema_version: int = 1
    provenance_version: int = 0
    workflow_identifier: str = ""
    workflow_hash: str = ""
    workflow_hash_type: str = ""
    api_prompt_hash: str = ""
    workflow_source: str = ""
    output_node_id: str = ""
    local_path: str = ""
    drive_path: str = ""
    source_filename: str = ""
    drive_filename: str = ""
    project_id: str = ""
    project_output_path: str = ""
    local_sha256: str = ""
    drive_sha256: str = ""
    byte_size: int = 0
    created_timestamp: str = ""
    synchronized_timestamp: str = ""
    sync_status: str = "pending"  # pending | verified | failed
    retry_count: int = 0
    error_summary: str = ""
    candidate_model: str = ""
    capability: str = ""
    model_family: str = ""
    model_files: list[str] = field(default_factory=list)
    positive_prompt: str = ""
    negative_prompt: str = ""
    seed: int | None = None
    steps: int | None = None
    cfg: float | None = None
    sampler_name: str = ""
    scheduler: str = ""
    denoise: float | None = None
    width: int | None = None
    height: int | None = None
    save_prefix: str = ""
    source_image_filenames: list[str] = field(default_factory=list)
    mask_filenames: list[str] = field(default_factory=list)
    provenance_status: str = ""
    missing_provenance_fields: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    prior_error_summary: str = ""
    # Package 4.7 generation snapshots
    generation_id: str = ""
    snapshot_status: str = ""
    snapshot_root: str = ""
    snapshot_manifest_path: str = ""
    snapshot_metadata_path: str = ""
    snapshot_workflow_path: str = ""
    workflow_snapshot_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # Omit null optional ints for compact legacy-compatible rows when unset.
        for key in ("seed", "steps", "cfg", "denoise", "width", "height"):
            if payload.get(key) is None:
                payload.pop(key, None)
        return payload

    @property
    def dedupe_key(self) -> str:
        return dedupe_key_from_parts(
            self.prompt_id,
            self.output_node_id,
            self.local_path,
            self.local_sha256,
        )


class EvidenceLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: EvidenceRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=".evidence_", suffix=".tmp", dir=str(self.path.parent))
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            existing = self.path.read_bytes() if self.path.is_file() else b""
            tmp_path.write_bytes(existing + line.encode("utf-8"))
            tmp_path.replace(self.path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def known_keys(self) -> set[str]:
        """All historical keys (including failed/pending). Prefer verified_keys() for dedupe."""
        return {dedupe_key_from_row(row) for row in self.read_all()}

    def verified_keys(self) -> set[str]:
        return {
            dedupe_key_from_row(row)
            for row in self.read_all()
            if str(row.get("sync_status") or "") == "verified"
        }

    def latest_record_by_key(self) -> dict[str, dict[str, Any]]:
        """Map dedupe_key → latest appended row for that key."""
        latest: dict[str, dict[str, Any]] = {}
        for row in self.read_all():
            latest[dedupe_key_from_row(row)] = row
        return latest

    def retryable_records(self) -> list[dict[str, Any]]:
        """Latest pending/failed rows whose keys are not yet verified."""
        verified = self.verified_keys()
        latest = self.latest_record_by_key()
        retryable: list[dict[str, Any]] = []
        for key, row in latest.items():
            if key in verified:
                continue
            status = str(row.get("sync_status") or "")
            if status in {"pending", "failed"}:
                retryable.append(row)
        return retryable
