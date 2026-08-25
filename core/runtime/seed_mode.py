#!/usr/bin/env python3
"""Prepared-workflow seed behavior (Package 4.9 / 4.11.1).

seed_mode is the user-facing preparation choice. It maps onto ComfyUI's native
KSampler ``control_after_generate`` widget — we do not invent an external
pseudo-random seed replacer.

Exposed values:
  fixed     → control_after_generate = fixed
  randomize → control_after_generate = randomize

ComfyUI also supports increment/decrement natively. Package 4.9 does not expose
those. Internal widget values match the display labels for the two modes we use.

Seed precision (Package 4.11.1):
  ComfyUI's browser loads workflow JSON via JavaScript ``JSON.parse``, which
  stores numbers as IEEE-754 float64. Integers above ``Number.MAX_SAFE_INTEGER``
  (2^53 - 1) cannot round-trip exactly. AI Studio therefore requires all
  prepared / user-entered seeds to stay within that range so preparation →
  browser → Run → snapshot provenance remains bit-identical.

  Stock ComfyUI ``control_after_generate=randomize`` is implemented in the
  frontend (not Python). The currently verified upstream implementation
  (``Comfy-Org/ComfyUI_frontend`` ``valueControl.ts``) clamps INT randomize to
  ``SAFE_INTEGER_MAX = 2^50``, which is stricter than ``Number.MAX_SAFE_INTEGER``.
  AI Studio keeps native randomize semantics and does not replace them.
  Important: this module encodes a verified compatibility contract for known
  frontend behavior; it does not introspect live upstream source at runtime.

Layers:
  preparation archive  — original prepared intent (immutable)
  ComfyUI user copy    — runtime-editable/loadable working copy
  generation snapshot  — actual execution (authoritative seed)
"""

from __future__ import annotations

import math
import secrets
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

# Largest integer range the ComfyUI browser can round-trip exactly (JS Number).
MIN_SAFE_SEED = 0
MAX_SAFE_SEED = (2**53) - 1  # 9007199254740991 == Number.MAX_SAFE_INTEGER
SEED_PRECISION_ERROR = (
    f"Seed must be between {MIN_SAFE_SEED} and {MAX_SAFE_SEED} "
    "so it can be preserved exactly through ComfyUI."
)

# Verified stock ComfyUI frontend randomize model
# (Comfy-Org/ComfyUI_frontend valueControl.ts):
# applyWidgetControl → nextValueForLinkedTarget → computeNextNumberValue(mode=randomize)
# This is a pinned compatibility assumption for Package 4.11.1 tests/docs.
# Future frontend upgrades must be re-verified before changing these constants.
COMFYUI_FRONTEND_VALUE_CONTROL_SOURCE = (
    "Comfy-Org/ComfyUI_frontend/src/scripts/valueControl.ts"
)
COMFYUI_FRONTEND_SAFE_INTEGER_MAX = 2**50  # SAFE_INTEGER_MAX in valueControl.ts
COMFYUI_FRONTEND_SAFE_INTEGER_MIN = -(2**50)
# KSampler seed INPUT_TYPES max (Comfy-Org/ComfyUI nodes_ksampler.py).
COMFYUI_KSAMPLER_SEED_RAW_MAX = 18446744073709551615  # 0xffffffffffffffff


def comfyui_frontend_randomize_int_bounds(
    *,
    raw_min: int = 0,
    raw_max: int = COMFYUI_KSAMPLER_SEED_RAW_MAX,
    step: int = 1,
) -> tuple[int, int]:
    """Inclusive output bounds for stock frontend randomize on an INT widget.

    Mirrors ``computeNextNumberValue`` clamping in valueControl.ts:
      max = min(SAFE_INTEGER_MAX, rawMax)
      min = max(SAFE_INTEGER_MIN, rawMin)
      next = floor(Math.random() * range) * step + min
      return clamp(next, min, max)
    """
    clamped_max = min(COMFYUI_FRONTEND_SAFE_INTEGER_MAX, raw_max)
    clamped_min = max(COMFYUI_FRONTEND_SAFE_INTEGER_MIN, raw_min)
    if step <= 0:
        return clamped_min, clamped_max
    range_count = (clamped_max - clamped_min) / step
    max_floor_index = int(range_count) - 1 if range_count >= 1 else 0
    output_max = clamped_min + max_floor_index * step
    output_max = min(max(output_max, clamped_min), clamped_max)
    return clamped_min, output_max


def simulate_comfyui_frontend_randomize_int(
    *,
    raw_min: int = 0,
    raw_max: int = COMFYUI_KSAMPLER_SEED_RAW_MAX,
    step: int = 1,
    random_unit: float,
) -> int:
    """Test helper mirroring ``computeNextNumberValue(..., 'randomize')``."""
    clamped_max = min(COMFYUI_FRONTEND_SAFE_INTEGER_MAX, raw_max)
    clamped_min = max(COMFYUI_FRONTEND_SAFE_INTEGER_MIN, raw_min)
    range_count = (clamped_max - clamped_min) / step
    next_val = math.floor(random_unit * range_count) * step + clamped_min
    return int(min(max(next_val, clamped_min), clamped_max))


def assert_verified_stock_randomize_contract() -> None:
    """Validate the currently verified stock-frontend compatibility assumption.

    This checks local constants that model inspected frontend behavior; it is
    intentionally not a live upstream-source detector.
    """
    lo, hi = comfyui_frontend_randomize_int_bounds()
    if lo < MIN_SAFE_SEED or hi > MAX_SAFE_SEED:
        raise ValueError(
            "Verified stock ComfyUI frontend randomize bounds "
            f"[{lo}, {hi}] exceed AI Studio MAX_SAFE_SEED={MAX_SAFE_SEED}. "
            "Re-verify frontend compatibility before accepting this contract."
        )
    if COMFYUI_FRONTEND_SAFE_INTEGER_MAX > MAX_SAFE_SEED:
        raise ValueError(
            "Verified frontend SAFE_INTEGER_MAX exceeds AI Studio MAX_SAFE_SEED; "
            "re-verify compatibility constants."
        )


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


def is_js_safe_seed(value: Any) -> bool:
    """True when value is an int in the JS-safe inclusive seed range."""
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return MIN_SAFE_SEED <= value <= MAX_SAFE_SEED


def validate_js_safe_seed(value: Any) -> tuple[int | None, str | None]:
    """Return ``(seed, None)`` when valid, else ``(None, user-facing error)``.

    Fail closed: never clamp, round, modulo, or rewrite.
    """
    seed = coerce_execution_seed(value)
    if seed is None:
        return None, SEED_PRECISION_ERROR
    if not is_js_safe_seed(seed):
        return None, SEED_PRECISION_ERROR
    return seed, None


def generate_js_safe_seed() -> int:
    """Cryptographically strong seed in ``[0, MAX_SAFE_SEED]`` (inclusive)."""
    return secrets.randbelow(MAX_SAFE_SEED + 1)


def simulate_js_number_round_trip(value: int) -> int:
    """Approximate browser ``JSON.parse`` numeric coercion (IEEE-754 float64)."""
    return int(float(value))


def seed_precision_warning(value: Any) -> str:
    """Non-mutating warning for display of historical oversized seeds."""
    seed = coerce_execution_seed(value)
    if seed is None or is_js_safe_seed(seed):
        return ""
    return (
        f"Recorded seed {seed} exceeds the JavaScript-safe maximum "
        f"({MAX_SAFE_SEED}); ComfyUI browser round-trip cannot guarantee "
        "exact execution of this value."
    )


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
