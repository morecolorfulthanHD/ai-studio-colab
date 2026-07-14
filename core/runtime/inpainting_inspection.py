#!/usr/bin/env python3
"""Extract inspection details from prepared inpainting workflows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .mask_diagnostics import MaskDiagnosticReport, analyze_mask


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _node_widgets(data: dict[str, Any], node_type: str) -> list[Any]:
    for node in data.get("nodes", []):
        if node.get("type") == node_type:
            widgets = node.get("widgets_values", [])
            if isinstance(widgets, list):
                return widgets
    return []


def inspect_prepared_inpainting_workflow(
    prepared_data: dict[str, Any],
    *,
    mask_path: Path | None = None,
    source_path: Path | None = None,
    canonical_path: Path | None = None,
) -> dict[str, Any]:
    checkpoint = _node_widgets(prepared_data, "CheckpointLoaderSimple")
    mask_widgets = _node_widgets(prepared_data, "LoadImageMask")
    grow_widgets = _node_widgets(prepared_data, "VAEEncodeForInpaint")
    sampler_widgets = _node_widgets(prepared_data, "KSampler")

    mask_channel = mask_widgets[1] if len(mask_widgets) > 1 else None
    staged_mask_filename = mask_widgets[0] if mask_widgets else None
    grow_mask_by = grow_widgets[0] if grow_widgets else None

    sampler: dict[str, Any] = {}
    if len(sampler_widgets) >= 7:
        sampler = {
            "seed": sampler_widgets[0],
            "control_after_generate": sampler_widgets[1],
            "steps": sampler_widgets[2],
            "cfg": sampler_widgets[3],
            "sampler_name": sampler_widgets[4],
            "scheduler": sampler_widgets[5],
            "denoise": sampler_widgets[6],
        }

    inspection: dict[str, Any] = {
        "workflow_id": "base_inpainting",
        "checkpoint": checkpoint[0] if checkpoint else None,
        "mask_channel": mask_channel,
        "staged_mask_filename": staged_mask_filename,
        "grow_mask_by": grow_mask_by,
        "sampler": sampler,
    }

    if canonical_path is not None and canonical_path.is_file():
        inspection["workflow_hash"] = _sha256_file(canonical_path)
    else:
        inspection["workflow_hash"] = hashlib.sha256(
            json.dumps(prepared_data, sort_keys=True).encode("utf-8")
        ).hexdigest()

    if source_path is not None and source_path.is_file():
        inspection["source_filename"] = source_path.name
        inspection["source_hash"] = _sha256_file(source_path)
    if mask_path is not None and mask_path.is_file():
        inspection["mask_filename"] = mask_path.name
        inspection["mask_hash"] = _sha256_file(mask_path)
        inspection["staged_mask_path"] = str(mask_path)
        channel = str(mask_channel or "red")
        mask_report = analyze_mask(mask_path, channel=channel)
        inspection["mask_statistics"] = mask_report.to_dict()

    return inspection


def format_inpainting_inspection(inspection: dict[str, Any]) -> str:
    lines = [
        "Inpainting inspection:",
        f"  checkpoint: {inspection.get('checkpoint')}",
        f"  mask channel: {inspection.get('mask_channel')}",
        f"  staged mask filename: {inspection.get('staged_mask_filename')}",
        f"  grow_mask_by: {inspection.get('grow_mask_by')}",
    ]
    sampler = inspection.get("sampler", {})
    if sampler:
        lines.extend(
            [
                f"  denoise: {sampler.get('denoise')}",
                f"  sampler: {sampler.get('sampler_name')}",
                f"  scheduler: {sampler.get('scheduler')}",
                f"  steps: {sampler.get('steps')}",
                f"  CFG: {sampler.get('cfg')}",
            ]
        )
    if inspection.get("staged_mask_path"):
        lines.append(f"  staged mask path: {inspection.get('staged_mask_path')}")
    if inspection.get("source_filename"):
        lines.append(f"  source filename: {inspection.get('source_filename')}")
    if inspection.get("mask_filename"):
        lines.append(f"  mask filename: {inspection.get('mask_filename')}")
    if inspection.get("workflow_hash"):
        lines.append(f"  workflow hash: {inspection.get('workflow_hash')}")
    if inspection.get("source_hash"):
        lines.append(f"  source hash: {inspection.get('source_hash')}")
    if inspection.get("mask_hash"):
        lines.append(f"  mask hash: {inspection.get('mask_hash')}")

    stats = inspection.get("mask_statistics")
    if isinstance(stats, dict):
        bbox = stats.get("bounding_box")
        bbox_text = "none"
        if isinstance(bbox, dict):
            bbox_text = f"{bbox.get('x1')},{bbox.get('y1')},{bbox.get('x2')},{bbox.get('y2')}"
        lines.extend(
            [
                f"  masked percent: {stats.get('masked_percent')}%",
                f"  mask bounding box: {bbox_text}",
                f"  mask classification: {stats.get('classification')}",
            ]
        )
    return "\n".join(lines)
