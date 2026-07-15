#!/usr/bin/env python3
"""Read and summarize generation evidence (legacy Package 4.4 and enriched Package 4.5 rows)."""

from __future__ import annotations

from dataclasses import dataclass, field
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


def list_recent_generations(
    path: Path,
    *,
    limit: int = 20,
    verified_only: bool = False,
) -> list[dict[str, Any]]:
    rows = EvidenceLedger(path).read_all()
    if verified_only:
        rows = [row for row in rows if str(row.get("sync_status") or "") == "verified"]
    rows = list(reversed(rows))
    return rows[:limit]


def find_generation_by_prompt_id(path: Path, prompt_id: str) -> list[dict[str, Any]]:
    return [row for row in EvidenceLedger(path).read_all() if str(row.get("prompt_id") or "") == prompt_id]
