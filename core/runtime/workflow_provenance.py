#!/usr/bin/env python3
"""Workflow identification, normalized hashing, and ComfyUI execution provenance extraction.

Hash representations (never compared across types):
  - UI workflow hash (``ui_workflow_v1``): SHA-256 over normalized ComfyUI UI workflow JSON
    (the drag-and-drop graph, ``nodes`` + ``links``). Used to identify registered workflows.
  - API prompt hash (``api_prompt_v1``): SHA-256 over the normalized ComfyUI API prompt
    (``class_type`` + ``inputs`` per node). Reflects exactly what executed.

UI structural signature ignores widget values (prompts/seed) so a registered canonical
workflow still identifies after the user edits its prompt or seed, while the exact UI hash
preserves full reproducibility.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
PROVENANCE_VERSION = 2

HASH_TYPE_UI = "ui_workflow_v1"
HASH_TYPE_API = "api_prompt_v1"
HASH_TYPE_NONE = "unavailable"

_UI_TOP_IGNORE_KEYS = frozenset({"last_node_id", "last_link_id", "groups", "config", "extra", "version"})

WORKFLOW_ID_TO_IDENTIFIER: dict[str, tuple[str, str]] = {
    "base_txt2img": ("base/txt2img", "registered_canonical"),
    "base_img2img": ("base/img2img", "registered_canonical"),
    "base_inpainting": ("base/inpainting", "registered_canonical"),
    "base_outpainting": ("base/outpainting", "registered_canonical"),
    "reference_inpainting_official": ("reference/inpainting_official", "registered_reference"),
    "reference_qwen_image_edit": ("benchmark/qwen_image_edit", "registered_reference"),
    "reference_flux_fill": ("benchmark/flux_fill", "registered_reference"),
    "diag_inpainting_mask_preview": ("diagnostics/inpainting_mask_preview", "registered_diagnostic"),
}

IDENTIFIER_TO_CAPABILITY: dict[str, str] = {
    "base/txt2img": "txt2img",
    "base/img2img": "img2img",
    "base/inpainting": "inpainting",
    "base/outpainting": "outpainting",
    "reference/inpainting_official": "inpainting",
    "benchmark/qwen_image_edit": "qwen_image_edit_benchmark",
    "benchmark/flux_fill": "flux_fill_benchmark",
}

CHECKPOINT_TO_FAMILY: dict[str, str] = {
    "sd15.safetensors": "sd15",
    "512-inpainting-ema.safetensors": "sd15_inpainting",
}


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_of(data: Any) -> str:
    return hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()


def workflow_hash_from_normalized(normalized: Any) -> str:
    return _sha256_of(normalized)


def _normalized_ui_nodes(data: dict[str, Any], *, include_widgets: bool) -> list[dict[str, Any]]:
    nodes = data.get("nodes") or []
    normalized_nodes: list[dict[str, Any]] = []
    for node in sorted(nodes, key=lambda item: str(item.get("id", ""))):
        if not isinstance(node, dict):
            continue
        entry: dict[str, Any] = {"id": node.get("id"), "type": node.get("type")}
        if include_widgets and "widgets_values" in node:
            entry["widgets_values"] = node.get("widgets_values")
        inputs = node.get("inputs")
        if isinstance(inputs, list):
            wired: list[dict[str, Any]] = []
            for inp in inputs:
                if not isinstance(inp, dict):
                    continue
                wired.append({"name": inp.get("name"), "type": inp.get("type"), "link": inp.get("link")})
            entry["inputs"] = sorted(wired, key=lambda item: str(item.get("name", "")))
        normalized_nodes.append(entry)
    return normalized_nodes


def _normalized_ui_links(data: dict[str, Any]) -> list[list[Any]]:
    links = data.get("links") or []
    normalized_links: list[list[Any]] = []
    for link in links:
        if isinstance(link, list) and len(link) >= 5:
            normalized_links.append([link[1], link[2], link[3], link[4]])
    normalized_links.sort(key=lambda item: (str(item[0]), str(item[1]), str(item[2]), str(item[3])))
    return normalized_links


def normalize_ui_workflow(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize UI workflow JSON for the exact reproducibility hash (includes widgets_values)."""
    return {"nodes": _normalized_ui_nodes(data, include_widgets=True), "links": _normalized_ui_links(data)}


def structural_signature_ui(data: dict[str, Any]) -> str:
    """Structural identity of a UI workflow: node types + wiring, ignoring widget values and layout."""
    signature = {"nodes": _normalized_ui_nodes(data, include_widgets=False), "links": _normalized_ui_links(data)}
    return _sha256_of(signature)


def hash_ui_workflow(data: dict[str, Any]) -> str:
    return workflow_hash_from_normalized(normalize_ui_workflow(data))


def normalize_api_prompt(prompt_nodes: dict[str, Any]) -> dict[str, Any]:
    def _norm_value(value: Any) -> Any:
        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int)):
            return [str(value[0]), value[1]]
        if isinstance(value, dict):
            return {str(k): _norm_value(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
        if isinstance(value, list):
            return [_norm_value(v) for v in value]
        return value

    normalized: dict[str, Any] = {}
    for node_id in sorted(prompt_nodes.keys(), key=lambda k: str(k)):
        node = prompt_nodes[node_id]
        if not isinstance(node, dict):
            continue
        normalized[str(node_id)] = {
            "class_type": node.get("class_type"),
            "inputs": _norm_value(node.get("inputs") or {}),
        }
    return normalized


def hash_api_prompt(prompt_nodes: dict[str, Any]) -> str:
    return workflow_hash_from_normalized(normalize_api_prompt(prompt_nodes))


# --------------------------------------------------------------------------------------
# History extraction (robust to real ComfyUI serialization forms)
# --------------------------------------------------------------------------------------


def _looks_like_api_prompt(candidate: Any) -> bool:
    if not isinstance(candidate, dict) or not candidate:
        return False
    for value in candidate.values():
        if isinstance(value, dict) and "class_type" in value:
            return True
    return False


def _looks_like_ui_workflow(candidate: Any) -> bool:
    return (
        isinstance(candidate, dict)
        and isinstance(candidate.get("nodes"), list)
        and "links" in candidate
    )


def extract_prompt_dict(history_entry: dict[str, Any]) -> dict[str, Any] | None:
    """Return the API prompt node dict from a ComfyUI history entry (robust to index position)."""
    prompt_field = history_entry.get("prompt")
    if isinstance(prompt_field, dict) and _looks_like_api_prompt(prompt_field):
        return prompt_field
    if isinstance(prompt_field, list):
        for element in prompt_field:
            if _looks_like_api_prompt(element):
                return element
    # Some serializations nest the api prompt at the top level.
    if _looks_like_api_prompt(history_entry.get("api_prompt")):
        return history_entry.get("api_prompt")
    return None


def _ui_workflow_from_extra(extra: Any) -> dict[str, Any] | None:
    if not isinstance(extra, dict):
        return None
    pnginfo = extra.get("extra_pnginfo")
    if isinstance(pnginfo, dict):
        workflow = pnginfo.get("workflow")
        if _looks_like_ui_workflow(workflow):
            return workflow
    workflow = extra.get("workflow")
    if _looks_like_ui_workflow(workflow):
        return workflow
    return None


def extract_ui_workflow_from_history(history_entry: dict[str, Any]) -> dict[str, Any] | None:
    """Find the UI workflow JSON from supported history forms. Returns None when unavailable."""
    if not isinstance(history_entry, dict):
        return None

    direct = _ui_workflow_from_extra(history_entry.get("extra_data"))
    if direct is not None:
        return direct

    prompt_field = history_entry.get("prompt")
    if isinstance(prompt_field, list):
        for element in prompt_field:
            found = _ui_workflow_from_extra(element)
            if found is not None:
                return found
            if _looks_like_ui_workflow(element):
                return element

    if _looks_like_ui_workflow(history_entry.get("workflow")):
        return history_entry.get("workflow")

    return None


def _embedded_ai_studio_metadata(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    extra = data.get("extra")
    if isinstance(extra, dict):
        meta = extra.get("ai_studio")
        if isinstance(meta, dict):
            return meta
    return None


def extract_ai_studio_extra(ui_workflow: dict[str, Any] | None) -> dict[str, Any]:
    """Return embedded ``extra.ai_studio`` metadata from a UI workflow, or {}."""
    meta = _embedded_ai_studio_metadata(ui_workflow)
    return dict(meta) if isinstance(meta, dict) else {}


# --------------------------------------------------------------------------------------
# Registered workflow identification
# --------------------------------------------------------------------------------------


def load_registered_workflow_hashes(
    repo_root: Path, workflows: list[dict[str, Any]]
) -> dict[str, tuple[str, str, str]]:
    """Map UI exact hash AND structural signature → (registry_id, identifier, source)."""
    mapping: dict[str, tuple[str, str, str]] = {}
    for workflow in workflows:
        workflow_id = str(workflow.get("id") or "")
        rel_path = str(workflow.get("path") or "")
        if not rel_path:
            continue
        path = repo_root / rel_path
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        identifier, source = WORKFLOW_ID_TO_IDENTIFIER.get(
            workflow_id, (f"registry/{workflow_id}", "registered")
        )
        mapping[hash_ui_workflow(data)] = (workflow_id, identifier, source)
        mapping[structural_signature_ui(data)] = (workflow_id, identifier, source)
    return mapping


def match_workflow_hash(
    digest: str,
    registered: dict[str, tuple[str, str, str]],
) -> tuple[str, str, str]:
    if digest in registered:
        _wid, identifier, source = registered[digest]
        return identifier, digest, source
    return "unknown", digest, "unregistered"


# --------------------------------------------------------------------------------------
# API-graph inspection
# --------------------------------------------------------------------------------------


def _nodes_by_type(prompt_nodes: dict[str, Any], class_type: str) -> list[dict[str, Any]]:
    return [
        node
        for node in prompt_nodes.values()
        if isinstance(node, dict) and node.get("class_type") == class_type
    ]


def _has_type(prompt_nodes: dict[str, Any], class_type: str) -> bool:
    return any(
        isinstance(node, dict) and node.get("class_type") == class_type for node in prompt_nodes.values()
    )


def _bfs_back(prompt_nodes: dict[str, Any], start_id: str, target_types: set[str]) -> dict[str, Any] | None:
    """Walk backward over input references from start_id to the nearest node of a target type."""
    queue: list[str] = [str(start_id)]
    seen: set[str] = set()
    while queue:
        node_id = queue.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)
        node = prompt_nodes.get(node_id)
        if not isinstance(node, dict):
            continue
        if node.get("class_type") in target_types:
            return node
        for value in (node.get("inputs") or {}).values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int)):
                queue.append(str(value[0]))
    return None


_SAMPLER_TYPES = {"KSampler", "KSamplerAdvanced"}


def _find_sampler_for_output(
    prompt_nodes: dict[str, Any], output_node_id: str | None
) -> tuple[dict[str, Any] | None, bool]:
    """Return (sampler_node, branch_resolved). Traverse backward from the specific output node."""
    if output_node_id is not None and str(output_node_id) in prompt_nodes:
        sampler = _bfs_back(prompt_nodes, str(output_node_id), _SAMPLER_TYPES)
        if sampler is not None:
            return sampler, True

    save_nodes = _nodes_by_type(prompt_nodes, "SaveImage") + _nodes_by_type(prompt_nodes, "SaveAnimatedWEBP")
    if len(save_nodes) == 1:
        for node_id, node in prompt_nodes.items():
            if node is save_nodes[0]:
                sampler = _bfs_back(prompt_nodes, node_id, _SAMPLER_TYPES)
                if sampler is not None:
                    return sampler, True

    samplers = [n for n in prompt_nodes.values() if isinstance(n, dict) and n.get("class_type") in _SAMPLER_TYPES]
    if len(samplers) == 1:
        return samplers[0], True
    if samplers:
        return samplers[0], False
    return None, False


def _resolve_conditioning_text(prompt_nodes: dict[str, Any], ref: Any) -> tuple[str, bool]:
    if not (isinstance(ref, list) and len(ref) == 2 and isinstance(ref[0], (str, int))):
        return "", False
    node = _bfs_back(prompt_nodes, str(ref[0]), {"CLIPTextEncode"})
    if node is not None:
        text = (node.get("inputs") or {}).get("text")
        if isinstance(text, str):
            return text, True
    return "", False


def _resolve_prompts(
    prompt_nodes: dict[str, Any], sampler: dict[str, Any] | None
) -> tuple[str, str, bool]:
    """Resolve (positive, negative, wiring_resolved) following KSampler conditioning inputs."""
    if sampler is not None:
        inputs = sampler.get("inputs") or {}
        positive, pos_ok = _resolve_conditioning_text(prompt_nodes, inputs.get("positive"))
        negative, neg_ok = _resolve_conditioning_text(prompt_nodes, inputs.get("negative"))
        if pos_ok:
            return positive, negative, (pos_ok and neg_ok)

    # Deterministic fallback: order CLIPTextEncode nodes by node id.
    encoders = sorted(
        (
            (node_id, node)
            for node_id, node in prompt_nodes.items()
            if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode"
        ),
        key=lambda item: int(item[0]) if str(item[0]).isdigit() else str(item[0]),
    )
    positive = ""
    negative = ""
    if encoders:
        text = (encoders[0][1].get("inputs") or {}).get("text")
        if isinstance(text, str):
            positive = text
    if len(encoders) >= 2:
        text = (encoders[1][1].get("inputs") or {}).get("text")
        if isinstance(text, str):
            negative = text
    return positive, negative, False


def _sampler_fields(sampler: dict[str, Any] | None) -> dict[str, Any]:
    if sampler is None:
        return {}
    inputs = sampler.get("inputs") or {}
    fields: dict[str, Any] = {}
    for key in ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"):
        value = inputs.get(key)
        if value is not None and not isinstance(value, list):
            fields[key] = value
    return fields


def _latent_dimensions(prompt_nodes: dict[str, Any], sampler: dict[str, Any] | None) -> tuple[int | None, int | None]:
    latent_node: dict[str, Any] | None = None
    if sampler is not None:
        ref = (sampler.get("inputs") or {}).get("latent_image")
        if isinstance(ref, list) and len(ref) == 2:
            latent_node = _bfs_back(prompt_nodes, str(ref[0]), {"EmptyLatentImage"})
    if latent_node is None:
        candidates = _nodes_by_type(prompt_nodes, "EmptyLatentImage")
        latent_node = candidates[0] if len(candidates) == 1 else None
    if latent_node is None:
        return None, None
    inputs = latent_node.get("inputs") or {}
    try:
        width = int(inputs["width"]) if inputs.get("width") is not None else None
        height = int(inputs["height"]) if inputs.get("height") is not None else None
        return width, height
    except (TypeError, ValueError):
        return None, None


def _save_prefix(prompt_nodes: dict[str, Any], output_node_id: str | None) -> str:
    if output_node_id is not None:
        node = prompt_nodes.get(str(output_node_id))
        if isinstance(node, dict):
            prefix = (node.get("inputs") or {}).get("filename_prefix")
            if isinstance(prefix, str):
                return prefix
    for node in _nodes_by_type(prompt_nodes, "SaveImage"):
        prefix = (node.get("inputs") or {}).get("filename_prefix")
        if isinstance(prefix, str):
            return prefix
    return ""


def _checkpoint_names(prompt_nodes: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for node in _nodes_by_type(prompt_nodes, "CheckpointLoaderSimple"):
        ckpt = (node.get("inputs") or {}).get("ckpt_name")
        if isinstance(ckpt, str) and ckpt:
            names.append(ckpt)
    for node in _nodes_by_type(prompt_nodes, "UNETLoader"):
        unet = (node.get("inputs") or {}).get("unet_name")
        if isinstance(unet, str) and unet:
            names.append(unet)
    return names


def _source_and_mask_filenames(prompt_nodes: dict[str, Any]) -> tuple[list[str], list[str]]:
    sources: list[str] = []
    masks: list[str] = []
    for node in _nodes_by_type(prompt_nodes, "LoadImage"):
        image = (node.get("inputs") or {}).get("image")
        if isinstance(image, str):
            sources.append(image)
    for node in _nodes_by_type(prompt_nodes, "LoadImageMask"):
        image = (node.get("inputs") or {}).get("image")
        if isinstance(image, str):
            masks.append(image)
    return sources, masks


def classify_capability_structural(prompt_nodes: dict[str, Any]) -> str:
    """Classify capability from execution graph structure (never from checkpoint filename alone)."""
    if not prompt_nodes:
        return ""
    # Benchmark signatures first (explicit loaders / model families).
    checkpoints = " ".join(_checkpoint_names(prompt_nodes)).lower()
    if "qwen" in checkpoints:
        return "qwen_image_edit_benchmark"
    if "flux" in checkpoints or _has_type(prompt_nodes, "FluxGuidance"):
        return "flux_fill_benchmark"

    has_outpaint = _has_type(prompt_nodes, "ImagePadForOutpaint")
    has_inpaint_encode = _has_type(prompt_nodes, "VAEEncodeForInpaint")
    has_mask = _has_type(prompt_nodes, "LoadImageMask")
    has_vae_encode = _has_type(prompt_nodes, "VAEEncode")
    has_load_image = _has_type(prompt_nodes, "LoadImage")
    has_empty_latent = _has_type(prompt_nodes, "EmptyLatentImage")

    if has_outpaint:
        return "outpainting"
    if has_inpaint_encode or has_mask:
        return "inpainting"
    if has_vae_encode and has_load_image:
        return "img2img"
    if has_empty_latent and not has_load_image and not has_vae_encode:
        return "txt2img"
    return ""


def resolve_model_provenance(
    *,
    capability: str,
    workflow_identifier: str,
    checkpoint_names: list[str],
) -> tuple[str, list[str], str]:
    """Return (model_family, model_files, candidate_model). Checkpoint never overrides graph capability."""
    if workflow_identifier == "benchmark/qwen_image_edit" or capability == "qwen_image_edit_benchmark":
        return "qwen_image_edit", checkpoint_names, "qwen_image_edit_2511"
    if workflow_identifier == "benchmark/flux_fill" or capability == "flux_fill_benchmark":
        return "flux_fill", checkpoint_names, "flux_fill_dev"

    model_family = ""
    for ckpt in checkpoint_names:
        if ckpt in CHECKPOINT_TO_FAMILY:
            model_family = CHECKPOINT_TO_FAMILY[ckpt]
            break
    if not model_family and checkpoint_names:
        if any("inpaint" in name.lower() for name in checkpoint_names):
            model_family = "sd15_inpainting"
        else:
            model_family = "sd15"
    if capability == "inpainting" and checkpoint_names and model_family == "sd15":
        # A dedicated inpainting graph on a non-dedicated checkpoint stays sd15 family.
        model_family = "sd15"
    return model_family, list(checkpoint_names), ""


REQUIRED_PROVENANCE_FIELDS = (
    "workflow_identifier",
    "workflow_hash",
    "workflow_hash_type",
    "capability",
    "model_files",
    "positive_prompt",
    "seed",
    "steps",
    "cfg",
    "sampler_name",
    "scheduler",
    "denoise",
    "save_prefix",
)


@dataclass
class ExecutionProvenance:
    schema_version: int = SCHEMA_VERSION
    provenance_version: int = PROVENANCE_VERSION
    workflow_identifier: str = "unknown"
    workflow_hash: str = ""
    workflow_hash_type: str = HASH_TYPE_NONE
    api_prompt_hash: str = ""
    workflow_source: str = "unregistered"
    capability: str = ""
    model_family: str = ""
    model_files: list[str] = field(default_factory=list)
    candidate_model: str = ""
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
    prompt_resolution: str = "none"
    provenance_status: str = "unavailable"
    missing_provenance_fields: list[str] = field(default_factory=list)
    preparation_id: str = ""
    prepared_workflow_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provenance_version": self.provenance_version,
            "workflow_identifier": self.workflow_identifier,
            "workflow_hash": self.workflow_hash,
            "workflow_hash_type": self.workflow_hash_type,
            "api_prompt_hash": self.api_prompt_hash,
            "workflow_source": self.workflow_source,
            "capability": self.capability,
            "model_family": self.model_family,
            "model_files": list(self.model_files),
            "candidate_model": self.candidate_model,
            "positive_prompt": self.positive_prompt,
            "negative_prompt": self.negative_prompt,
            "seed": self.seed,
            "steps": self.steps,
            "cfg": self.cfg,
            "sampler_name": self.sampler_name,
            "scheduler": self.scheduler,
            "denoise": self.denoise,
            "width": self.width,
            "height": self.height,
            "save_prefix": self.save_prefix,
            "source_image_filenames": list(self.source_image_filenames),
            "mask_filenames": list(self.mask_filenames),
            "prompt_resolution": self.prompt_resolution,
            "provenance_status": self.provenance_status,
            "missing_provenance_fields": list(self.missing_provenance_fields),
            "preparation_id": self.preparation_id,
            "prepared_workflow_hash": self.prepared_workflow_hash,
        }


def _compute_provenance_status(data: dict[str, Any]) -> tuple[str, list[str]]:
    missing: list[str] = []
    for field_name in REQUIRED_PROVENANCE_FIELDS:
        value = data.get(field_name)
        if value is None or value == "" or value == []:
            missing.append(field_name)
    if str(data.get("workflow_identifier") or "") == "unknown" and "workflow_identifier" not in missing:
        missing.append("workflow_identifier")
    if not missing:
        return "complete", []
    if data.get("workflow_hash"):
        return "partial", missing
    return "unavailable", missing


def _identify_from_ui(
    ui_workflow: dict[str, Any],
    registered: dict[str, tuple[str, str, str]],
) -> tuple[str, str, str]:
    """Return (identifier, source, ui_hash) using embedded metadata, exact hash, then structure."""
    ui_hash = hash_ui_workflow(ui_workflow)
    meta = _embedded_ai_studio_metadata(ui_workflow)
    if meta and meta.get("workflow_identifier"):
        return str(meta.get("workflow_identifier")), str(meta.get("workflow_source") or "prepared"), ui_hash
    if ui_hash in registered:
        _wid, identifier, source = registered[ui_hash]
        return identifier, source, ui_hash
    structural = structural_signature_ui(ui_workflow)
    if structural in registered:
        _wid, identifier, source = registered[structural]
        return identifier, source, ui_hash
    return "unknown", "unregistered", ui_hash


def extract_execution_provenance(
    history_entry: dict[str, Any],
    *,
    registered_hashes: dict[str, tuple[str, str, str]],
    ui_workflow: dict[str, Any] | None = None,
    output_node_id: str | None = None,
) -> ExecutionProvenance:
    """Extract provenance from ComfyUI history; never guesses missing execution values."""
    provenance = ExecutionProvenance()
    prompt_nodes = extract_prompt_dict(history_entry)
    if ui_workflow is None:
        ui_workflow = extract_ui_workflow_from_history(history_entry)

    # API prompt hash (execution graph) always recorded when available.
    if prompt_nodes:
        provenance.api_prompt_hash = hash_api_prompt(prompt_nodes)

    # Identification hierarchy.
    if ui_workflow is not None:
        identifier, source, ui_hash = _identify_from_ui(ui_workflow, registered_hashes)
        provenance.workflow_identifier = identifier
        provenance.workflow_source = source
        provenance.workflow_hash = ui_hash
        provenance.workflow_hash_type = HASH_TYPE_UI
        ai_meta = extract_ai_studio_extra(ui_workflow)
        if ai_meta.get("preparation_id"):
            provenance.preparation_id = str(ai_meta.get("preparation_id") or "")
        if ai_meta.get("prepared_workflow_hash"):
            provenance.prepared_workflow_hash = str(ai_meta.get("prepared_workflow_hash") or "")
        elif ai_meta.get("canonical_workflow_hash"):
            canonical = str(ai_meta.get("canonical_workflow_hash") or "")
            if canonical and ui_hash != canonical:
                provenance.prepared_workflow_hash = ui_hash
    elif prompt_nodes:
        provenance.workflow_hash = provenance.api_prompt_hash
        provenance.workflow_hash_type = HASH_TYPE_API
        provenance.workflow_identifier = "unknown"
        provenance.workflow_source = "unregistered"

    # Execution values from the API prompt, correlated to the synchronized output branch.
    if prompt_nodes:
        sampler, branch_resolved = _find_sampler_for_output(prompt_nodes, output_node_id)
        positive, negative, wiring_ok = _resolve_prompts(prompt_nodes, sampler)
        provenance.positive_prompt = positive
        provenance.negative_prompt = negative
        provenance.prompt_resolution = "wiring" if wiring_ok else "ordering"

        fields = _sampler_fields(sampler)
        provenance.seed = fields.get("seed") if isinstance(fields.get("seed"), int) else None
        provenance.steps = fields.get("steps") if isinstance(fields.get("steps"), int) else None
        cfg_val = fields.get("cfg")
        provenance.cfg = float(cfg_val) if isinstance(cfg_val, (int, float)) else None
        provenance.sampler_name = str(fields.get("sampler_name") or "")
        provenance.scheduler = str(fields.get("scheduler") or "")
        denoise_val = fields.get("denoise")
        provenance.denoise = float(denoise_val) if isinstance(denoise_val, (int, float)) else None

        width, height = _latent_dimensions(prompt_nodes, sampler)
        provenance.width = width
        provenance.height = height
        provenance.save_prefix = _save_prefix(prompt_nodes, output_node_id)
        sources, masks = _source_and_mask_filenames(prompt_nodes)
        provenance.source_image_filenames = sources
        provenance.mask_filenames = masks

        checkpoints = _checkpoint_names(prompt_nodes)
        # Capability: identifier mapping first, else structural classification.
        capability = IDENTIFIER_TO_CAPABILITY.get(provenance.workflow_identifier, "")
        if not capability:
            capability = classify_capability_structural(prompt_nodes)
        provenance.capability = capability
        family, files, candidate = resolve_model_provenance(
            capability=capability,
            workflow_identifier=provenance.workflow_identifier,
            checkpoint_names=checkpoints,
        )
        provenance.model_family = family
        provenance.model_files = files
        provenance.candidate_model = candidate
    elif ui_workflow is not None:
        # No API prompt, but UI workflow present: classify from identifier only.
        provenance.capability = IDENTIFIER_TO_CAPABILITY.get(provenance.workflow_identifier, "")

    status, missing = _compute_provenance_status(provenance.to_dict())
    provenance.provenance_status = status
    provenance.missing_provenance_fields = missing
    return provenance


def slugify_project_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "project"
