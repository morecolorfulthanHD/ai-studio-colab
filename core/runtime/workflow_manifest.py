#!/usr/bin/env python3
"""Workflow library manifest loading and validation (Package 4.8)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .workflow_provenance import WORKFLOW_ID_TO_IDENTIFIER, hash_ui_workflow

MANIFEST_FILENAME = "manifest.json"

REQUIRED_MANIFEST_FIELDS = [
    "schema_version",
    "workflow_identifier",
    "display_name",
    "description",
    "category",
    "capability",
    "implementation_status",
    "runtime_status",
    "quality_status",
    "production_status",
    "status_reason",
    "model_family",
    "required_model_files",
    "optional_model_files",
    "required_nodes",
    "optional_nodes",
    "canonical_workflow_path",
    "workflow_hash",
    "workflow_hash_type",
    "parameter_schema",
    "default_parameters",
    "output_prefix",
    "supported_environments",
    "license_notes",
    "tags",
    "documentation_path",
    "launchable",
    "requires_experimental",
    "requires_benchmark",
]

_IDENTIFIER_ALIASES: dict[str, str] = {
    "txt2img": "base/txt2img",
    "img2img": "base/img2img",
    "inpainting": "base/inpainting",
    "outpainting": "base/outpainting",
    "qwen_image_edit": "reference/qwen_image_edit",
    "flux_fill": "reference/flux_fill",
}

_IDENTIFIER_TO_WORKFLOW_ID: dict[str, str] = {
    identifier: workflow_id for workflow_id, (identifier, _source) in WORKFLOW_ID_TO_IDENTIFIER.items()
}


def resolve_workflow_identifier(alias: str) -> str:
    """Normalize workflow alias to canonical ``category/name`` identifier."""
    text = str(alias or "").strip()
    if not text:
        raise ValueError("Workflow identifier is required.")

    if text in _IDENTIFIER_ALIASES:
        return _IDENTIFIER_ALIASES[text]

    normalized = text.replace("\\", "/")
    if normalized.startswith("base_"):
        normalized = "base/" + normalized[len("base_") :]
    elif normalized.startswith("reference_"):
        normalized = "reference/" + normalized[len("reference_") :]
    elif normalized.startswith("benchmark/"):
        normalized = "reference/" + normalized[len("benchmark/") :]

    if "/" in normalized:
        return normalized

    raise ValueError(f"Unknown workflow identifier: {alias}")


def _manifest_path_for_identifier(repo_root: Path, workflow_identifier: str) -> Path:
    return repo_root / "workflows" / workflow_identifier / MANIFEST_FILENAME


def load_workflow_manifest(repo_root: Path, workflow_identifier: str) -> dict[str, Any]:
    """Load manifest.json for a resolved workflow identifier."""
    resolved = resolve_workflow_identifier(workflow_identifier)
    manifest_path = _manifest_path_for_identifier(repo_root, resolved)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Workflow manifest not found: {manifest_path}")
    with manifest_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{manifest_path}: manifest root must be a JSON object")
    data["_manifest_path"] = str(manifest_path)
    data["_workflow_identifier"] = resolved
    return data


def list_workflow_manifests(repo_root: Path) -> list[dict[str, Any]]:
    """Scan ``workflows/**/manifest.json`` and return manifest payloads with paths."""
    entries: list[dict[str, Any]] = []
    workflows_root = repo_root / "workflows"
    if not workflows_root.is_dir():
        return entries
    for manifest_path in sorted(workflows_root.rglob(MANIFEST_FILENAME)):
        try:
            with manifest_path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        rel = manifest_path.parent.relative_to(repo_root).as_posix()
        identifier = str(data.get("workflow_identifier") or rel.replace("workflows/", ""))
        entry = dict(data)
        entry["_manifest_path"] = str(manifest_path)
        entry["_workflow_identifier"] = identifier
        entries.append(entry)
    return entries


def validate_manifest_structure(data: dict[str, Any]) -> list[str]:
    """Return structural validation errors for a workflow manifest."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["manifest root must be a JSON object"]

    for field_name in REQUIRED_MANIFEST_FIELDS:
        if field_name not in data:
            errors.append(f"missing required field: {field_name}")

    schema = data.get("parameter_schema")
    if schema is not None and not isinstance(schema, dict):
        errors.append("parameter_schema must be an object")

    defaults = data.get("default_parameters")
    if defaults is not None and not isinstance(defaults, dict):
        errors.append("default_parameters must be an object")

    for list_field in ("required_model_files", "optional_model_files", "required_nodes", "optional_nodes"):
        value = data.get(list_field)
        if value is not None and not isinstance(value, list):
            errors.append(f"{list_field} must be a list")

    supported = data.get("supported_environments")
    if supported is not None and not isinstance(supported, list):
        errors.append("supported_environments must be a list")

    return errors


def validate_manifest_against_canonical(repo_root: Path, data: dict[str, Any]) -> list[str]:
    """Validate canonical workflow file exists and hash matches manifest."""
    errors: list[str] = []
    rel_path = str(data.get("canonical_workflow_path") or "")
    if not rel_path:
        errors.append("canonical_workflow_path is empty")
        return errors

    canonical_path = repo_root / rel_path
    if not canonical_path.is_file():
        errors.append(f"canonical workflow missing: {rel_path}")
        return errors

    declared_hash = str(data.get("workflow_hash") or "")
    declared_type = str(data.get("workflow_hash_type") or "")
    if declared_type and declared_type != "ui_workflow_v1":
        errors.append(f"unsupported workflow_hash_type: {declared_type}")

    try:
        workflow_data = json.loads(canonical_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read canonical workflow: {exc}")
        return errors

    computed = hash_ui_workflow(workflow_data)
    if declared_hash and computed != declared_hash:
        errors.append(
            f"workflow_hash mismatch: manifest={declared_hash[:16]}... computed={computed[:16]}..."
        )
    return errors


def workflow_id_for_identifier(workflow_identifier: str) -> str:
    """Return registry-style workflow id (e.g. base_txt2img)."""
    resolved = resolve_workflow_identifier(workflow_identifier)
    return _IDENTIFIER_TO_WORKFLOW_ID.get(resolved, resolved.replace("/", "_"))
