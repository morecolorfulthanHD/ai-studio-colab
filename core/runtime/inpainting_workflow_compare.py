#!/usr/bin/env python3
"""Compare canonical and reference inpainting workflow graphs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .workflow_validation import WorkflowValidationResult, _parse_workflow_graph

CANONICAL_INPAINTING_PATH = "workflows/base/inpainting/workflow.json"
REFERENCE_INPAINTING_PATH = "workflows/reference/inpainting_official/workflow.json"
REFERENCE_PROVENANCE_PATH = "workflows/reference/inpainting_official/provenance.json"

MASK_SOURCE_EMBEDDED_ALPHA = "embedded_alpha_from_load_image"
MASK_SOURCE_SEPARATE_LOAD_IMAGE_MASK = "separate_load_image_mask"

MATERIAL_FIELDS = frozenset(
    {
        "checkpoint",
        "mask_source_type",
        "mask_source_node_type",
        "mask_source_channel",
        "source_image_provides_mask",
        "separate_mask_file_required",
        "mask_architecture",
        "mask_channel",
        "mask_color",
        "grow_mask_by",
        "denoise",
        "sampler_name",
        "scheduler",
        "steps",
        "cfg",
        "node_types",
        "links",
        "input_sockets",
        "output_sockets",
    }
)


@dataclass
class WorkflowDifference:
    field: str
    canonical: Any
    reference: Any
    severity: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InpaintingWorkflowComparison:
    canonical_path: str
    reference_path: str
    overall: str
    differences: list[WorkflowDifference] = field(default_factory=list)
    canonical_mask_architecture: dict[str, Any] = field(default_factory=dict)
    reference_mask_architecture: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_path": self.canonical_path,
            "reference_path": self.reference_path,
            "overall": self.overall,
            "canonical_mask_architecture": self.canonical_mask_architecture,
            "reference_mask_architecture": self.reference_mask_architecture,
            "differences": [item.to_dict() for item in self.differences],
        }


def _load_workflow(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _node_by_type(data: dict[str, Any], node_type: str) -> dict[str, Any] | None:
    matches = [node for node in data.get("nodes", []) if node.get("type") == node_type]
    if len(matches) == 1:
        return matches[0]
    return matches[0] if matches else None


def _nodes_by_type(data: dict[str, Any], node_type: str) -> list[dict[str, Any]]:
    return [node for node in data.get("nodes", []) if node.get("type") == node_type]


def _prompt_nodes(data: dict[str, Any]) -> list[str]:
    return [
        str(node.get("widgets_values", [""])[0])
        for node in data.get("nodes", [])
        if node.get("type") == "CLIPTextEncode"
    ]


def _link_feeds_mask_from_load_image(data: dict[str, Any]) -> bool:
    """True when a LoadImage MASK output feeds VAEEncodeForInpaint.mask."""
    load_image_ids = {node.get("id") for node in _nodes_by_type(data, "LoadImage")}
    encode_ids = {node.get("id") for node in _nodes_by_type(data, "VAEEncodeForInpaint")}
    for link in data.get("links", []):
        if not isinstance(link, list) or len(link) < 5:
            continue
        _link_id, src_node, src_slot, dst_node, dst_slot = link[:5]
        if src_node in load_image_ids and src_slot == 1 and dst_node in encode_ids and dst_slot == 2:
            return True
    return False


def _extract_mask_architecture(data: dict[str, Any]) -> dict[str, Any]:
    has_load_image_mask = bool(_nodes_by_type(data, "LoadImageMask"))
    load_image_provides_mask = _link_feeds_mask_from_load_image(data)
    mask_node = _node_by_type(data, "LoadImageMask")
    mask_channel = None
    if mask_node:
        widgets = mask_node.get("widgets_values", [])
        if len(widgets) > 1:
            mask_channel = widgets[1]

    if load_image_provides_mask and not has_load_image_mask:
        mask_source_type = MASK_SOURCE_EMBEDDED_ALPHA
        mask_source_node_type = "LoadImage"
        source_image_provides_mask = True
        separate_mask_file_required = False
        channel = "alpha"
    elif has_load_image_mask:
        mask_source_type = MASK_SOURCE_SEPARATE_LOAD_IMAGE_MASK
        mask_source_node_type = "LoadImageMask"
        source_image_provides_mask = False
        separate_mask_file_required = True
        channel = mask_channel
    else:
        mask_source_type = "unknown"
        mask_source_node_type = None
        source_image_provides_mask = load_image_provides_mask
        separate_mask_file_required = has_load_image_mask
        channel = mask_channel

    return {
        "mask_source_type": mask_source_type,
        "mask_source_node_type": mask_source_node_type,
        "mask_source_channel": channel,
        "source_image_provides_mask": source_image_provides_mask,
        "separate_mask_file_required": separate_mask_file_required,
    }


def _mask_architecture_label(arch: dict[str, Any]) -> str:
    mask_type = arch.get("mask_source_type")
    if mask_type == MASK_SOURCE_SEPARATE_LOAD_IMAGE_MASK:
        channel = arch.get("mask_source_channel") or "unknown"
        return f"separate {channel}-channel mask"
    if mask_type == MASK_SOURCE_EMBEDDED_ALPHA:
        return "embedded alpha from LoadImage"
    return str(mask_type)


def _extract_profile(data: dict[str, Any]) -> dict[str, Any]:
    checkpoint = _node_by_type(data, "CheckpointLoaderSimple")
    mask = _node_by_type(data, "LoadImageMask")
    grow = _node_by_type(data, "VAEEncodeForInpaint")
    sampler = _node_by_type(data, "KSampler")
    mask_architecture = _extract_mask_architecture(data)

    checkpoint_name = None
    if checkpoint:
        widgets = checkpoint.get("widgets_values", [])
        checkpoint_name = widgets[0] if widgets else None

    mask_channel = mask_architecture.get("mask_source_channel")
    mask_color = None
    if mask:
        widgets = mask.get("widgets_values", [])
        if len(widgets) > 2:
            mask_color = widgets[2]

    grow_mask_by = None
    if grow:
        widgets = grow.get("widgets_values")
        if isinstance(widgets, list) and widgets:
            grow_mask_by = widgets[0]

    sampler_values: dict[str, Any] = {}
    if sampler:
        widgets = sampler.get("widgets_values", [])
        if len(widgets) >= 7:
            sampler_values = {
                "seed": widgets[0],
                "control_after_generate": widgets[1],
                "steps": widgets[2],
                "cfg": widgets[3],
                "sampler_name": widgets[4],
                "scheduler": widgets[5],
                "denoise": widgets[6],
            }

    validation = WorkflowValidationResult(workflow_id="compare", path="<memory>", valid=True)
    graph = _parse_workflow_graph(data, validation)
    links: list[tuple[int, int, int, int, str]] = []
    input_sockets: list[tuple[int, int, int | None]] = []
    output_sockets: list[tuple[int, int, list[int] | None]] = []
    if graph is not None:
        links = sorted(
            (link.src_node, link.src_slot, link.dst_node, link.dst_slot, link.link_type)
            for link in graph.links
        )
        for node_id, node in sorted(graph.nodes_by_id.items()):
            for index, node_input in enumerate(node.get("inputs", [])):
                if isinstance(node_input, dict):
                    input_sockets.append((node_id, index, node_input.get("link")))
            for index, node_output in enumerate(node.get("outputs", [])):
                if isinstance(node_output, dict):
                    output_sockets.append((node_id, index, node_output.get("links")))

    node_types = sorted(node.get("type") for node in data.get("nodes", []) if isinstance(node, dict))

    return {
        "checkpoint": checkpoint_name,
        "mask_source_type": mask_architecture["mask_source_type"],
        "mask_source_node_type": mask_architecture["mask_source_node_type"],
        "mask_source_channel": mask_architecture["mask_source_channel"],
        "source_image_provides_mask": mask_architecture["source_image_provides_mask"],
        "separate_mask_file_required": mask_architecture["separate_mask_file_required"],
        "mask_architecture": _mask_architecture_label(mask_architecture),
        "mask_channel": mask_channel,
        "mask_color": mask_color,
        "grow_mask_by": grow_mask_by,
        "prompts": _prompt_nodes(data),
        "denoise": sampler_values.get("denoise"),
        "sampler_name": sampler_values.get("sampler_name"),
        "scheduler": sampler_values.get("scheduler"),
        "steps": sampler_values.get("steps"),
        "cfg": sampler_values.get("cfg"),
        "node_types": node_types,
        "links": links,
        "input_sockets": input_sockets,
        "output_sockets": output_sockets,
        "_mask_architecture": mask_architecture,
    }


def compare_inpainting_workflows(
    canonical_path: Path,
    reference_path: Path,
) -> InpaintingWorkflowComparison:
    canonical_data = _load_workflow(canonical_path)
    reference_data = _load_workflow(reference_path)
    canonical_profile = _extract_profile(canonical_data)
    reference_profile = _extract_profile(reference_data)
    canonical_arch = canonical_profile.pop("_mask_architecture")
    reference_arch = reference_profile.pop("_mask_architecture")

    differences: list[WorkflowDifference] = []
    all_keys = sorted(set(canonical_profile) | set(reference_profile))
    for key in all_keys:
        canonical_value = canonical_profile.get(key)
        reference_value = reference_profile.get(key)
        if canonical_value == reference_value:
            continue
        severity = "cosmetic" if key in {"prompts"} else "material"
        if key in MATERIAL_FIELDS:
            severity = "material"
        differences.append(
            WorkflowDifference(
                field=key,
                canonical=canonical_value,
                reference=reference_value,
                severity=severity,
            )
        )

    material = [item for item in differences if item.severity == "material"]
    if not differences:
        overall = "identical"
    elif not material:
        overall = "equivalent"
    else:
        overall = "materially_different"

    return InpaintingWorkflowComparison(
        canonical_path=str(canonical_path),
        reference_path=str(reference_path),
        overall=overall,
        differences=differences,
        canonical_mask_architecture=canonical_arch,
        reference_mask_architecture=reference_arch,
    )


def format_comparison_summary(comparison: InpaintingWorkflowComparison) -> str:
    lines = [
        "AI Studio — Inpainting Workflow Comparison",
        "=" * 40,
        f"Canonical: {comparison.canonical_path}",
        f"Reference: {comparison.reference_path}",
        f"Overall:   {comparison.overall}",
    ]
    if comparison.canonical_mask_architecture or comparison.reference_mask_architecture:
        lines.append("\nMask architectures:")
        lines.append(
            f"  - canonical: {_mask_architecture_label(comparison.canonical_mask_architecture)}"
        )
        lines.append(
            f"  - reference: {_mask_architecture_label(comparison.reference_mask_architecture)}"
        )
    material = [item for item in comparison.differences if item.severity == "material"]
    cosmetic = [item for item in comparison.differences if item.severity != "material"]
    if material:
        lines.append("\nMaterial differences:")
        for item in material:
            if item.field == "mask_architecture":
                lines.append(
                    "  - mask source architecture:"
                    f"\n      canonical = {item.canonical}"
                    f"\n      reference = {item.reference}"
                )
            else:
                lines.append(
                    f"  - {item.field}: canonical={item.canonical!r} reference={item.reference!r}"
                )
    if cosmetic:
        lines.append("\nCosmetic differences:")
        for item in cosmetic:
            lines.append(f"  - {item.field}: canonical={item.canonical!r} reference={item.reference!r}")
    if not comparison.differences:
        lines.append("\nNo differences detected.")
    return "\n".join(lines)


def load_reference_provenance(repo_root: Path) -> dict[str, Any]:
    path = repo_root / REFERENCE_PROVENANCE_PATH
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)
