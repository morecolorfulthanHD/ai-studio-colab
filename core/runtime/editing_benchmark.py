#!/usr/bin/env python3
"""Editing benchmark records and human-review rubric (no invented perceptual scores)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HUMAN_REVIEW_RUBRIC = [
    "instruction_adherence",
    "masked_region_quality",
    "preservation_outside_mask",
    "seam_blend_quality",
    "geometry_consistency",
    "photographic_realism",
    "unacceptable_artifacts",
]


@dataclass
class EditingBenchmarkRecord:
    candidate_model: str
    workflow: str
    task: str
    prompt: str
    source_hash: str = ""
    mask_hash: str = ""
    seed: Any = None
    dimensions: dict[str, int] | None = None
    execution_time_seconds: float | None = None
    peak_vram_mb: float | None = None
    success: bool | None = None
    output_path: str = ""
    drive_sync_status: str = "unknown"
    evidence_status: str = "unknown"
    human_review: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["human_review_rubric_keys"] = list(HUMAN_REVIEW_RUBRIC)
        return payload


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def append_benchmark_record(ledger_path: Path, record: EditingBenchmarkRecord) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if not record.created_at:
        record.created_at = utc_now()
    line = json.dumps(record.to_dict(), ensure_ascii=False)
    tmp = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    existing = ledger_path.read_text(encoding="utf-8") if ledger_path.is_file() else ""
    tmp.write_text(existing + line + "\n", encoding="utf-8")
    tmp.replace(ledger_path)


def load_benchmark_records(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def format_benchmark_report(records: list[dict[str, Any]]) -> str:
    lines = [
        "AI Studio — Editing Benchmark Report",
        "=" * 40,
        f"Records: {len(records)}",
        "Note: human-review fields are qualitative; no automated perceptual scores are invented.",
        "",
    ]
    for row in records:
        lines.append(
            f"- {row.get('candidate_model')} | {row.get('task')} | success={row.get('success')} | "
            f"sync={row.get('drive_sync_status')} | evidence={row.get('evidence_status')}"
        )
        if row.get("prompt"):
            lines.append(f"  prompt: {row['prompt']}")
        if row.get("output_path"):
            lines.append(f"  output: {row['output_path']}")
    if not records:
        lines.append("No benchmark records found.")
    return "\n".join(lines)


def empty_human_review_template() -> dict[str, str]:
    return {key: "pending_human_review" for key in HUMAN_REVIEW_RUBRIC}
