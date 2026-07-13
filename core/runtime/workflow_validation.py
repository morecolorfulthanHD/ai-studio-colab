#!/usr/bin/env python3
"""Reusable ComfyUI workflow validation helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

BASE_TXT2IMG_WORKFLOW_ID = "base_txt2img"
BASE_IMG2IMG_WORKFLOW_ID = "base_img2img"
BASE_INPAINTING_WORKFLOW_ID = "base_inpainting"
BASE_OUTPAINTING_WORKFLOW_ID = "base_outpainting"

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
BASE_IMG2IMG_REQUIRED_NODE_TYPES = frozenset(
    {
        "LoadImage",
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "VAEEncode",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    }
)
BASE_INPAINTING_REQUIRED_NODE_TYPES = frozenset(
    {
        "LoadImage",
        "LoadImageMask",
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "VAEEncodeForInpaint",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    }
)
BASE_OUTPAINTING_REQUIRED_NODE_TYPES = frozenset(
    {
        "LoadImage",
        "ImagePadForOutpaint",
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "VAEEncodeForInpaint",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    }
)

BASE_TXT2IMG_NODE_COUNT = 7
BASE_IMG2IMG_NODE_COUNT = 8
BASE_INPAINTING_NODE_COUNT = 9
BASE_OUTPAINTING_NODE_COUNT = 9

INPAINTING_CANONICAL_DENOISE = 1.0
OUTPAINTING_CANONICAL_DENOISE = 1.0
INPAINTING_CANONICAL_CHECKPOINT = "512-inpainting-ema.safetensors"
INPAINTING_CANONICAL_MASK_CHANNEL = "red"

WORKFLOW_OUTPUT_PREFIXES = {
    BASE_TXT2IMG_WORKFLOW_ID: "ai_studio_base_txt2img",
    BASE_IMG2IMG_WORKFLOW_ID: "ai_studio_base_img2img",
    BASE_INPAINTING_WORKFLOW_ID: "ai_studio_base_inpainting",
    BASE_OUTPAINTING_WORKFLOW_ID: "ai_studio_base_outpainting",
}


@dataclass
class ParsedLink:
    link_id: int
    src_node: int
    src_slot: int
    dst_node: int
    dst_slot: int
    link_type: str


@dataclass
class WorkflowGraph:
    nodes_by_id: dict[int, dict[str, Any]]
    links: list[ParsedLink]

    def node_ids_of_type(self, node_type: str) -> list[int]:
        return sorted(
            node_id
            for node_id, node in self.nodes_by_id.items()
            if node.get("type") == node_type
        )

    def has_link(self, src_node: int, src_slot: int, dst_node: int, dst_slot: int) -> bool:
        return any(
            link.src_node == src_node
            and link.src_slot == src_slot
            and link.dst_node == dst_node
            and link.dst_slot == dst_slot
            for link in self.links
        )

    def links_to_input(self, dst_node: int, dst_slot: int) -> list[ParsedLink]:
        return [link for link in self.links if link.dst_node == dst_node and link.dst_slot == dst_slot]


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


def _load_workflow_json(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.is_file():
        return None, [f"Workflow file missing: {path}"]
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        return None, [f"Invalid workflow JSON: {exc}"]
    except OSError as exc:
        return None, [f"Unable to read workflow file: {exc}"]
    if not isinstance(data, dict):
        return None, ["Workflow root must be a JSON object."]
    return data, []


def _collect_nodes(data: dict[str, Any], result: WorkflowValidationResult) -> list[str] | None:
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        result.reasons.append("Workflow is missing a top-level nodes list.")
        return None
    result.node_count = len(nodes)
    node_types: list[str] = []
    for index, node in enumerate(nodes):
        result.reasons.extend(_validate_node_record(node, index))
        if isinstance(node, dict) and isinstance(node.get("type"), str):
            node_types.append(node["type"])
    result.present_node_types = sorted(set(node_types))
    return node_types


def _require_node_types(
    result: WorkflowValidationResult,
    node_types: list[str],
    required_types: frozenset[str],
) -> None:
    missing_types = sorted(required_types - set(node_types))
    if missing_types:
        result.reasons.append(
            f"Workflow missing required node types: {', '.join(missing_types)}"
        )


def _require_clip_encode_count(result: WorkflowValidationResult, node_types: list[str], minimum: int = 2) -> None:
    if node_types.count("CLIPTextEncode") < minimum:
        result.reasons.append(
            "Workflow must include two CLIPTextEncode nodes for positive and negative prompts."
        )


def _require_save_prefix(
    data: dict[str, Any],
    result: WorkflowValidationResult,
    expected_prefix: str,
) -> None:
    nodes = data.get("nodes", [])
    save_nodes = [node for node in nodes if isinstance(node, dict) and node.get("type") == "SaveImage"]
    if not save_nodes:
        result.reasons.append("Workflow is missing a SaveImage node.")
        return
    widgets = save_nodes[0].get("widgets_values", [])
    if not widgets or widgets[0] != expected_prefix:
        result.reasons.append(
            f"SaveImage prefix must be {expected_prefix!r}; found {widgets[0] if widgets else 'none'}."
        )


def _parse_workflow_graph(data: dict[str, Any], result: WorkflowValidationResult) -> WorkflowGraph | None:
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return None

    nodes_by_id: dict[int, dict[str, Any]] = {}
    seen_ids: set[int] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, int):
            result.reasons.append(f"Node at index {index} has a non-integer id.")
            continue
        if node_id in seen_ids:
            result.reasons.append(f"Duplicate node id detected: {node_id}.")
        seen_ids.add(node_id)
        nodes_by_id[node_id] = node

    links_raw = data.get("links")
    if not isinstance(links_raw, list):
        result.reasons.append("Workflow is missing a top-level links list.")
        return None

    parsed_links: list[ParsedLink] = []
    links_by_id: dict[int, ParsedLink] = {}
    for index, link in enumerate(links_raw):
        if not isinstance(link, list) or len(link) < 6:
            result.reasons.append(f"Malformed link at index {index}.")
            continue
        link_id, src_node, src_slot, dst_node, dst_slot, link_type = link[:6]
        if not all(isinstance(value, int) for value in (link_id, src_node, src_slot, dst_node, dst_slot)):
            result.reasons.append(f"Malformed link at index {index}: node or slot ids must be integers.")
            continue
        if not isinstance(link_type, str):
            result.reasons.append(f"Malformed link at index {index}: link type must be a string.")
            continue
        if link_id in links_by_id:
            result.reasons.append(f"Duplicate link id detected: {link_id}.")
            continue
        if src_node not in nodes_by_id:
            result.reasons.append(f"Link {link_id} references unknown source node {src_node}.")
            continue
        if dst_node not in nodes_by_id:
            result.reasons.append(f"Link {link_id} references unknown destination node {dst_node}.")
            continue
        parsed = ParsedLink(
            link_id=link_id,
            src_node=src_node,
            src_slot=src_slot,
            dst_node=dst_node,
            dst_slot=dst_slot,
            link_type=link_type,
        )
        links_by_id[link_id] = parsed
        parsed_links.append(parsed)

    return WorkflowGraph(nodes_by_id=nodes_by_id, links=parsed_links)


def _single_node_id(graph: WorkflowGraph, result: WorkflowValidationResult, node_type: str) -> int | None:
    node_ids = graph.node_ids_of_type(node_type)
    if len(node_ids) != 1:
        result.reasons.append(f"Expected exactly one {node_type} node; found {len(node_ids)}.")
        return None
    return node_ids[0]


def _require_path(
    graph: WorkflowGraph,
    result: WorkflowValidationResult,
    *,
    src_type: str,
    src_slot: int,
    dst_type: str,
    dst_slot: int,
    description: str,
) -> None:
    src_id = _single_node_id(graph, result, src_type)
    dst_id = _single_node_id(graph, result, dst_type)
    if src_id is None or dst_id is None:
        return
    if not graph.has_link(src_id, src_slot, dst_id, dst_slot):
        result.reasons.append(f"Missing required path: {description}")


def _require_checkpoint_clip_to_encoders(graph: WorkflowGraph, result: WorkflowValidationResult) -> None:
    checkpoint_ids = graph.node_ids_of_type("CheckpointLoaderSimple")
    encoder_ids = graph.node_ids_of_type("CLIPTextEncode")
    if len(checkpoint_ids) != 1 or len(encoder_ids) < 2:
        return
    checkpoint_id = checkpoint_ids[0]
    connected = {
        link.dst_node
        for link in graph.links
        if link.src_node == checkpoint_id and link.src_slot == 1 and link.dst_slot == 0
    }
    if len(connected.intersection(encoder_ids)) < 2:
        result.reasons.append(
            "CheckpointLoaderSimple CLIP output must connect to both CLIPTextEncode nodes."
        )


def _require_encoders_to_sampler(graph: WorkflowGraph, result: WorkflowValidationResult) -> None:
    encoder_ids = graph.node_ids_of_type("CLIPTextEncode")
    sampler_ids = graph.node_ids_of_type("KSampler")
    if len(sampler_ids) != 1 or len(encoder_ids) < 2:
        return
    sampler_id = sampler_ids[0]
    positive_links = graph.links_to_input(sampler_id, 1)
    negative_links = graph.links_to_input(sampler_id, 2)
    positive_sources = {link.src_node for link in positive_links}
    negative_sources = {link.src_node for link in negative_links}
    if len(positive_sources.intersection(encoder_ids)) == 0:
        result.reasons.append("Positive CLIPTextEncode conditioning must connect to KSampler.")
    if len(negative_sources.intersection(encoder_ids)) == 0:
        result.reasons.append("Negative CLIPTextEncode conditioning must connect to KSampler.")


def _validate_shared_sampler_decode_paths(graph: WorkflowGraph, result: WorkflowValidationResult) -> None:
    _require_path(
        graph,
        result,
        src_type="CheckpointLoaderSimple",
        src_slot=0,
        dst_type="KSampler",
        dst_slot=0,
        description="CheckpointLoaderSimple MODEL → KSampler model",
    )
    _require_checkpoint_clip_to_encoders(graph, result)
    _require_encoders_to_sampler(graph, result)
    _require_path(
        graph,
        result,
        src_type="KSampler",
        src_slot=0,
        dst_type="VAEDecode",
        dst_slot=0,
        description="KSampler LATENT → VAEDecode samples",
    )
    _require_path(
        graph,
        result,
        src_type="CheckpointLoaderSimple",
        src_slot=2,
        dst_type="VAEDecode",
        dst_slot=1,
        description="CheckpointLoaderSimple VAE → VAEDecode vae",
    )
    _require_path(
        graph,
        result,
        src_type="VAEDecode",
        src_slot=0,
        dst_type="SaveImage",
        dst_slot=0,
        description="VAEDecode IMAGE → SaveImage images",
    )


def _validate_img2img_connectivity(graph: WorkflowGraph, result: WorkflowValidationResult) -> None:
    _require_path(
        graph,
        result,
        src_type="LoadImage",
        src_slot=0,
        dst_type="VAEEncode",
        dst_slot=0,
        description="LoadImage IMAGE → VAEEncode pixels",
    )
    _require_path(
        graph,
        result,
        src_type="CheckpointLoaderSimple",
        src_slot=2,
        dst_type="VAEEncode",
        dst_slot=1,
        description="CheckpointLoaderSimple VAE → VAEEncode vae",
    )
    _require_path(
        graph,
        result,
        src_type="VAEEncode",
        src_slot=0,
        dst_type="KSampler",
        dst_slot=3,
        description="VAEEncode LATENT → KSampler latent_image",
    )
    _validate_shared_sampler_decode_paths(graph, result)


def _validate_inpainting_connectivity(graph: WorkflowGraph, result: WorkflowValidationResult) -> None:
    _require_path(
        graph,
        result,
        src_type="LoadImage",
        src_slot=0,
        dst_type="VAEEncodeForInpaint",
        dst_slot=0,
        description="LoadImage IMAGE → VAEEncodeForInpaint pixels",
    )
    _require_path(
        graph,
        result,
        src_type="LoadImageMask",
        src_slot=0,
        dst_type="VAEEncodeForInpaint",
        dst_slot=2,
        description="LoadImageMask MASK → VAEEncodeForInpaint mask",
    )
    _require_path(
        graph,
        result,
        src_type="CheckpointLoaderSimple",
        src_slot=2,
        dst_type="VAEEncodeForInpaint",
        dst_slot=1,
        description="CheckpointLoaderSimple VAE → VAEEncodeForInpaint vae",
    )
    _require_path(
        graph,
        result,
        src_type="VAEEncodeForInpaint",
        src_slot=0,
        dst_type="KSampler",
        dst_slot=3,
        description="VAEEncodeForInpaint LATENT → KSampler latent_image",
    )
    _validate_shared_sampler_decode_paths(graph, result)


def _validate_outpainting_connectivity(graph: WorkflowGraph, result: WorkflowValidationResult) -> None:
    _require_path(
        graph,
        result,
        src_type="LoadImage",
        src_slot=0,
        dst_type="ImagePadForOutpaint",
        dst_slot=0,
        description="LoadImage IMAGE → ImagePadForOutpaint image",
    )
    _require_path(
        graph,
        result,
        src_type="ImagePadForOutpaint",
        src_slot=0,
        dst_type="VAEEncodeForInpaint",
        dst_slot=0,
        description="ImagePadForOutpaint IMAGE → VAEEncodeForInpaint pixels",
    )
    _require_path(
        graph,
        result,
        src_type="ImagePadForOutpaint",
        src_slot=1,
        dst_type="VAEEncodeForInpaint",
        dst_slot=2,
        description="ImagePadForOutpaint MASK → VAEEncodeForInpaint mask",
    )
    _require_path(
        graph,
        result,
        src_type="CheckpointLoaderSimple",
        src_slot=2,
        dst_type="VAEEncodeForInpaint",
        dst_slot=1,
        description="CheckpointLoaderSimple VAE → VAEEncodeForInpaint vae",
    )
    _require_path(
        graph,
        result,
        src_type="VAEEncodeForInpaint",
        src_slot=0,
        dst_type="KSampler",
        dst_slot=3,
        description="VAEEncodeForInpaint LATENT → KSampler latent_image",
    )
    _validate_shared_sampler_decode_paths(graph, result)


def _validate_workflow_metadata(data: dict[str, Any], result: WorkflowValidationResult) -> dict[int, ParsedLink]:
    nodes = data.get("nodes")
    links_raw = data.get("links")
    if not isinstance(nodes, list) or not isinstance(links_raw, list):
        return {}

    node_ids = [node.get("id") for node in nodes if isinstance(node, dict) and isinstance(node.get("id"), int)]
    if node_ids:
        max_node_id = max(node_ids)
        last_node_id = data.get("last_node_id")
        if not isinstance(last_node_id, int):
            result.reasons.append("last_node_id must be an integer.")
        elif last_node_id < max_node_id:
            result.reasons.append(
                f"last_node_id {last_node_id} is below maximum node id {max_node_id}."
            )

    links_by_id: dict[int, ParsedLink] = {}
    for index, link in enumerate(links_raw):
        if not isinstance(link, list) or len(link) < 6:
            continue
        link_id, src_node, src_slot, dst_node, dst_slot, link_type = link[:6]
        if not all(isinstance(value, int) for value in (link_id, src_node, src_slot, dst_node, dst_slot)):
            continue
        if not isinstance(link_type, str):
            continue
        if link_id in links_by_id:
            result.reasons.append(f"Duplicate link id detected: {link_id}.")
            continue
        links_by_id[link_id] = ParsedLink(
            link_id=link_id,
            src_node=src_node,
            src_slot=src_slot,
            dst_node=dst_node,
            dst_slot=dst_slot,
            link_type=link_type,
        )

    if links_by_id:
        max_link_id = max(links_by_id)
        last_link_id = data.get("last_link_id")
        if not isinstance(last_link_id, int):
            result.reasons.append("last_link_id must be an integer.")
        elif last_link_id < max_link_id:
            result.reasons.append(
                f"last_link_id {last_link_id} is below maximum link id {max_link_id}."
            )

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, int):
            continue

        inputs = node.get("inputs", [])
        if isinstance(inputs, list):
            for input_index, node_input in enumerate(inputs):
                if not isinstance(node_input, dict):
                    continue
                link_ref = node_input.get("link")
                if link_ref is None:
                    continue
                if not isinstance(link_ref, int):
                    result.reasons.append(f"Node {node_id} input {input_index} has a non-integer link reference.")
                    continue
                parsed = links_by_id.get(link_ref)
                if parsed is None:
                    result.reasons.append(
                        f"Node {node_id} input {input_index} references unknown link id {link_ref}."
                    )
                    continue
                if parsed.dst_node != node_id or parsed.dst_slot != input_index:
                    result.reasons.append(
                        f"Node {node_id} input {input_index} references link {link_ref} "
                        f"with mismatched destination node/socket."
                    )

        outputs = node.get("outputs", [])
        if isinstance(outputs, list):
            for output_index, node_output in enumerate(outputs):
                if not isinstance(node_output, dict):
                    continue
                slot_index = node_output.get("slot_index", output_index)
                if not isinstance(slot_index, int):
                    slot_index = output_index
                link_refs = node_output.get("links")
                if link_refs is None:
                    continue
                if not isinstance(link_refs, list):
                    result.reasons.append(
                        f"Node {node_id} output {output_index} links must be a list when present."
                    )
                    continue
                for link_ref in link_refs:
                    if not isinstance(link_ref, int):
                        continue
                    parsed = links_by_id.get(link_ref)
                    if parsed is None:
                        result.reasons.append(
                            f"Node {node_id} output slot {slot_index} references unknown link id {link_ref}."
                        )
                        continue
                    if parsed.src_node != node_id or parsed.src_slot != slot_index:
                        result.reasons.append(
                            f"Node {node_id} output slot {slot_index} references link {link_ref} "
                            f"with mismatched source node/socket."
                        )

    return links_by_id


def _validate_graph_connectivity(
    data: dict[str, Any],
    result: WorkflowValidationResult,
    *,
    connectivity_check: Callable[[WorkflowGraph, WorkflowValidationResult], None],
) -> None:
    graph = _parse_workflow_graph(data, result)
    if graph is None:
        return
    connectivity_check(graph, result)


def _validate_workflow_template(
    workflow_id: str,
    path: Path,
    *,
    expected_node_count: int,
    required_types: frozenset[str],
    output_prefix: str,
    extra_checks: Callable[[dict[str, Any], list[str], WorkflowValidationResult], None] | None = None,
    connectivity_check: Callable[[WorkflowGraph, WorkflowValidationResult], None] | None = None,
) -> WorkflowValidationResult:
    result = WorkflowValidationResult(workflow_id=workflow_id, path=str(path), valid=False)
    data, load_errors = _load_workflow_json(path)
    if data is None:
        result.reasons.extend(load_errors)
        return result

    node_types = _collect_nodes(data, result)
    if node_types is None:
        return result

    if result.node_count != expected_node_count:
        result.reasons.append(
            f"Workflow must contain {expected_node_count} nodes; found {result.node_count}."
        )

    _require_node_types(result, node_types, required_types)
    _require_clip_encode_count(result, node_types)
    _require_save_prefix(data, result, output_prefix)
    _validate_workflow_metadata(data, result)
    if connectivity_check is not None:
        _validate_graph_connectivity(data, result, connectivity_check=connectivity_check)
    if extra_checks is not None:
        extra_checks(data, node_types, result)

    result.valid = not result.reasons
    return result


def _img2img_extra_checks(data: dict[str, Any], node_types: list[str], result: WorkflowValidationResult) -> None:
    if "VAEEncode" not in node_types:
        result.reasons.append("img2img workflow requires an image-to-latent VAEEncode path.")
    if "LoadImage" not in node_types:
        result.reasons.append("img2img workflow requires a LoadImage source input.")


def _inpainting_extra_checks(data: dict[str, Any], node_types: list[str], result: WorkflowValidationResult) -> None:
    if "LoadImageMask" not in node_types:
        result.reasons.append("inpainting workflow requires a LoadImageMask mask input.")
    if "VAEEncodeForInpaint" not in node_types:
        result.reasons.append("inpainting workflow requires a mask-aware VAEEncodeForInpaint path.")
    sampler_nodes = [
        node for node in data.get("nodes", []) if isinstance(node, dict) and node.get("type") == "KSampler"
    ]
    if len(sampler_nodes) == 1:
        widgets = sampler_nodes[0].get("widgets_values", [])
        if len(widgets) < 7 or widgets[6] != INPAINTING_CANONICAL_DENOISE:
            result.reasons.append(
                f"Inpainting KSampler denoise must be {INPAINTING_CANONICAL_DENOISE} for the true-inpainting path."
            )
    checkpoint_nodes = [
        node for node in data.get("nodes", []) if isinstance(node, dict) and node.get("type") == "CheckpointLoaderSimple"
    ]
    if len(checkpoint_nodes) == 1:
        widgets = checkpoint_nodes[0].get("widgets_values", [])
        checkpoint_name = widgets[0] if widgets else None
        if checkpoint_name != INPAINTING_CANONICAL_CHECKPOINT:
            result.reasons.append(
                f"Inpainting checkpoint must be {INPAINTING_CANONICAL_CHECKPOINT!r}; found {checkpoint_name!r}."
            )
    mask_nodes = [
        node for node in data.get("nodes", []) if isinstance(node, dict) and node.get("type") == "LoadImageMask"
    ]
    if len(mask_nodes) == 1:
        widgets = mask_nodes[0].get("widgets_values", [])
        mask_channel = widgets[1] if len(widgets) > 1 else None
        if mask_channel != INPAINTING_CANONICAL_MASK_CHANNEL:
            result.reasons.append(
                f"Inpainting mask channel must be {INPAINTING_CANONICAL_MASK_CHANNEL!r}; found {mask_channel!r}."
            )


def _outpainting_extra_checks(data: dict[str, Any], node_types: list[str], result: WorkflowValidationResult) -> None:
    if "ImagePadForOutpaint" not in node_types:
        result.reasons.append("outpainting workflow requires ImagePadForOutpaint for canvas expansion.")
    if "VAEEncodeForInpaint" not in node_types:
        result.reasons.append("outpainting workflow requires a mask-aware VAEEncodeForInpaint path.")
    pad_nodes = [
        node
        for node in data.get("nodes", [])
        if isinstance(node, dict) and node.get("type") == "ImagePadForOutpaint"
    ]
    if len(pad_nodes) == 1:
        widgets = pad_nodes[0].get("widgets_values", [])
        if len(widgets) >= 4 and all(int(widgets[index]) == 0 for index in range(4)):
            result.reasons.append(
                "Outpainting workflow must configure at least one ImagePadForOutpaint expansion side > 0."
            )
    sampler_nodes = [
        node for node in data.get("nodes", []) if isinstance(node, dict) and node.get("type") == "KSampler"
    ]
    if len(sampler_nodes) == 1:
        widgets = sampler_nodes[0].get("widgets_values", [])
        if len(widgets) < 7 or widgets[6] != OUTPAINTING_CANONICAL_DENOISE:
            result.reasons.append(
                f"Outpainting KSampler denoise must be {OUTPAINTING_CANONICAL_DENOISE} for the true-inpainting path."
            )


def validate_base_txt2img_workflow(path: Path) -> WorkflowValidationResult:
    return _validate_workflow_template(
        BASE_TXT2IMG_WORKFLOW_ID,
        path,
        expected_node_count=BASE_TXT2IMG_NODE_COUNT,
        required_types=BASE_TXT2IMG_REQUIRED_NODE_TYPES,
        output_prefix=WORKFLOW_OUTPUT_PREFIXES[BASE_TXT2IMG_WORKFLOW_ID],
    )


def validate_base_img2img_workflow(path: Path) -> WorkflowValidationResult:
    return _validate_workflow_template(
        BASE_IMG2IMG_WORKFLOW_ID,
        path,
        expected_node_count=BASE_IMG2IMG_NODE_COUNT,
        required_types=BASE_IMG2IMG_REQUIRED_NODE_TYPES,
        output_prefix=WORKFLOW_OUTPUT_PREFIXES[BASE_IMG2IMG_WORKFLOW_ID],
        extra_checks=_img2img_extra_checks,
        connectivity_check=_validate_img2img_connectivity,
    )


def validate_base_inpainting_workflow(path: Path) -> WorkflowValidationResult:
    return _validate_workflow_template(
        BASE_INPAINTING_WORKFLOW_ID,
        path,
        expected_node_count=BASE_INPAINTING_NODE_COUNT,
        required_types=BASE_INPAINTING_REQUIRED_NODE_TYPES,
        output_prefix=WORKFLOW_OUTPUT_PREFIXES[BASE_INPAINTING_WORKFLOW_ID],
        extra_checks=_inpainting_extra_checks,
        connectivity_check=_validate_inpainting_connectivity,
    )


def validate_base_outpainting_workflow(path: Path) -> WorkflowValidationResult:
    return _validate_workflow_template(
        BASE_OUTPAINTING_WORKFLOW_ID,
        path,
        expected_node_count=BASE_OUTPAINTING_NODE_COUNT,
        required_types=BASE_OUTPAINTING_REQUIRED_NODE_TYPES,
        output_prefix=WORKFLOW_OUTPUT_PREFIXES[BASE_OUTPAINTING_WORKFLOW_ID],
        extra_checks=_outpainting_extra_checks,
        connectivity_check=_validate_outpainting_connectivity,
    )


def validate_workflow(workflow_id: str, path: Path) -> WorkflowValidationResult:
    validators = {
        BASE_TXT2IMG_WORKFLOW_ID: validate_base_txt2img_workflow,
        BASE_IMG2IMG_WORKFLOW_ID: validate_base_img2img_workflow,
        BASE_INPAINTING_WORKFLOW_ID: validate_base_inpainting_workflow,
        BASE_OUTPAINTING_WORKFLOW_ID: validate_base_outpainting_workflow,
    }
    validator = validators.get(workflow_id)
    if validator is not None:
        return validator(path)

    result = WorkflowValidationResult(workflow_id=workflow_id, path=str(path), valid=False)
    if not path.is_file():
        result.reasons.append(f"Workflow file missing: {path}")
        return result
    result.valid = True
    return result


def validate_workflow_from_data(workflow_id: str, data: dict[str, Any]) -> WorkflowValidationResult:
    """Validate an in-memory workflow document using the shared workflow validators."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "workflow.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = validate_workflow(workflow_id, path)
        result.path = "<prepared>"
        return result
