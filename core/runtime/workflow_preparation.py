#!/usr/bin/env python3
"""Prepare runtime workflow copies with user-selected inputs (read-only on canonical JSON)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .input_staging import stage_inputs_batch
from .input_utils import validate_input_path, validate_matching_dimensions
from .output_sync import utc_collision_timestamp
from .workflow_validation import (
    BASE_IMG2IMG_WORKFLOW_ID,
    BASE_INPAINTING_WORKFLOW_ID,
    BASE_OUTPAINTING_WORKFLOW_ID,
    INPAINTING_CANONICAL_MASK_CHANNEL,
    validate_workflow,
    validate_workflow_from_data,
)

WORKFLOW_ALIASES = {
    "img2img": BASE_IMG2IMG_WORKFLOW_ID,
    "inpainting": BASE_INPAINTING_WORKFLOW_ID,
    "outpainting": BASE_OUTPAINTING_WORKFLOW_ID,
}

CANONICAL_WORKFLOW_PATHS = {
    BASE_IMG2IMG_WORKFLOW_ID: "workflows/base/img2img/workflow.json",
    BASE_INPAINTING_WORKFLOW_ID: "workflows/base/inpainting/workflow.json",
    BASE_OUTPAINTING_WORKFLOW_ID: "workflows/base/outpainting/workflow.json",
}


@dataclass
class WorkflowPreparationResult:
    workflow: str
    workflow_id: str
    canonical_path: str
    prepared_path: str = ""
    input_image: str = ""
    mask_image: str = ""
    staged_input_path: str = ""
    staged_mask_path: str = ""
    staged_input_filename: str = ""
    staged_mask_filename: str = ""
    comfyui_input_dir: str = ""
    expansion: dict[str, int] = field(default_factory=dict)
    dry_run: bool = False
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_workflow_id(workflow: str) -> str:
    workflow_id = WORKFLOW_ALIASES.get(workflow, workflow)
    if workflow_id not in CANONICAL_WORKFLOW_PATHS:
        raise KeyError(f"Unknown workflow: {workflow}")
    return workflow_id


def _patch_load_image_mask_widgets(node: dict[str, Any], staged_mask_filename: str) -> None:
    widgets = node.get("widgets_values")
    if isinstance(widgets, list) and len(widgets) >= 3:
        channel = widgets[1] if isinstance(widgets[1], str) else INPAINTING_CANONICAL_MASK_CHANNEL
        mask_color = widgets[2] if isinstance(widgets[2], str) else "white"
    else:
        channel = INPAINTING_CANONICAL_MASK_CHANNEL
        mask_color = "white"
    node["widgets_values"] = [staged_mask_filename, channel, mask_color]


def _patch_nodes(
    data: dict[str, Any],
    *,
    staged_input_filename: str,
    staged_mask_filename: str | None,
    expansion: dict[str, int] | None,
) -> None:
    nodes = data.get("nodes", [])
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        if node_type == "LoadImage":
            node["widgets_values"] = [staged_input_filename, "image"]
        elif node_type == "LoadImageMask" and staged_mask_filename is not None:
            _patch_load_image_mask_widgets(node, staged_mask_filename)
        elif node_type == "ImagePadForOutpaint" and expansion is not None:
            node["widgets_values"] = [
                expansion.get("left", 0),
                expansion.get("top", 0),
                expansion.get("right", 0),
                expansion.get("bottom", 0),
                24,
            ]


def _runtime_output_path(runtime_dir: Path, workflow_id: str, timestamp: str) -> Path:
    candidate = runtime_dir / f"{workflow_id}_{timestamp}.json"
    suffix = 1
    while candidate.exists():
        candidate = runtime_dir / f"{workflow_id}_{timestamp}.{suffix}.json"
        suffix += 1
    return candidate


def _append_execution_sequence(result: WorkflowPreparationResult) -> None:
    result.messages.append("Execution sequence:")
    result.messages.append(f"  1. Persistent source: {result.input_image}")
    if result.mask_image:
        result.messages.append(f"  2. Persistent mask:   {result.mask_image}")
    if result.staged_input_path:
        label = "  3. Staged source:" if result.mask_image else "  2. Staged source:"
        result.messages.append(f"{label} {result.staged_input_path}")
    if result.staged_mask_path:
        result.messages.append(f"  4. Staged mask:     {result.staged_mask_path}")
    prepared_label = "  5. Prepared workflow:" if result.mask_image else "  3. Prepared workflow:"
    if result.prepared_path:
        result.messages.append(f"{prepared_label} {result.prepared_path}")
        result.messages.append(
            "  Import the prepared workflow JSON in ComfyUI (Workflow → Load), then queue the prompt."
        )


def prepare_workflow(
    repo_root: Path,
    runtime_dir: Path,
    *,
    comfyui_input_dir: Path,
    workflow: str,
    input_path: Path,
    mask_path: Path | None = None,
    expansion: dict[str, int] | None = None,
    dry_run: bool = False,
    operation_timestamp: str | None = None,
) -> WorkflowPreparationResult:
    workflow_id = _resolve_workflow_id(workflow)
    canonical_rel = CANONICAL_WORKFLOW_PATHS[workflow_id]
    canonical_path = repo_root / canonical_rel

    result = WorkflowPreparationResult(
        workflow=workflow,
        workflow_id=workflow_id,
        canonical_path=str(canonical_path),
        input_image=str(input_path),
        comfyui_input_dir=str(comfyui_input_dir),
        dry_run=dry_run,
    )
    if mask_path is not None:
        result.mask_image = str(mask_path)
    if expansion is not None:
        result.expansion = dict(expansion)

    validation = validate_workflow(workflow_id, canonical_path)
    if not validation.valid:
        result.errors.append(validation.reasons[0] if validation.reasons else "Workflow validation failed.")
        return result

    ok, error = validate_input_path(input_path)
    if not ok and error:
        result.errors.append(error)
        return result

    if workflow_id == BASE_INPAINTING_WORKFLOW_ID:
        if mask_path is None:
            result.errors.append("Inpainting preparation requires --mask.")
            return result
        mask_ok, mask_error = validate_input_path(mask_path)
        if not mask_ok and mask_error:
            result.errors.append(mask_error)
            return result
        dims_ok, dims_error, dims_warning = validate_matching_dimensions(input_path, mask_path)
        if dims_warning:
            result.messages.append(dims_warning)
        if not dims_ok and dims_error:
            result.errors.append(dims_error)
            return result

    if workflow_id == BASE_OUTPAINTING_WORKFLOW_ID:
        if expansion is None:
            expansion = {"left": 0, "top": 0, "right": 0, "bottom": 0}
            result.expansion = dict(expansion)
        for side, value in expansion.items():
            if value < 0:
                result.errors.append(f"Expansion value for {side} must be non-negative; got {value}.")
        if all(expansion.get(side, 0) == 0 for side in ("left", "right", "top", "bottom")):
            result.errors.append("Outpainting requires at least one expansion side greater than zero.")
        if result.errors:
            return result

    operation_ts = operation_timestamp or utc_collision_timestamp()
    staged_input, staged_mask = stage_inputs_batch(
        input_path,
        comfyui_input_dir,
        mask=mask_path,
        dry_run=dry_run,
        timestamp=operation_ts,
    )
    result.staged_input_path = str(staged_input.staged_path)
    result.staged_input_filename = staged_input.staged_filename
    result.messages.append(staged_input.message)

    staged_mask_filename: str | None = None
    if staged_mask is not None:
        result.staged_mask_path = str(staged_mask.staged_path)
        staged_mask_filename = staged_mask.staged_filename
        result.staged_mask_filename = staged_mask_filename
        if staged_mask.staged_path != staged_input.staged_path:
            result.messages.append(staged_mask.message)
        elif staged_mask.message != staged_input.message:
            result.messages.append(
                f"Mask shares staged file with source in ComfyUI/input: {staged_mask_filename}"
            )

    with canonical_path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    _patch_nodes(
        data,
        staged_input_filename=staged_input.staged_filename,
        staged_mask_filename=staged_mask_filename,
        expansion=expansion,
    )

    patched_validation = validate_workflow_from_data(workflow_id, data)
    if not patched_validation.valid:
        result.errors.append(
            patched_validation.reasons[0]
            if patched_validation.reasons
            else "Prepared workflow validation failed."
        )
        return result

    prepared_path = _runtime_output_path(runtime_dir, workflow_id, operation_ts)
    result.prepared_path = str(prepared_path)
    result.messages.append(f"Canonical workflow (unchanged): {canonical_path}")
    if dry_run:
        result.messages.append("Dry run only — no ComfyUI input copies and no prepared workflow written.")
        _append_execution_sequence(result)
        return result

    runtime_dir.mkdir(parents=True, exist_ok=True)
    with prepared_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    result.messages.append("Prepared workflow written to ephemeral runtime directory.")
    _append_execution_sequence(result)
    return result
