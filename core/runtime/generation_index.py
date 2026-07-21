#!/usr/bin/env python3
"""Append-only generation index for Package 4.7 snapshot discovery."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .generation_evidence_ledger import dedupe_key_from_row, utc_now


GENERATION_INDEX_NAME = "generation_index.jsonl"


@dataclass
class GenerationIndexRecord:
    generation_id: str
    dedupe_key: str
    prompt_id: str
    output_node_id: str
    project_id: str = ""
    project_slug: str = ""
    capability: str = ""
    created_timestamp: str = ""
    canonical_output_path: str = ""
    snapshot_root: str = ""
    snapshot_status: str = "snapshot_pending"
    image_sha256: str = ""
    drive_filename: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GenerationIndex:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: GenerationIndexRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), sort_keys=True, ensure_ascii=False) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=".genidx_", suffix=".tmp", dir=str(self.path.parent))
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
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def latest_by_generation_id(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self.read_all():
            gid = str(row.get("generation_id") or "")
            if gid:
                latest[gid] = row
        return latest

    def latest_by_dedupe_key(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self.read_all():
            key = str(row.get("dedupe_key") or "")
            if key:
                latest[key] = row
        return latest

    def generation_id_for_dedupe_key(self, dedupe_key: str) -> str:
        row = self.latest_by_dedupe_key().get(dedupe_key)
        if row:
            return str(row.get("generation_id") or "")
        return ""

    def lookup_by_generation_id(self, generation_id: str) -> dict[str, Any] | None:
        """Return the latest index row for a generation ID.

        Accepts canonical ``gen_<uuid>`` or bare UUID; normalizes before lookup.
        Raises InvalidGenerationIdError for malformed IDs.
        """
        from .generation_identity import normalize_generation_id

        canonical = normalize_generation_id(generation_id)
        return self.latest_by_generation_id().get(canonical)


def rebuild_index_from_sources(
    *,
    evidence_path: Path,
    drive_root: Path,
    apply: bool = False,
) -> dict[str, Any]:
    """Rebuild generation index from evidence rows and on-disk manifests."""
    from .generation_snapshot import (
        global_generations_root,
        is_snapshot_complete,
        project_generations_root,
    )

    evidence_rows = []
    if evidence_path.is_file():
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    evidence_rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    latest_evidence: dict[str, dict[str, Any]] = {}
    for row in evidence_rows:
        latest_evidence[dedupe_key_from_row(row)] = row

    records: list[GenerationIndexRecord] = []
    seen_ids: set[str] = set()
    for key, row in latest_evidence.items():
        if str(row.get("sync_status") or "") != "verified":
            continue
        gid = str(row.get("generation_id") or "")
        snapshot_root = str(row.get("snapshot_root") or "")
        if not gid:
            continue
        if gid in seen_ids:
            continue
        seen_ids.add(gid)
        status = str(row.get("snapshot_status") or "snapshot_pending")
        if snapshot_root and is_snapshot_complete(Path(snapshot_root)):
            status = "snapshot_complete"
        records.append(
            GenerationIndexRecord(
                generation_id=gid,
                dedupe_key=key,
                prompt_id=str(row.get("prompt_id") or ""),
                output_node_id=str(row.get("output_node_id") or ""),
                project_id=str(row.get("project_id") or ""),
                project_slug=_slug_from_path(str(row.get("project_output_path") or "")),
                capability=str(row.get("capability") or ""),
                created_timestamp=str(
                    row.get("synchronized_timestamp") or row.get("created_timestamp") or ""
                ),
                canonical_output_path=str(row.get("drive_path") or ""),
                snapshot_root=snapshot_root,
                snapshot_status=status,
                image_sha256=str(row.get("drive_sha256") or row.get("local_sha256") or ""),
                drive_filename=str(row.get("drive_filename") or ""),
            )
        )

    # Discover complete snapshots on disk not yet in evidence.
    for root in (global_generations_root(drive_root),):
        if root.is_dir():
            for child in sorted(root.iterdir()):
                if child.is_dir() and is_snapshot_complete(child):
                    gid = child.name
                    if gid in seen_ids:
                        continue
                    seen_ids.add(gid)
                    records.append(
                        GenerationIndexRecord(
                            generation_id=gid,
                            dedupe_key="",
                            prompt_id="",
                            output_node_id="",
                            snapshot_root=str(child),
                            snapshot_status="snapshot_complete",
                            created_timestamp=utc_now(),
                        )
                    )

    projects_root = drive_root / "projects"
    if projects_root.is_dir():
        for project_dir in sorted(projects_root.iterdir()):
            if not project_dir.is_dir():
                continue
            gen_root = project_generations_root(drive_root, project_dir.name)
            if not gen_root.is_dir():
                continue
            for child in sorted(gen_root.iterdir()):
                if child.is_dir() and is_snapshot_complete(child):
                    gid = child.name
                    if gid in seen_ids:
                        continue
                    seen_ids.add(gid)
                    records.append(
                        GenerationIndexRecord(
                            generation_id=gid,
                            dedupe_key="",
                            prompt_id="",
                            output_node_id="",
                            project_slug=project_dir.name,
                            snapshot_root=str(child),
                            snapshot_status="snapshot_complete",
                            created_timestamp=utc_now(),
                        )
                    )

    result = {
        "apply": apply,
        "records": len(records),
        "entries": [r.to_dict() for r in records],
    }
    if apply:
        index = GenerationIndex(evidence_path.parent / GENERATION_INDEX_NAME)
        if index.path.is_file():
            backup = index.path.with_suffix(".jsonl.bak")
            backup.write_bytes(index.path.read_bytes())
        else:
            backup = None
        # Rewrite atomically from scratch.
        fd, tmp_name = tempfile.mkstemp(prefix=".genidx_rebuild_", suffix=".tmp", dir=str(index.path.parent))
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            lines = [json.dumps(r.to_dict(), sort_keys=True, ensure_ascii=False) + "\n" for r in records]
            tmp_path.write_text("".join(lines), encoding="utf-8")
            tmp_path.replace(index.path)
        finally:
            if tmp_path.exists() and not index.path.is_file():
                tmp_path.unlink(missing_ok=True)
        result["backup"] = str(backup) if backup and backup.is_file() else ""
    return result


def _slug_from_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    marker = "/projects/"
    if marker not in normalized:
        return ""
    tail = normalized.split(marker, 1)[1]
    return tail.split("/", 1)[0] if tail else ""
