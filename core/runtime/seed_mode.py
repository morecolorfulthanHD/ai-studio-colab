#!/usr/bin/env python3
"""Prepared-workflow seed behavior (Package 4.9).

seed_mode is the user-facing preparation choice. It maps onto ComfyUI's native
KSampler ``control_after_generate`` widget — we do not invent an external
pseudo-random seed replacer.

Exposed values:
  fixed     → control_after_generate = fixed
  randomize → control_after_generate = randomize

ComfyUI also supports increment/decrement natively. Package 4.9 does not expose
those. Internal widget values match the display labels for the two modes we use.

Layers:
  preparation archive  — original prepared intent (immutable)
  ComfyUI user copy    — runtime-editable/loadable working copy
  generation snapshot  — actual execution (authoritative seed)
"""

from __future__ import annotations

from typing import Any

SEED_MODE_FIXED = "fixed"
SEED_MODE_RANDOMIZE = "randomize"
ALLOWED_SEED_MODES = (SEED_MODE_FIXED, SEED_MODE_RANDOMIZE)
ALLOWED_SEED_MODE_SET = frozenset(ALLOWED_SEED_MODES)

# Native ComfyUI KSampler control_after_generate values we currently bind.
CONTROL_AFTER_GENERATE_FIXED = "fixed"
CONTROL_AFTER_GENERATE_RANDOMIZE = "randomize"

_SEED_MODE_TO_CONTROL = {
    SEED_MODE_FIXED: CONTROL_AFTER_GENERATE_FIXED,
    SEED_MODE_RANDOMIZE: CONTROL_AFTER_GENERATE_RANDOMIZE,
}


def control_after_generate_for_seed_mode(seed_mode: str) -> str:
    """Map a validated seed_mode onto the native KSampler widget value."""
    return _SEED_MODE_TO_CONTROL.get(str(seed_mode).strip(), CONTROL_AFTER_GENERATE_FIXED)


def coerce_execution_seed(value: Any) -> int | None:
    """Coerce a history/API/UI seed to int. Never treats bool as a seed."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def annotate_seed_controls(params: dict[str, Any], schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record control_after_generate beside seed_mode when the schema supports it."""
    if schema is not None and "seed_mode" not in schema:
        return params
    if "seed_mode" not in params:
        return params
    mode = str(params.get("seed_mode") or "").strip()
    if mode not in ALLOWED_SEED_MODE_SET:
        return params
    params["control_after_generate"] = control_after_generate_for_seed_mode(mode)
    return params


def extract_ksampler_widgets(workflow_data: dict[str, Any] | None) -> list[Any]:
    if not isinstance(workflow_data, dict):
        return []
    for node in workflow_data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "KSampler":
            widgets = node.get("widgets_values")
            return list(widgets) if isinstance(widgets, list) else []
    return []


def extract_ksampler_seed(workflow_data: dict[str, Any] | None) -> int | None:
    widgets = extract_ksampler_widgets(workflow_data)
    if not widgets:
        return None
    return coerce_execution_seed(widgets[0])


def extract_ksampler_control_after_generate(workflow_data: dict[str, Any] | None) -> str:
    widgets = extract_ksampler_widgets(workflow_data)
    if len(widgets) < 2 or widgets[1] is None:
        return ""
    return str(widgets[1]).strip()


def _first_seed_mode(*sources: Any) -> str:
    for source in sources:
        if not isinstance(source, dict):
            continue
        candidates = [source.get("seed_mode")]
        parameters = source.get("parameters")
        if isinstance(parameters, dict):
            candidates.append(parameters.get("seed_mode"))
        summary = source.get("parameter_summary")
        if isinstance(summary, dict):
            candidates.append(summary.get("seed_mode"))
        for raw in candidates:
            if raw is None:
                continue
            text = str(raw).strip()
            if text in ALLOWED_SEED_MODE_SET:
                return text
    return ""


def _first_control(*sources: Any) -> str:
    for source in sources:
        if not isinstance(source, dict):
            continue
        candidates = [source.get("control_after_generate")]
        parameters = source.get("parameters")
        if isinstance(parameters, dict):
            candidates.append(parameters.get("control_after_generate"))
        summary = source.get("parameter_summary")
        if isinstance(summary, dict):
            candidates.append(summary.get("control_after_generate"))
        for raw in candidates:
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                return text
    return ""


def resolve_seed_mode(
    *,
    parameters: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    index_record: dict[str, Any] | None = None,
    workflow_data: dict[str, Any] | None = None,
) -> str:
    """Resolve seed_mode for display/inspection.

    Explicit stored seed_mode wins. Legacy Package 4.8.x preparations without
    seed_mode are treated as fixed when control_after_generate is fixed or
    missing. If the archived graph already has randomize, report randomize.
    """
    explicit = _first_seed_mode(parameters, metadata, index_record)
    if explicit:
        return explicit
    control = _first_control(parameters, metadata, index_record)
    if not control:
        control = extract_ksampler_control_after_generate(workflow_data)
    if control == CONTROL_AFTER_GENERATE_RANDOMIZE:
        return SEED_MODE_RANDOMIZE
    return SEED_MODE_FIXED


def resolve_control_after_generate(
    *,
    parameters: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    index_record: dict[str, Any] | None = None,
    workflow_data: dict[str, Any] | None = None,
    seed_mode: str | None = None,
) -> str:
    explicit = _first_control(parameters, metadata, index_record)
    if explicit:
        return explicit
    from_graph = extract_ksampler_control_after_generate(workflow_data)
    if from_graph:
        return from_graph
    mode = seed_mode or resolve_seed_mode(
        parameters=parameters,
        metadata=metadata,
        index_record=index_record,
        workflow_data=workflow_data,
    )
    return control_after_generate_for_seed_mode(mode)
