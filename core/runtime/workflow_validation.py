#!/usr/bin/env python3
"""Reusable ComfyUI workflow validation helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BASE_TXT2IMG_WORKFLOW_ID = "base_txt2img"
BASE_TXT2IMG_REQUIRED_NODE_TYPES = frozenset(
    {
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "EmptyLatentImage",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    }
)
BASE_TXT2IMG_NODE_COUNT = 7


@dataclass
class WorkflowValidationResult:
    workflow_id: str
    path: str
    valid: bool
    reasons: list[str] = field(default_factory=list)
    node_count: int = 0
    present_node_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_node_record(node: Any, index: int) -> list[str]:
    issues: list[str] = []
    if not isinstance(node, dict):
        issues.append(f"Node at index {index} is not an object.")
        return issues
    node_type = node.get("type")
    if not isinstance(node_type, str) or not node_type.strip():
        issues.append(f"Node at index {index} is missing a valid type.")
    if "id" not in node:
        issues.append(f"Node at index {index} is missing id.")
    return issues


def validate_base_txt2img_workflow(path: Path) -> WorkflowValidationResult:
    result = WorkflowValidationResult(
        workflow_id=BASE_TXT2IMG_WORKFLOW_ID,
        path=str(path),
        valid=False,
    )

    if not path.is_file():
        result.reasons.append(f"Workflow file missing: {path}")
        return result

    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        result.reasons.append(f"Invalid workflow JSON: {exc}")
        return result
    except OSError as exc:
        result.reasons.append(f"Unable to read workflow file: {exc}")
        return result

    if not isinstance(data, dict):
        result.reasons.append("Workflow root must be a JSON object.")
        return result

    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        result.reasons.append("Workflow is missing a top-level nodes list.")
        return result

    result.node_count = len(nodes)
    if result.node_count != BASE_TXT2IMG_NODE_COUNT:
        result.reasons.append(
            f"Workflow must contain {BASE_TXT2IMG_NODE_COUNT} nodes; found {result.node_count}."
        )

    node_types: list[str] = []
    for index, node in enumerate(nodes):
        result.reasons.extend(_validate_node_record(node, index))
        if isinstance(node, dict) and isinstance(node.get("type"), str):
            node_types.append(node["type"])

    result.present_node_types = sorted(set(node_types))
    missing_types = sorted(BASE_TXT2IMG_REQUIRED_NODE_TYPES - set(node_types))
    if missing_types:
        result.reasons.append(
            f"Workflow missing required node types: {', '.join(missing_types)}"
        )

    clip_encode_count = node_types.count("CLIPTextEncode")
    if clip_encode_count < 2:
        result.reasons.append(
            "Workflow must include two CLIPTextEncode nodes for positive and negative prompts."
        )

    result.valid = not result.reasons
    return result


def validate_workflow(workflow_id: str, path: Path) -> WorkflowValidationResult:
    if workflow_id == BASE_TXT2IMG_WORKFLOW_ID:
        return validate_base_txt2img_workflow(path)

    result = WorkflowValidationResult(workflow_id=workflow_id, path=str(path), valid=False)
    if not path.is_file():
        result.reasons.append(f"Workflow file missing: {path}")
        return result
    result.valid = True
    return result
