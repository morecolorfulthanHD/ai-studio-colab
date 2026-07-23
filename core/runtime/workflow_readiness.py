#!/usr/bin/env python3
"""Workflow library readiness evaluation (Package 4.8)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .registry_loader import RegistryLoader
from .runtime_health import _model_present
from .workflow_manifest import (
    load_workflow_manifest,
    validate_manifest_against_canonical,
    validate_manifest_structure,
)
from .workflow_parameters import IMAGE_PARAM_TYPES

READINESS_READY = "ready"
READINESS_PARTIAL = "partial"
READINESS_BLOCKED = "blocked"
READINESS_EXPERIMENTAL = "experimental"
READINESS_BENCHMARK_ONLY = "benchmark_only"


@dataclass
class ReadinessResult:
    status: str
    reasons: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_model_filename(repo_root: Path, filename: str, bundle: Any | None) -> list[Path]:
    paths: list[Path] = []
    if bundle is not None:
        try:
            drive_models = bundle.path("drive_models")
            paths.append(drive_models / "checkpoints" / filename)
        except KeyError:
            pass
        for entry in bundle.models:
            intended = str(entry.get("intended_path") or "")
            if intended.endswith(filename) or Path(intended).name == filename:
                paths.append(repo_root / intended)
                runtime = entry.get("runtime_path")
                if runtime:
                    paths.append(Path(runtime))
    paths.append(repo_root / "models" / filename)
    return paths


def _model_file_present(
    repo_root: Path,
    filename: str,
    *,
    model_files_present: dict[str, bool] | None,
    bundle: Any | None,
) -> bool:
    if model_files_present is not None and filename in model_files_present:
        return bool(model_files_present[filename])
    for path in _resolve_model_filename(repo_root, filename, bundle):
        if _model_present(path):
            return True
    return False


def _check_required_nodes(
    required_nodes: list[str],
    comfy_object_info: dict[str, Any] | None,
) -> tuple[list[str], list[str]]:
    if comfy_object_info is None:
        return [], ["node availability not checked (object_info unavailable)"]
    available = set(comfy_object_info.keys())
    missing = [node for node in required_nodes if node not in available]
    return missing, []


def evaluate_workflow_readiness(
    repo_root: Path,
    workflow_identifier: str,
    *,
    allow_experimental: bool = False,
    allow_benchmark: bool = False,
    parameters: dict[str, Any] | None = None,
    comfy_object_info: dict[str, Any] | None = None,
    model_files_present: dict[str, bool] | None = None,
) -> ReadinessResult:
    """Evaluate whether a library workflow is ready to prepare."""
    repo_root = repo_root.resolve()
    reasons: list[str] = []
    details: dict[str, Any] = {"workflow_identifier": workflow_identifier}

    try:
        manifest = load_workflow_manifest(repo_root, workflow_identifier)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return ReadinessResult(
            status=READINESS_BLOCKED,
            reasons=[str(exc)],
            details=details,
        )

    identifier = str(manifest.get("_workflow_identifier") or manifest.get("workflow_identifier") or "")
    details["workflow_identifier"] = identifier
    details["production_status"] = manifest.get("production_status")
    details["requires_experimental"] = manifest.get("requires_experimental")
    details["requires_benchmark"] = manifest.get("requires_benchmark")

    structure_errors = validate_manifest_structure(manifest)
    if structure_errors:
        reasons.extend(structure_errors)
        return ReadinessResult(status=READINESS_BLOCKED, reasons=reasons, details=details)

    hash_errors = validate_manifest_against_canonical(repo_root, manifest)
    if hash_errors:
        reasons.extend(hash_errors)

    production_status = str(manifest.get("production_status") or "")
    if production_status == READINESS_BENCHMARK_ONLY:
        if not allow_benchmark:
            reasons.append("benchmark-only workflow requires --allow-benchmark")
            return ReadinessResult(status=READINESS_BENCHMARK_ONLY, reasons=reasons, details=details)
    elif production_status == READINESS_EXPERIMENTAL or manifest.get("requires_experimental"):
        if not allow_experimental:
            reasons.append("experimental workflow requires --allow-experimental")
            return ReadinessResult(status=READINESS_EXPERIMENTAL, reasons=reasons, details=details)

    supported_envs = manifest.get("supported_environments") or []
    if "colab" not in supported_envs:
        reasons.append("workflow does not list colab in supported_environments")

    bundle = None
    try:
        bundle = RegistryLoader(repo_root).load_all()
    except (FileNotFoundError, ValueError):
        pass

    required_models = manifest.get("required_model_files") or []
    missing_models: list[str] = []
    model_status: dict[str, bool] = {}
    for filename in required_models:
        present = _model_file_present(
            repo_root,
            str(filename),
            model_files_present=model_files_present,
            bundle=bundle,
        )
        model_status[str(filename)] = present
        if not present:
            missing_models.append(str(filename))
    details["model_files"] = model_status
    if missing_models:
        reasons.append(f"missing required model files: {', '.join(missing_models)}")

    required_nodes = manifest.get("required_nodes") or []
    missing_nodes, node_notes = _check_required_nodes(required_nodes, comfy_object_info)
    details["missing_nodes"] = missing_nodes
    if node_notes:
        details["node_check_notes"] = node_notes
    if missing_nodes:
        reasons.append(f"missing required nodes: {', '.join(missing_nodes)}")

    if parameters:
        schema = manifest.get("parameter_schema") or {}
        for param_name, spec in schema.items():
            if not isinstance(spec, dict):
                continue
            if str(spec.get("type") or "") not in IMAGE_PARAM_TYPES:
                continue
            value = parameters.get(param_name)
            if value and isinstance(value, (str, Path)):
                path = Path(str(value))
                if not path.is_file():
                    reasons.append(f"parameter file missing: {param_name}={path}")

    if hash_errors:
        return ReadinessResult(status=READINESS_BLOCKED, reasons=reasons, details=details)

    if production_status == READINESS_BENCHMARK_ONLY:
        status = READINESS_BENCHMARK_ONLY if not reasons else READINESS_BLOCKED
        return ReadinessResult(status=status, reasons=reasons, details=details)

    if production_status == READINESS_EXPERIMENTAL or manifest.get("requires_experimental"):
        status = READINESS_EXPERIMENTAL if not reasons else READINESS_PARTIAL
        return ReadinessResult(status=status, reasons=reasons, details=details)

    if missing_nodes and comfy_object_info is None:
        status = READINESS_PARTIAL if not missing_models else READINESS_BLOCKED
    elif missing_models or missing_nodes:
        status = READINESS_PARTIAL if not missing_models else READINESS_BLOCKED
    elif reasons:
        status = READINESS_PARTIAL
    else:
        status = READINESS_READY

    if production_status == READINESS_PARTIAL and status == READINESS_READY:
        status = READINESS_PARTIAL
        details["production_caution"] = True

    return ReadinessResult(status=status, reasons=reasons, details=details)
