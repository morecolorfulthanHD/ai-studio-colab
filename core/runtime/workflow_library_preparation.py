#!/usr/bin/env python3
"""Workflow library preparation engine (Package 4.8)."""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .input_staging import stage_inputs_batch
from .output_sync import utc_collision_timestamp
from .prepared_workflow_index import append_preparation_record, preparations_log_path
from .project_workspace import ProjectManifest
from .workflow_manifest import (
    load_workflow_manifest,
    validate_manifest_against_canonical,
    validate_manifest_structure,
    workflow_id_for_identifier,
)
from .workflow_parameters import IMAGE_PARAM_TYPES, apply_parameter_bindings, coerce_and_validate_parameters
from .workflow_provenance import hash_ui_workflow
from .workflow_readiness import (
    READINESS_BLOCKED,
    READINESS_BENCHMARK_ONLY,
    READINESS_EXPERIMENTAL,
    evaluate_workflow_readiness,
)

PACKAGE_VERSION = "4.8"


@dataclass
class LibraryPreparationResult:
    preparation_id: str = ""
    workflow_identifier: str = ""
    workflow_id: str = ""
    readiness_status: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    canonical_workflow_hash: str = ""
    prepared_workflow_hash: str = ""
    runtime_prepared_dir: str = ""
    runtime_workflow_path: str = ""
    runtime_metadata_path: str = ""
    runtime_manifest_path: str = ""
    drive_prepared_dir: str = ""
    project_prepared_dir: str = ""
    staged_filenames: dict[str, str] = field(default_factory=dict)
    dry_run: bool = False
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _allocate_preparation_id(runtime_prepared_root: Path) -> str:
    for _ in range(8):
        preparation_id = f"prep_{uuid.uuid4()}"
        if not (runtime_prepared_root / preparation_id).exists():
            return preparation_id
    raise RuntimeError("Unable to allocate unique preparation_id")


def _validate_allowed_path(path: Path, allowed_roots: list[Path]) -> str | None:
    resolved = path.resolve()
    for root in allowed_roots:
        try:
            root_resolved = root.resolve()
        except OSError:
            continue
        if not root_resolved.is_dir():
            continue
        try:
            resolved.relative_to(root_resolved)
            return None
        except ValueError:
            continue
    return f"Input path not under allowed roots: {resolved}"


def _cross_parameter_rules(
    workflow_identifier: str,
    params: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if workflow_identifier == "base/outpainting":
        sides = ("left", "right", "top", "bottom")
        if all(int(params.get(side) or 0) == 0 for side in sides):
            errors.append("Outpainting requires at least one expansion side greater than zero.")
    if workflow_identifier == "base/inpainting":
        mask = params.get("mask_image")
        if not mask:
            errors.append("Inpainting requires mask_image parameter.")
    return errors


def _collect_image_paths(
    schema: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for param_name, spec in (schema or {}).items():
        if not isinstance(spec, dict):
            continue
        if str(spec.get("type") or "") not in IMAGE_PARAM_TYPES:
            continue
        value = params.get(param_name)
        if value:
            paths[param_name] = Path(str(value))
    return paths


def _stage_image_parameters(
    *,
    schema: dict[str, Any],
    params: dict[str, Any],
    comfyui_input_dir: Path,
    dry_run: bool,
    timestamp: str,
) -> tuple[dict[str, str], list[str], list[str]]:
    """Stage image/mask/file params; return staged basenames, messages, errors."""
    messages: list[str] = []
    errors: list[str] = []
    staged: dict[str, str] = {}

    source_param = None
    mask_param = None
    for param_name, spec in (schema or {}).items():
        if not isinstance(spec, dict):
            continue
        param_type = str(spec.get("type") or "")
        if param_type == "image" and source_param is None:
            source_param = param_name
        elif param_type == "mask" and mask_param is None:
            mask_param = param_name

    if source_param and params.get(source_param):
        source_path = Path(str(params[source_param]))
        mask_path = Path(str(params[mask_param])) if mask_param and params.get(mask_param) else None
        staged_source, staged_mask = stage_inputs_batch(
            source_path,
            comfyui_input_dir,
            mask=mask_path,
            dry_run=dry_run,
            timestamp=timestamp,
        )
        staged[source_param] = staged_source.staged_filename
        messages.append(staged_source.message)
        if staged_mask is not None:
            staged[mask_param or "mask"] = staged_mask.staged_filename
            if staged_mask.message != staged_source.message:
                messages.append(staged_mask.message)
        return staged, messages, errors

    for param_name, spec in (schema or {}).items():
        if not isinstance(spec, dict):
            continue
        if str(spec.get("type") or "") not in IMAGE_PARAM_TYPES:
            continue
        value = params.get(param_name)
        if not value:
            continue
        from .input_staging import stage_input_file

        file_path = Path(str(value))
        result = stage_input_file(
            file_path,
            comfyui_input_dir,
            dry_run=dry_run,
            timestamp=timestamp,
        )
        staged[param_name] = result.staged_filename
        messages.append(result.message)

    return staged, messages, errors


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _copy_preparation_tree(source_dir: Path, dest_dir: Path) -> None:
    if dest_dir.exists():
        raise FileExistsError(f"Destination already exists: {dest_dir}")
    shutil.copytree(source_dir, dest_dir)


def prepare_library_workflow(
    repo_root: Path,
    *,
    workflow_identifier: str,
    parameters: dict[str, Any] | None = None,
    runtime_prepared_root: Path,
    drive_prepared_root: Path,
    comfyui_input_dir: Path,
    drive_root: Path,
    active_project: ProjectManifest | None = None,
    allow_experimental: bool = False,
    allow_benchmark: bool = False,
    dry_run: bool = False,
    allowed_input_roots: list[Path] | None = None,
    comfy_object_info: dict[str, Any] | None = None,
    model_files_present: dict[str, bool] | None = None,
) -> LibraryPreparationResult:
    """Prepare a library workflow with parameter bindings and staged inputs."""
    repo_root = repo_root.resolve()
    result = LibraryPreparationResult(dry_run=dry_run)

    try:
        manifest = load_workflow_manifest(repo_root, workflow_identifier)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        result.errors.append(str(exc))
        return result

    identifier = str(manifest.get("_workflow_identifier") or manifest.get("workflow_identifier") or "")
    result.workflow_identifier = identifier
    result.workflow_id = workflow_id_for_identifier(identifier)

    structure_errors = validate_manifest_structure(manifest)
    if structure_errors:
        result.errors.extend(structure_errors)
        return result

    hash_errors = validate_manifest_against_canonical(repo_root, manifest)
    if hash_errors:
        result.errors.extend(hash_errors)
        return result

    schema = manifest.get("parameter_schema") or {}
    defaults = manifest.get("default_parameters") or {}
    params, param_errors = coerce_and_validate_parameters(schema, defaults, parameters)
    if param_errors:
        result.errors.extend(param_errors)
        return result
    result.parameters = params

    cross_errors = _cross_parameter_rules(identifier, params)
    if cross_errors:
        result.errors.extend(cross_errors)
        return result

    allowed_roots = [p.resolve() for p in (allowed_input_roots or [])]
    for param_name, path in _collect_image_paths(schema, params).items():
        if not path.is_file():
            result.errors.append(f"Parameter file not found: {param_name}={path}")
            continue
        if allowed_roots:
            path_error = _validate_allowed_path(path, allowed_roots)
            if path_error:
                result.errors.append(path_error)

    if result.errors:
        return result

    readiness = evaluate_workflow_readiness(
        repo_root,
        identifier,
        allow_experimental=allow_experimental,
        allow_benchmark=allow_benchmark,
        parameters=params,
        comfy_object_info=comfy_object_info,
        model_files_present=model_files_present,
    )
    result.readiness_status = readiness.status
    if readiness.status == READINESS_BLOCKED:
        result.errors.extend(readiness.reasons or ["workflow readiness blocked"])
        return result
    gate_reasons = [r for r in readiness.reasons if "requires --allow" in r]
    if gate_reasons:
        result.errors.extend(gate_reasons)
        return result
    blocking_reasons = [
        r
        for r in readiness.reasons
        if not r.startswith("node availability not checked")
    ]
    if blocking_reasons:
        result.errors.extend(blocking_reasons)
        return result

    canonical_rel = str(manifest.get("canonical_workflow_path") or "")
    canonical_path = repo_root / canonical_rel
    try:
        canonical_data = json.loads(canonical_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.errors.append(f"Cannot load canonical workflow: {exc}")
        return result

    canonical_hash = hash_ui_workflow(canonical_data)
    result.canonical_workflow_hash = canonical_hash

    preparation_id = _allocate_preparation_id(runtime_prepared_root)
    result.preparation_id = preparation_id
    operation_ts = utc_collision_timestamp()

    staged_filenames, stage_messages, stage_errors = _stage_image_parameters(
        schema=schema,
        params=params,
        comfyui_input_dir=comfyui_input_dir,
        dry_run=dry_run,
        timestamp=operation_ts,
    )
    result.messages.extend(stage_messages)
    if stage_errors:
        result.errors.extend(stage_errors)
        return result

    params_with_staged = dict(params)
    for param_name, filename in staged_filenames.items():
        params_with_staged[param_name] = filename
    result.staged_filenames = dict(staged_filenames)

    prepared_data = apply_parameter_bindings(copy.deepcopy(canonical_data), schema, params_with_staged)
    prepared_data.setdefault("extra", {})
    if isinstance(prepared_data["extra"], dict):
        prepared_data["extra"]["ai_studio"] = {
            "workflow_identifier": identifier,
            "workflow_id": result.workflow_id,
            "workflow_source": "registered_canonical",
            "preparation_id": preparation_id,
            "prepared_workflow_hash": "",
            "canonical_workflow_hash": canonical_hash,
            "package_version": PACKAGE_VERSION,
        }

    prepared_hash = hash_ui_workflow(prepared_data)
    result.prepared_workflow_hash = prepared_hash
    if isinstance(prepared_data.get("extra"), dict) and isinstance(
        prepared_data["extra"].get("ai_studio"), dict
    ):
        prepared_data["extra"]["ai_studio"]["prepared_workflow_hash"] = prepared_hash

    runtime_dir = runtime_prepared_root / preparation_id
    result.runtime_prepared_dir = str(runtime_dir)
    workflow_filename = f"{preparation_id}.workflow.json"
    metadata_filename = f"{preparation_id}.metadata.json"
    manifest_filename = f"{preparation_id}.manifest.json"
    result.runtime_workflow_path = str(runtime_dir / workflow_filename)
    result.runtime_metadata_path = str(runtime_dir / metadata_filename)
    result.runtime_manifest_path = str(runtime_dir / manifest_filename)

    drive_dir = drive_prepared_root / preparation_id
    result.drive_prepared_dir = str(drive_dir)
    project_dir = ""
    if active_project is not None:
        project_dir = str(
            drive_root / "projects" / active_project.slug / "workflows" / "prepared" / preparation_id
        )
        result.project_prepared_dir = project_dir

    metadata_payload = {
        "schema_version": 1,
        "preparation_id": preparation_id,
        "created_timestamp": operation_ts,
        "workflow_identifier": identifier,
        "canonical_workflow_path": canonical_rel or None,
        "canonical_workflow_hash": canonical_hash,
        "prepared_workflow_hash": prepared_hash,
        "capability": manifest.get("capability") or None,
        "project_id": (active_project.project_id if active_project is not None else None),
        "project_slug": (active_project.slug if active_project is not None else None),
        "parameters": params,
        "staged_inputs": {
            name: {
                "source_path": str(params.get(name) or "") or None,
                "staged_filename": filename,
            }
            for name, filename in staged_filenames.items()
        },
        "required_models": list(manifest.get("required_model_files") or []),
        "required_nodes": list(manifest.get("required_nodes") or []),
        "readiness_status": readiness.status,
        "experimental_acknowledged": bool(allow_experimental),
        "benchmark_acknowledged": bool(allow_benchmark),
        "runtime_id": None,
        "repository_commit": None,
        "package_version": PACKAGE_VERSION,
        "prepared_runtime_path": str(runtime_dir),
        "prepared_drive_path": str(drive_dir),
        "prepared_project_path": project_dir or None,
        "workflow_id": result.workflow_id,
        "workflow_source": "registered_canonical",
        "staged_filenames": staged_filenames,
        "dry_run": dry_run,
    }

    manifest_payload = {
        "schema_version": 1,
        "package_version": PACKAGE_VERSION,
        "preparation_id": preparation_id,
        "workflow_identifier": identifier,
        "workflow_file": workflow_filename,
        "metadata_file": metadata_filename,
        "prepared_workflow_hash": prepared_hash,
        "canonical_workflow_hash": canonical_hash,
        "created_timestamp": operation_ts,
    }

    if dry_run:
        result.messages.append("Dry run only — no files written or copied.")
        return result

    runtime_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=".wfprep_", dir=str(runtime_prepared_root)))
    try:
        _atomic_write_json(temp_dir / workflow_filename, prepared_data)
        _atomic_write_json(temp_dir / metadata_filename, metadata_payload)
        for name in (workflow_filename, metadata_filename):
            src = temp_dir / name
            dst = runtime_dir / name
            if dst.exists():
                dst.unlink()
            src.replace(dst)
        _atomic_write_json(runtime_dir / manifest_filename, manifest_payload)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    drive_prepared_root.mkdir(parents=True, exist_ok=True)
    _copy_preparation_tree(runtime_dir, drive_dir)
    result.messages.append(f"Drive prepared copy: {drive_dir}")

    if active_project is not None and project_dir:
        project_path = Path(project_dir)
        project_path.parent.mkdir(parents=True, exist_ok=True)
        _copy_preparation_tree(runtime_dir, project_path)
        result.messages.append(f"Project prepared copy: {project_path}")

    log_path = preparations_log_path(drive_root)
    append_preparation_record(
        log_path,
        {
            "preparation_id": preparation_id,
            "workflow_identifier": identifier,
            "created_timestamp": operation_ts,
            "project_id": (active_project.project_id if active_project is not None else None),
            "project_slug": (active_project.slug if active_project is not None else None),
            "prepared_workflow_path": result.runtime_workflow_path,
            "prepared_drive_path": result.drive_prepared_dir,
            "prepared_project_path": result.project_prepared_dir or None,
            "runtime_prepared_dir": result.runtime_prepared_dir,
            "drive_prepared_dir": result.drive_prepared_dir,
            "project_prepared_dir": result.project_prepared_dir or None,
            "readiness_status": readiness.status,
            "parameter_summary": {
                key: params.get(key)
                for key in (
                    "positive_prompt",
                    "seed",
                    "steps",
                    "cfg",
                    "width",
                    "height",
                    "denoise",
                    "checkpoint",
                )
                if key in params
            },
            "prepared_workflow_hash": prepared_hash,
            "canonical_workflow_hash": canonical_hash,
            "workflow_id": result.workflow_id,
            "package_version": PACKAGE_VERSION,
        },
    )
    result.messages.append(f"Appended preparation record to {log_path}")
    return result
