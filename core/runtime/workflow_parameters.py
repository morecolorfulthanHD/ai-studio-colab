#!/usr/bin/env python3
"""Workflow parameter coercion, validation, and binding (Package 4.8)."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

IMAGE_PARAM_TYPES = frozenset({"image", "mask", "file"})

_UNSAFE_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|]')
_WIDGET_INDEX_RE = re.compile(r"^widgets_values\[(\d+)\]$")


def _normalize_divisible_by_8(value: int, *, minimum: int | None, maximum: int | None) -> int:
    normalized = int(value)
    if normalized % 8 != 0:
        normalized = max(8, (normalized // 8) * 8)
    if minimum is not None and normalized < minimum:
        normalized = ((minimum + 7) // 8) * 8
    if maximum is not None and normalized > maximum:
        normalized = (maximum // 8) * 8
    return normalized


def _normalize_safe_filename_prefix(value: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", value.strip())
    cleaned = cleaned.replace("..", "_").strip("._ ")
    return cleaned or "ai_studio"


def _coerce_value(param_name: str, spec: dict[str, Any], raw: Any) -> tuple[Any, list[str]]:
    errors: list[str] = []
    param_type = str(spec.get("type") or "string")
    required = bool(spec.get("required", False))
    normalization = str(spec.get("normalization") or "")

    if raw is None:
        if required:
            errors.append(f"{param_name}: required parameter is missing")
        return None, errors

    if param_type in IMAGE_PARAM_TYPES:
        if isinstance(raw, (str, Path)):
            text = str(raw).strip()
            if not text and required:
                errors.append(f"{param_name}: required file parameter is empty")
            return text or None, errors
        if required:
            errors.append(f"{param_name}: expected file path string")
        return None, errors

    if param_type == "string":
        text = str(raw)
        if normalization == "safe_filename_prefix":
            text = _normalize_safe_filename_prefix(text)
        else:
            text = text.strip() if isinstance(raw, str) else str(raw)
        if required and not text:
            errors.append(f"{param_name}: required string parameter is empty")
        return text, errors

    if param_type == "boolean":
        if isinstance(raw, bool):
            return raw, errors
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True, errors
            if lowered in {"false", "0", "no", "off"}:
                return False, errors
        errors.append(f"{param_name}: expected boolean")
        return None, errors

    if param_type == "integer":
        try:
            value = int(raw)
        except (TypeError, ValueError):
            errors.append(f"{param_name}: expected integer")
            return None, errors
        if normalization == "divisible_by_8":
            value = _normalize_divisible_by_8(
                value,
                minimum=spec.get("minimum"),
                maximum=spec.get("maximum"),
            )
        minimum = spec.get("minimum")
        maximum = spec.get("maximum")
        if minimum is not None and value < minimum:
            errors.append(f"{param_name}: value {value} below minimum {minimum}")
        if maximum is not None and value > maximum:
            errors.append(f"{param_name}: value {value} above maximum {maximum}")
        return value, errors

    if param_type == "number":
        try:
            value = float(raw)
        except (TypeError, ValueError):
            errors.append(f"{param_name}: expected number")
            return None, errors
        minimum = spec.get("minimum")
        maximum = spec.get("maximum")
        if minimum is not None and value < minimum:
            errors.append(f"{param_name}: value {value} below minimum {minimum}")
        if maximum is not None and value > maximum:
            errors.append(f"{param_name}: value {value} above maximum {maximum}")
        return value, errors

    if param_type == "enum":
        text = str(raw).strip()
        allowed = spec.get("allowed_values") or []
        if allowed and text not in allowed:
            errors.append(f"{param_name}: value {text!r} not in allowed_values")
        return text, errors

    errors.append(f"{param_name}: unsupported parameter type {param_type!r}")
    return raw, errors


def coerce_and_validate_parameters(
    schema: dict[str, Any],
    defaults: dict[str, Any],
    user_params: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Merge defaults with user params, coerce types, and return validation errors."""
    merged = dict(defaults or {})
    if user_params:
        merged.update(user_params)

    params: dict[str, Any] = {}
    errors: list[str] = []
    for param_name, spec in (schema or {}).items():
        if not isinstance(spec, dict):
            continue
        raw = merged.get(param_name, spec.get("default"))
        value, param_errors = _coerce_value(param_name, spec, raw)
        errors.extend(param_errors)
        params[param_name] = value

    for param_name, spec in (schema or {}).items():
        if not isinstance(spec, dict):
            continue
        if param_name == "positive_prompt" and str(spec.get("type") or "") == "string":
            text = str(params.get(param_name) or "").strip()
            if spec.get("required") and not text:
                errors.append(f"{param_name}: positive_prompt must be non-empty after strip")

    return params, errors


def _find_node(workflow_data: dict[str, Any], node_id: str | int) -> dict[str, Any] | None:
    target = str(node_id)
    for node in workflow_data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("id")) == target:
            return node
    return None


def _apply_target_field(node: dict[str, Any], target_field: str, value: Any) -> bool:
    match = _WIDGET_INDEX_RE.match(target_field.strip())
    if not match:
        return False
    index = int(match.group(1))
    widgets = node.get("widgets_values")
    if not isinstance(widgets, list):
        widgets = []
        node["widgets_values"] = widgets
    while len(widgets) <= index:
        widgets.append(None)
    widgets[index] = value
    return True


def apply_parameter_bindings(
    workflow_data: dict[str, Any],
    schema: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Return a copy of workflow_data with non-file parameter bindings applied."""
    data = copy.deepcopy(workflow_data)
    for param_name, spec in (schema or {}).items():
        if not isinstance(spec, dict):
            continue
        param_type = str(spec.get("type") or "string")
        value = params.get(param_name)
        if param_type in IMAGE_PARAM_TYPES:
            if isinstance(value, str) and value and "/" not in value and "\\" not in value:
                node_id = spec.get("target_node_id")
                target_field = spec.get("target_field")
                if node_id is not None and target_field:
                    node = _find_node(data, node_id)
                    if node is not None:
                        _apply_target_field(node, str(target_field), Path(value).name)
            continue
        if value is None:
            continue
        node_id = spec.get("target_node_id")
        target_field = spec.get("target_field")
        if node_id is None or not target_field:
            continue
        node = _find_node(data, node_id)
        if node is None:
            continue
        _apply_target_field(node, str(target_field), value)
    return data
