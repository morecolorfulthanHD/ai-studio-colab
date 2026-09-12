#!/usr/bin/env python3
"""ComfyUI /prompt queue helpers for authorized Package 4.12.3 benchmark execution.

Explicitly allowed only for identity-architecture live runner with cost acknowledgement.
Not used by ordinary prepare/open/reproduction paths.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

from .comfyui_events import DEFAULT_COMFY_BASE, extract_output_files, fetch_history, history_entry_completed

# Widget keys in ComfyUI API order (skip UI-only control_after_generate for KSampler).
NODE_WIDGET_API_KEYS: dict[str, list[str]] = {
    "CheckpointLoaderSimple": ["ckpt_name"],
    "CLIPTextEncode": ["text"],
    "EmptyLatentImage": ["width", "height", "batch_size"],
    "KSampler": ["seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"],
    "LoadImage": ["image"],
    "VAEDecode": [],
    "SaveImage": ["filename_prefix"],
    "InstantIDModelLoader": ["instantid_file"],
    "InstantIDFaceAnalysis": ["provider"],
    "ControlNetLoader": ["control_net_name"],
    "ApplyInstantID": ["weight", "start_at", "end_at"],
    "ApplyInstantIDAdvanced": [
        "ip_weight",
        "cn_strength",
        "start_at",
        "end_at",
        "noise",
        "combine_embeds",
    ],
}

# Linked input names by slot index for nodes that mix links + widgets.
NODE_LINK_INPUT_NAMES: dict[str, list[str]] = {
    "CLIPTextEncode": ["clip"],
    "KSampler": ["model", "positive", "negative", "latent_image"],
    "VAEDecode": ["samples", "vae"],
    "SaveImage": ["images"],
    "ApplyInstantID": [
        "instantid",
        "insightface",
        "control_net",
        "image",
        "model",
        "positive",
        "negative",
    ],
    "ApplyInstantIDAdvanced": [
        "instantid",
        "insightface",
        "control_net",
        "image",
        "model",
        "positive",
        "negative",
    ],
}


def _ksampler_widget_values(widgets: list[Any]) -> list[Any]:
    """UI widgets: [seed, control_after_generate, steps, cfg, sampler, scheduler, denoise]."""
    if len(widgets) >= 7:
        return [widgets[0], widgets[2], widgets[3], widgets[4], widgets[5], widgets[6]]
    if len(widgets) >= 6:
        return widgets[:6]
    return list(widgets)


def ui_workflow_to_api_prompt(workflow: dict[str, Any]) -> dict[str, Any]:
    """Convert a LiteGraph UI workflow to ComfyUI API prompt dict (node_id -> node)."""
    nodes = workflow.get("nodes") or []
    links = workflow.get("links") or []
    link_map: dict[int, tuple[int, int]] = {}
    for link in links:
        if not isinstance(link, (list, tuple)) or len(link) < 5:
            continue
        # [id, from_node, from_slot, to_node, to_slot, type]
        link_map[int(link[0])] = (int(link[1]), int(link[2]))

    prompt: dict[str, Any] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id"))
        class_type = str(node.get("type") or "")
        if not node_id or not class_type:
            continue
        inputs: dict[str, Any] = {}
        # Linked inputs by declared name/slot
        for inp in node.get("inputs") or []:
            if not isinstance(inp, dict):
                continue
            name = str(inp.get("name") or "")
            link_id = inp.get("link")
            if not name or link_id is None:
                continue
            src = link_map.get(int(link_id))
            if src is None:
                continue
            inputs[name] = [str(src[0]), int(src[1])]

        widgets = list(node.get("widgets_values") or [])
        if class_type == "KSampler":
            widgets = _ksampler_widget_values(widgets)
        keys = NODE_WIDGET_API_KEYS.get(class_type, [])
        for idx, key in enumerate(keys):
            if idx < len(widgets):
                inputs[key] = widgets[idx]
        # LoadImage may have a second upload widget — ignore.
        if class_type == "SaveImage" and "filename_prefix" not in inputs and widgets:
            inputs["filename_prefix"] = widgets[0]

        prompt[node_id] = {"class_type": class_type, "inputs": inputs}
    return prompt


@dataclass
class QueuePromptResult:
    ok: bool
    prompt_id: str = ""
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    raw: dict[str, Any] | None = None


def queue_prompt(
    api_prompt: dict[str, Any],
    *,
    base_url: str = DEFAULT_COMFY_BASE,
    client_id: str | None = None,
    timeout: float = 30.0,
    extra_data: dict[str, Any] | None = None,
) -> QueuePromptResult:
    """POST ComfyUI /prompt. Fail closed on HTTP/network errors."""
    result = QueuePromptResult(ok=False)
    if not api_prompt:
        result.errors.append("ERROR: Empty API prompt.")
        return result
    cid = client_id or str(uuid.uuid4())
    body: dict[str, Any] = {"prompt": api_prompt, "client_id": cid}
    if extra_data:
        body["extra_data"] = extra_data
    url = base_url.rstrip("/") + "/prompt"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            detail = str(exc)
        result.errors.append(f"ERROR: ComfyUI /prompt HTTP {exc.code}: {detail}")
        return result
    except urllib.error.URLError as exc:
        result.errors.append(f"ERROR: Unable to reach ComfyUI /prompt at {url}: {exc}")
        return result
    except json.JSONDecodeError as exc:
        result.errors.append(f"ERROR: Invalid JSON from ComfyUI /prompt: {exc}")
        return result

    result.raw = payload if isinstance(payload, dict) else {"raw": payload}
    if isinstance(payload, dict) and payload.get("error"):
        result.errors.append(f"ERROR: ComfyUI /prompt rejected: {payload.get('error')}")
        return result
    prompt_id = ""
    if isinstance(payload, dict):
        prompt_id = str(payload.get("prompt_id") or "").strip()
    if not prompt_id:
        result.errors.append("ERROR: ComfyUI /prompt response missing prompt_id.")
        return result
    result.ok = True
    result.prompt_id = prompt_id
    result.messages.append(f"Queued ComfyUI prompt_id={prompt_id}")
    return result


@dataclass
class WaitHistoryResult:
    ok: bool
    entry: dict[str, Any] | None = None
    timed_out: bool = False
    failed_status: bool = False
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def wait_for_prompt_completion(
    prompt_id: str,
    *,
    base_url: str = DEFAULT_COMFY_BASE,
    timeout_seconds: float = 600.0,
    poll_interval_seconds: float = 2.0,
    sleep_fn=time.sleep,
    fetch_fn=None,
) -> WaitHistoryResult:
    """Poll /history/{prompt_id} until completed or timeout. Fail closed."""
    result = WaitHistoryResult(ok=False)
    if not prompt_id:
        result.errors.append("ERROR: prompt_id required for history wait.")
        return result
    fetch = fetch_fn or fetch_history
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        try:
            history = fetch(base_url=base_url, prompt_id=prompt_id)
        except RuntimeError as exc:
            result.errors.append(str(exc))
            return result
        entry = None
        if isinstance(history, dict):
            if prompt_id in history and isinstance(history[prompt_id], dict):
                entry = history[prompt_id]
            elif history and "outputs" in history:
                entry = history
        if entry is not None and history_entry_completed(entry):
            status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
            status_str = str((status or {}).get("status_str") or "").lower()
            if status_str in {"error", "interrupted"}:
                result.failed_status = True
                result.entry = entry
                result.errors.append(f"ERROR: ComfyUI execution {status_str} for prompt {prompt_id}.")
                return result
            result.ok = True
            result.entry = entry
            result.messages.append(f"Prompt {prompt_id} completed.")
            return result
        sleep_fn(max(0.1, float(poll_interval_seconds)))
    result.timed_out = True
    result.errors.append(
        f"ERROR: Timed out after {timeout_seconds}s waiting for ComfyUI prompt {prompt_id}."
    )
    return result


def first_output_meta(history_entry: dict[str, Any]) -> dict[str, Any] | None:
    files = extract_output_files(history_entry)
    return files[0] if files else None
