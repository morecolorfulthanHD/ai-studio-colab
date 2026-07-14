#!/usr/bin/env python3
"""Shared helpers for modern editing benchmark workflow preparation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .input_staging import stage_input_file
from .input_utils import validate_input_path
from .output_sync import utc_collision_timestamp
from .registry_loader import RegistryBundle, RegistryLoader


@dataclass
class ModernEditingPrepResult:
    candidate: str
    reference_path: str
    prepared_path: str = ""
    input_image: str = ""
    mask_image: str = ""
    reference_image: str = ""
    staged_input_path: str = ""
    staged_mask_path: str = ""
    staged_reference_path: str = ""
    staged_input_filename: str = ""
    staged_mask_filename: str = ""
    positive_prompt: str = ""
    comfyui_input_dir: str = ""
    runtime_dir: str = ""
    dry_run: bool = False
    required_models: list[str] = field(default_factory=list)
    missing_models: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_runtime_dirs(
    repo_root: Path,
    *,
    runtime_dir: Path | None = None,
    comfyui_input_dir: Path | None = None,
    bundle: RegistryBundle | None = None,
) -> tuple[Path, Path]:
    loaded = bundle or RegistryLoader(repo_root).load_all()
    resolved_runtime = runtime_dir.resolve() if runtime_dir else loaded.path("runtime_workflows")
    resolved_input = (
        comfyui_input_dir.resolve() if comfyui_input_dir else loaded.path("comfyui_runtime") / "input"
    )
    return resolved_runtime, resolved_input


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _iter_nodes(data: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [node for node in data.get("nodes", []) if isinstance(node, dict)]
    for subgraph in (data.get("definitions") or {}).get("subgraphs") or []:
        if isinstance(subgraph, dict):
            nodes.extend(node for node in subgraph.get("nodes", []) if isinstance(node, dict))
    return nodes


def verify_required_model_files(bundle: RegistryBundle, model_names: list[str]) -> tuple[list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    by_name = {entry.get("name"): entry for entry in bundle.models}
    for name in model_names:
        entry = by_name.get(name)
        if entry is None:
            missing.append(name)
            continue
        runtime = entry.get("runtime_path")
        if runtime and Path(runtime).is_file():
            present.append(name)
        else:
            missing.append(name)
    return present, missing


def _patch_load_image_filenames(data: dict[str, Any], filenames: list[str]) -> int:
    patched = 0
    index = 0
    for node in data.get("nodes", []):
        if not isinstance(node, dict) or node.get("type") != "LoadImage":
            continue
        if index >= len(filenames):
            break
        node["widgets_values"] = [filenames[index], "image"]
        patched += 1
        index += 1
    return patched


def _patch_primary_positive_prompt(data: dict[str, Any], prompt: str) -> bool:
    # Prefer Qwen edit text encoder nodes inside subgraphs.
    for node in _iter_nodes(data):
        node_type = str(node.get("type") or "")
        widgets = node.get("widgets_values")
        if not isinstance(widgets, list) or not widgets:
            continue
        if node_type in {"TextEncodeQwenImageEditPlus", "CLIPTextEncode"} and isinstance(widgets[0], str):
            # For dual CLIPTextEncode graphs, patch the first positive-looking node (order-based).
            widgets[0] = prompt
            node["widgets_values"] = widgets
            if node_type == "TextEncodeQwenImageEditPlus":
                return True
            # Keep scanning; last CLIPTextEncode may be negative — only first is patched.
            return True
    return False


def prepare_modern_editing_workflow(
    repo_root: Path,
    *,
    candidate: str,
    reference_relpath: str,
    required_models: list[str],
    input_path: Path,
    runtime_dir: Path,
    comfyui_input_dir: Path,
    positive_prompt: str,
    mask_path: Path | None = None,
    reference_image_path: Path | None = None,
    dry_run: bool = False,
    require_models: bool = True,
) -> ModernEditingPrepResult:
    reference_path = repo_root / reference_relpath
    result = ModernEditingPrepResult(
        candidate=candidate,
        reference_path=str(reference_path),
        input_image=str(input_path),
        positive_prompt=positive_prompt,
        comfyui_input_dir=str(comfyui_input_dir),
        runtime_dir=str(runtime_dir),
        dry_run=dry_run,
        required_models=list(required_models),
    )
    if mask_path is not None:
        result.mask_image = str(mask_path)
    if reference_image_path is not None:
        result.reference_image = str(reference_image_path)

    if not reference_path.is_file():
        result.errors.append(f"Reference workflow missing: {reference_path}")
        return result

    ok, error = validate_input_path(input_path)
    if not ok and error:
        result.errors.append(error)
        return result
    if mask_path is not None:
        mask_ok, mask_error = validate_input_path(mask_path)
        if not mask_ok and mask_error:
            result.errors.append(mask_error)
            return result
    if reference_image_path is not None:
        ref_ok, ref_error = validate_input_path(reference_image_path)
        if not ref_ok and ref_error:
            result.errors.append(ref_error)
            return result

    bundle = RegistryLoader(repo_root).load_all()
    present, missing = verify_required_model_files(bundle, required_models)
    result.missing_models = missing
    if missing:
        msg = (
            "Missing required model files (manual download required; no auto-download): "
            + ", ".join(missing)
        )
        if require_models:
            result.errors.append(msg)
            return result
        result.messages.append("WARNING: " + msg)
    else:
        result.messages.append(f"Verified required models present: {', '.join(present)}")

    data = _load_json(reference_path)
    source_hash = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    result.messages.append(f"Reference workflow hash (unchanged source): {source_hash[:16]}...")

    staged_input = stage_input_file(input_path, comfyui_input_dir, dry_run=dry_run)
    result.staged_input_path = str(staged_input.staged_path)
    result.staged_input_filename = staged_input.staged_filename
    result.messages.append(staged_input.message)

    filenames = [staged_input.staged_filename]
    if reference_image_path is not None:
        staged_ref = stage_input_file(reference_image_path, comfyui_input_dir, dry_run=dry_run)
        result.staged_reference_path = str(staged_ref.staged_path)
        filenames.append(staged_ref.staged_filename)
        result.messages.append(staged_ref.message)
    if mask_path is not None:
        staged_mask = stage_input_file(mask_path, comfyui_input_dir, dry_run=dry_run)
        result.staged_mask_path = str(staged_mask.staged_path)
        result.staged_mask_filename = staged_mask.staged_filename
        result.messages.append(staged_mask.message)
        # Separate LoadImageMask workflows are uncommon for flux fill alpha path;
        # if an extra LoadImage exists, stage into next LoadImage slot only when unused.

    patched = _patch_load_image_filenames(data, filenames)
    if patched < 1:
        result.errors.append("Unable to patch LoadImage filename in reference workflow.")
        return result
    if not _patch_primary_positive_prompt(data, positive_prompt):
        result.errors.append("Unable to locate a primary positive prompt node to patch.")
        return result
    result.messages.append(f"Patched {patched} LoadImage node(s) and positive prompt.")

    timestamp = utc_collision_timestamp()
    prepared_path = runtime_dir / f"{candidate}_{timestamp}.json"
    result.prepared_path = str(prepared_path)
    if dry_run:
        result.messages.append(f"Dry-run prepared path: {prepared_path}")
        return result

    runtime_dir.mkdir(parents=True, exist_ok=True)
    prepared_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    # Ensure source reference file bytes were not modified.
    if hashlib.sha256(reference_path.read_bytes()).hexdigest() != source_hash:
        result.errors.append("Reference workflow changed on disk during preparation.")
        return result
    result.messages.append(f"Wrote prepared workflow: {prepared_path}")
    return result
