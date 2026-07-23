#!/usr/bin/env python3
"""Append-only index for workflow library preparations (Package 4.8)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .generation_evidence_ledger import utc_now
from .preparation_identity import InvalidPreparationIdError, normalize_preparation_id

WORKFLOW_PREPARATIONS_NAME = "workflow_preparations.jsonl"


def preparations_log_path(drive_root: Path) -> Path:
    return drive_root / "logs" / WORKFLOW_PREPARATIONS_NAME


def append_preparation_record(log_path: Path, record: dict[str, Any]) -> None:
    """Append one preparation record to workflow_preparations.jsonl."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault("recorded_timestamp", utc_now())
    line = json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".wfprep_", suffix=".tmp", dir=str(log_path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        existing = log_path.read_bytes() if log_path.is_file() else b""
        tmp_path.write_bytes(existing + line.encode("utf-8"))
        tmp_path.replace(log_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def read_preparation_records(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
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


def find_by_preparation_id(log_path: Path, preparation_id: str) -> dict[str, Any] | None:
    """Return latest record matching normalized preparation_id."""
    try:
        canonical = normalize_preparation_id(preparation_id)
    except InvalidPreparationIdError:
        return None
    latest: dict[str, Any] | None = None
    for row in read_preparation_records(log_path):
        row_id = str(row.get("preparation_id") or "")
        if not row_id:
            continue
        try:
            if normalize_preparation_id(row_id) == canonical:
                latest = row
        except InvalidPreparationIdError:
            continue
    return latest
