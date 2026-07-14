#!/usr/bin/env python3
"""Prepare temporary official-reference inpainting workflows (diagnostic only)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .input_staging import stage_input_file
from .input_utils import validate_input_path
from .inpainting_workflow_compare import (
    CANONICAL_INPAINTING_PATH,
    REFERENCE_INPAINTING_PATH,
)
from .mask_diagnostics import analyze_mask
from .output_sync import utc_collision_timestamp
from .registry_loader import RegistryBundle, RegistryLoader
from .workflow_validation import INPAINTING_CANONICAL_CHECKPOINT, INPAINTING_CANONICAL_DENOISE

# Temporary prepared copies only — do not mutate the extracted reference JSON.
CONTROLLED_GROW_MASK_BY = 6


@dataclass
class ResolvedReferencePaths:
    runtime_dir: Path
    comfyui_input_dir: Path
    runtime_dir_source: str
    comfyui_input_dir_source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_dir": str(self.runtime_dir),
            "comfyui_input_dir": str(self.comfyui_input_dir),
            "runtime_dir_source": self.runtime_dir_source,
            "comfyui_input_dir_source": self.comfyui_input_dir_source,
        }


@dataclass
class ReferencePreparationResult:
    reference_path: str
    prepared_path: str = ""
    input_image: str = ""
    staged_input_path: str = ""
    staged_input_filename: str = ""
    comfyui_input_dir: str = ""
    runtime_dir: str = ""
    dry_run: bool = False
    matched_canonical_sampler: bool = False
    matched_canonical_settings: bool = False
    positive_prompt: str = ""
    negative_prompt: str = ""
    grow_mask_by: Any = None
    grow_mask_by_note: str = ""
    sampler_settings: dict[str, Any] = field(default_factory=dict)
    checkpoint: str = ""
    denoise: Any = None
    source_sha256: str = ""
    staged_sha256: str = ""
    alpha_mask_report: dict[str, Any] = field(default_factory=dict)
    resolved_paths: dict[str, Any] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_reference_runtime_paths(
    repo_root: Path,
    *,
    runtime_dir: Path | None = None,
    comfyui_input_dir: Path | None = None,
    bundle: RegistryBundle | None = None,
) -> ResolvedReferencePaths:
    """Resolve live runtime dirs using the same configured path system as prepare_workflow.py."""
    loaded = bundle or RegistryLoader(repo_root).load_all()
    if runtime_dir is not None:
        resolved_runtime = runtime_dir.resolve()
        runtime_source = "explicit --runtime-dir"
    else:
        resolved_runtime = loaded.path("runtime_workflows")
        runtime_source = "configs/paths/colab_paths.json:runtime_workflows"

    if comfyui_input_dir is not None:
        resolved_input = comfyui_input_dir.resolve()
        input_source = "explicit --comfyui-input-dir"
    else:
        resolved_input = loaded.path("comfyui_runtime") / "input"
        input_source = "configs/paths/colab_paths.json:comfyui_runtime/input"

    return ResolvedReferencePaths(
        runtime_dir=resolved_runtime,
        comfyui_input_dir=resolved_input,
        runtime_dir_source=runtime_source,
        comfyui_input_dir_source=input_source,
    )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _nodes_of_type(data: dict[str, Any], node_type: str) -> list[dict[str, Any]]:
    return [node for node in data.get("nodes", []) if isinstance(node, dict) and node.get("type") == node_type]


def _node_by_id(data: dict[str, Any], node_id: int) -> dict[str, Any] | None:
    for node in data.get("nodes", []):
        if isinstance(node, dict) and node.get("id") == node_id:
            return node
    return None


def _load_image_mask_connected(data: dict[str, Any]) -> bool:
    load_nodes = _nodes_of_type(data, "LoadImage")
    encode_nodes = _nodes_of_type(data, "VAEEncodeForInpaint")
    if len(load_nodes) != 1 or not encode_nodes:
        return False
    load_id = load_nodes[0].get("id")
    encode_ids = {node.get("id") for node in encode_nodes}
    image_ok = False
    mask_ok = False
    for link in data.get("links", []):
        if not isinstance(link, list) or len(link) < 5:
            continue
        _link_id, src_node, src_slot, dst_node, dst_slot = link[:5]
        if src_node != load_id or dst_node not in encode_ids:
            continue
        if src_slot == 0 and dst_slot == 0:
            image_ok = True
        if src_slot == 1 and dst_slot == 2:
            mask_ok = True
    return image_ok and mask_ok


def _clip_encode_pair(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    clip_nodes = _nodes_of_type(data, "CLIPTextEncode")
    if len(clip_nodes) != 2:
        return None
    samplers = _nodes_of_type(data, "KSampler")
    if len(samplers) != 1:
        ordered = sorted(clip_nodes, key=lambda node: int(node.get("id", 0)))
        return ordered[0], ordered[1]

    sampler_id = samplers[0].get("id")
    positive_id: int | None = None
    negative_id: int | None = None
    for link in data.get("links", []):
        if not isinstance(link, list) or len(link) < 5:
            continue
        _link_id, src_node, _src_slot, dst_node, dst_slot = link[:5]
        if dst_node != sampler_id:
            continue
        if dst_slot == 1:
            positive_id = src_node
        elif dst_slot == 2:
            negative_id = src_node

    by_id = {node.get("id"): node for node in clip_nodes}
    if positive_id in by_id and negative_id in by_id and positive_id != negative_id:
        return by_id[positive_id], by_id[negative_id]

    ordered = sorted(clip_nodes, key=lambda node: int(node.get("id", 0)))
    return ordered[0], ordered[1]


def prompt_texts(data: dict[str, Any]) -> tuple[str, str] | None:
    pair = _clip_encode_pair(data)
    if pair is None:
        return None
    positive, negative = pair
    positive_widgets = positive.get("widgets_values") or [""]
    negative_widgets = negative.get("widgets_values") or [""]
    return str(positive_widgets[0]), str(negative_widgets[0])


def _set_prompt_texts(data: dict[str, Any], *, positive: str | None, negative: str | None) -> None:
    pair = _clip_encode_pair(data)
    if pair is None:
        raise ValueError("Reference workflow must contain exactly two CLIPTextEncode nodes.")
    positive_node, negative_node = pair
    if positive is not None:
        positive_node["widgets_values"] = [positive]
    if negative is not None:
        negative_node["widgets_values"] = [negative]


def _patch_load_image_filename(data: dict[str, Any], filename: str) -> None:
    for node in _nodes_of_type(data, "LoadImage"):
        node["widgets_values"] = [filename, "image"]


def _copy_sampler_from_canonical(reference_data: dict[str, Any], canonical_data: dict[str, Any]) -> bool:
    canonical_sampler = next(iter(_nodes_of_type(canonical_data, "KSampler")), None)
    if canonical_sampler is None:
        return False
    widgets = canonical_sampler.get("widgets_values")
    if not isinstance(widgets, list) or len(widgets) < 7:
        return False
    for node in _nodes_of_type(reference_data, "KSampler"):
        node["widgets_values"] = list(widgets)
        return True
    return False


def _copy_prompts_from_canonical(reference_data: dict[str, Any], canonical_data: dict[str, Any]) -> bool:
    prompts = prompt_texts(canonical_data)
    if prompts is None:
        return False
    _set_prompt_texts(reference_data, positive=prompts[0], negative=prompts[1])
    return True


def sampler_widgets(data: dict[str, Any]) -> list[Any] | None:
    for node in _nodes_of_type(data, "KSampler"):
        widgets = node.get("widgets_values")
        if isinstance(widgets, list) and len(widgets) >= 7:
            return list(widgets[:7])
    return None


def sampler_settings(data: dict[str, Any]) -> dict[str, Any]:
    widgets = sampler_widgets(data)
    if widgets is None:
        return {}
    return {
        "seed": widgets[0],
        "control_after_generate": widgets[1],
        "steps": widgets[2],
        "cfg": widgets[3],
        "sampler_name": widgets[4],
        "scheduler": widgets[5],
        "denoise": widgets[6],
    }


def _checkpoint_name(data: dict[str, Any]) -> str | None:
    nodes = _nodes_of_type(data, "CheckpointLoaderSimple")
    if not nodes:
        return None
    widgets = nodes[0].get("widgets_values") or []
    return str(widgets[0]) if widgets else None


def _set_grow_mask_by(data: dict[str, Any], value: int) -> Any:
    nodes = _nodes_of_type(data, "VAEEncodeForInpaint")
    if not nodes:
        return None
    node = nodes[0]
    prior = node.get("widgets_values")
    node["widgets_values"] = [value]
    return prior


def _effective_grow_mask_by(data: dict[str, Any]) -> Any:
    nodes = _nodes_of_type(data, "VAEEncodeForInpaint")
    if not nodes:
        return None
    widgets = nodes[0].get("widgets_values")
    if isinstance(widgets, list) and widgets:
        return widgets[0]
    return None


def _validate_prepared_reference(
    data: dict[str, Any],
    *,
    expected_positive: str,
    expected_negative: str,
) -> list[str]:
    errors: list[str] = []
    load_nodes = _nodes_of_type(data, "LoadImage")
    if len(load_nodes) != 1:
        errors.append("Prepared reference must contain exactly one LoadImage node.")
    if _nodes_of_type(data, "LoadImageMask"):
        errors.append("Prepared reference must not contain LoadImageMask.")
    if not _load_image_mask_connected(data):
        errors.append("Prepared reference LoadImage must supply both IMAGE and MASK to VAEEncodeForInpaint.")
    checkpoint = _checkpoint_name(data)
    if checkpoint != INPAINTING_CANONICAL_CHECKPOINT:
        errors.append(
            f"Prepared reference checkpoint must be {INPAINTING_CANONICAL_CHECKPOINT!r}; found {checkpoint!r}."
        )
    settings = sampler_settings(data)
    if settings.get("denoise") != INPAINTING_CANONICAL_DENOISE:
        errors.append(
            f"Prepared reference denoise must be {INPAINTING_CANONICAL_DENOISE}; found {settings.get('denoise')!r}."
        )
    prompts = prompt_texts(data)
    if prompts is None:
        errors.append("Prepared reference must contain exactly two usable CLIPTextEncode nodes.")
    else:
        positive, negative = prompts
        if positive != expected_positive:
            errors.append("Prepared positive prompt does not match requested value.")
        if negative != expected_negative:
            errors.append("Prepared negative prompt does not match requested value.")
    return errors


def prepare_inpainting_reference(
    repo_root: Path,
    runtime_dir: Path,
    *,
    input_path: Path,
    comfyui_input_dir: Path,
    dry_run: bool = False,
    match_canonical_sampler: bool = False,
    match_canonical_settings: bool = False,
    positive_prompt: str | None = None,
    negative_prompt: str | None = None,
    set_grow_mask_by: int | None = CONTROLLED_GROW_MASK_BY,
    resolved_paths: ResolvedReferencePaths | None = None,
    reference_workflow_path: Path | None = None,
) -> ReferencePreparationResult:
    reference_path = reference_workflow_path or (repo_root / REFERENCE_INPAINTING_PATH)
    result = ReferencePreparationResult(
        reference_path=str(reference_path),
        input_image=str(input_path),
        comfyui_input_dir=str(comfyui_input_dir),
        runtime_dir=str(runtime_dir),
        dry_run=dry_run,
    )
    if resolved_paths is not None:
        result.resolved_paths = resolved_paths.to_dict()
        result.messages.append(
            f"Resolved ComfyUI input dir: {resolved_paths.comfyui_input_dir} ({resolved_paths.comfyui_input_dir_source})"
        )
        result.messages.append(
            f"Resolved prepared workflow dir: {resolved_paths.runtime_dir} ({resolved_paths.runtime_dir_source})"
        )

    if not reference_path.is_file():
        result.errors.append(f"Reference workflow missing: {reference_path}")
        return result

    ok, error = validate_input_path(input_path)
    if not ok and error:
        result.errors.append(error)
        return result

    data = _load_json(reference_path)
    load_nodes = _nodes_of_type(data, "LoadImage")
    mask_nodes = _nodes_of_type(data, "LoadImageMask")
    if len(load_nodes) != 1:
        result.errors.append("Reference workflow must contain exactly one LoadImage node.")
        return result
    if mask_nodes:
        result.errors.append("Reference workflow must not contain LoadImageMask.")
        return result
    if not _load_image_mask_connected(data):
        result.errors.append("Reference LoadImage must supply both IMAGE and MASK to VAEEncodeForInpaint.")
        return result
    if _clip_encode_pair(data) is None:
        result.errors.append("Reference workflow must contain exactly two usable CLIPTextEncode nodes.")
        return result

    alpha_report = analyze_mask(input_path, channel="alpha")
    result.alpha_mask_report = alpha_report.to_dict()
    if alpha_report.errors:
        result.errors.extend(alpha_report.errors)
        return result
    if alpha_report.classification == "all_black":
        result.errors.append(
            "RGBA input has no transparent inpaint region under ComfyUI LoadImage MASK semantics."
        )
        return result

    source_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    result.source_sha256 = source_hash

    prior_grow = _effective_grow_mask_by(data)
    if prior_grow is None:
        result.messages.append(
            "Extracted reference omits grow_mask_by serialization; modern ComfyUI node default is expected to be 6."
        )

    canonical_path = repo_root / CANONICAL_INPAINTING_PATH
    canonical_data: dict[str, Any] | None = None
    if match_canonical_settings or match_canonical_sampler:
        if not canonical_path.is_file():
            result.errors.append(f"Canonical workflow missing for alignment: {canonical_path}")
            return result
        canonical_data = _load_json(canonical_path)

    if match_canonical_settings:
        assert canonical_data is not None
        if not _copy_sampler_from_canonical(data, canonical_data):
            result.errors.append("Unable to copy KSampler widgets from canonical workflow.")
            return result
        if positive_prompt is None or negative_prompt is None:
            if not _copy_prompts_from_canonical(data, canonical_data):
                result.errors.append("Unable to copy prompts from canonical workflow.")
                return result
        result.matched_canonical_settings = True
        result.matched_canonical_sampler = True
        result.messages.append("Aligned sampler and unset prompts with canonical workflow for A/B comparison.")
    elif match_canonical_sampler:
        assert canonical_data is not None
        if not _copy_sampler_from_canonical(data, canonical_data):
            result.errors.append("Unable to copy KSampler widgets from canonical workflow.")
            return result
        result.matched_canonical_sampler = True
        result.messages.append("Aligned KSampler widgets with canonical workflow for A/B comparison.")

    try:
        if positive_prompt is not None or negative_prompt is not None:
            _set_prompt_texts(data, positive=positive_prompt, negative=negative_prompt)
            if positive_prompt is not None:
                result.messages.append(f"Applied positive prompt override: {positive_prompt}")
            if negative_prompt is not None:
                result.messages.append(f"Applied negative prompt override: {negative_prompt}")
    except ValueError as exc:
        result.errors.append(str(exc))
        return result

    if set_grow_mask_by is not None:
        _set_grow_mask_by(data, set_grow_mask_by)
        result.grow_mask_by = set_grow_mask_by
        result.grow_mask_by_note = (
            f"Temporary prepared reference sets grow_mask_by={set_grow_mask_by} "
            "(extracted reference JSON left unchanged)."
        )
        result.messages.append(result.grow_mask_by_note)
    else:
        result.grow_mask_by = _effective_grow_mask_by(data)
        if result.grow_mask_by is None:
            result.grow_mask_by_note = "Relying on live ComfyUI VAEEncodeForInpaint default (expected 6)."
        else:
            result.grow_mask_by_note = f"Using serialized grow_mask_by={result.grow_mask_by}."
        result.messages.append(result.grow_mask_by_note)

    final_prompts = prompt_texts(data)
    if final_prompts is None:
        result.errors.append("Reference workflow must contain exactly two usable CLIPTextEncode nodes.")
        return result
    result.positive_prompt, result.negative_prompt = final_prompts
    result.sampler_settings = sampler_settings(data)
    result.checkpoint = _checkpoint_name(data) or ""
    result.denoise = result.sampler_settings.get("denoise")

    validation_errors = _validate_prepared_reference(
        data,
        expected_positive=result.positive_prompt,
        expected_negative=result.negative_prompt,
    )
    if validation_errors:
        result.errors.extend(validation_errors)
        return result

    staged = stage_input_file(input_path, comfyui_input_dir, dry_run=dry_run)
    result.staged_input_path = str(staged.staged_path)
    result.staged_input_filename = staged.staged_filename
    result.messages.append(staged.message)

    if not dry_run:
        staged_hash = hashlib.sha256(Path(staged.staged_path).read_bytes()).hexdigest()
        result.staged_sha256 = staged_hash
        if source_hash != staged_hash:
            result.errors.append("Staged RGBA file hash does not match source; alpha may have been altered.")
            return result
        result.messages.append(f"Preserved embedded alpha mask (sha256={source_hash[:12]}...).")
    else:
        result.staged_sha256 = source_hash
        result.messages.append(f"Dry-run would preserve embedded alpha mask (sha256={source_hash[:12]}...).")

    _patch_load_image_filename(data, staged.staged_filename)

    # Re-validate prompts/topology after filename patch (topology unchanged).
    validation_errors = _validate_prepared_reference(
        data,
        expected_positive=result.positive_prompt,
        expected_negative=result.negative_prompt,
    )
    if validation_errors:
        result.errors.extend(validation_errors)
        return result

    timestamp = utc_collision_timestamp()
    prepared_path = runtime_dir / f"reference_inpainting_official_{timestamp}.json"
    result.prepared_path = str(prepared_path)
    if dry_run:
        result.messages.append(f"Dry-run prepared path: {prepared_path}")
        return result

    runtime_dir.mkdir(parents=True, exist_ok=True)
    prepared_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    result.messages.append(f"Wrote prepared reference workflow: {prepared_path}")
    return result
