#!/usr/bin/env python3
"""ComfyUI HTTP history/event helpers (stdlib). Optional WebSocket when available."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_COMFY_BASE = "http://127.0.0.1:8188"
DEFAULT_COMFY_WS = "ws://127.0.0.1:8188/ws"


@dataclass
class ExecutionCompleteEvent:
    prompt_id: str
    node: str | None = None
    raw: dict[str, Any] | None = None


def fetch_history(
    base_url: str = DEFAULT_COMFY_BASE,
    prompt_id: str | None = None,
    *,
    timeout: float = 10,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/history"
    if prompt_id:
        url = f"{url}/{prompt_id}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Unable to reach ComfyUI history at {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("ComfyUI history payload must be a JSON object.")
    return payload


def poll_completed_prompt_ids(
    previous: set[str],
    *,
    base_url: str = DEFAULT_COMFY_BASE,
) -> list[str]:
    history = fetch_history(base_url=base_url)
    completed = sorted(set(history.keys()) - previous)
    return completed


def history_entry_completed(entry: dict[str, Any]) -> bool:
    """True when ComfyUI reports the prompt finished (success or error)."""
    status = entry.get("status")
    if isinstance(status, dict):
        if status.get("completed") is True:
            return True
        status_str = str(status.get("status_str") or "").lower()
        if status_str in {"success", "error", "interrupted"}:
            return True
    # History entries without status but with outputs are treated as complete.
    outputs = entry.get("outputs")
    return isinstance(outputs, dict) and bool(outputs)


_MEDIA_KEYS = ("images", "gifs", "videos")


def _file_item_from_dict(item: Any, *, node_id: str, kind: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    filename = item.get("filename")
    if not filename:
        return None
    subfolder = str(item.get("subfolder") or "")
    file_type = str(item.get("type") or "output")
    if file_type.lower() in {"temp", "preview"} or subfolder.lower() in {"temp", "preview"}:
        return None
    return {
        "node_id": str(node_id),
        "filename": str(filename),
        "subfolder": subfolder,
        "type": file_type,
        "kind": kind,
    }


def _collect_media_items(container: Any, *, node_id: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    if not isinstance(container, dict):
        return files
    for key in _MEDIA_KEYS:
        items = container.get(key) or []
        if not isinstance(items, list):
            continue
        for item in items:
            parsed = _file_item_from_dict(item, node_id=node_id, kind=key)
            if parsed is not None:
                files.append(parsed)
    return files


def extract_output_files(history_entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return final output metadata from a single prompt history entry.

    Accepts stock ComfyUI history shapes:
      outputs[node_id].images[{filename, subfolder, type}]
    and nested/live variants:
      outputs[node_id].ui.images[...]
      outputs[node_id].output.images[...]
    """
    outputs = history_entry.get("outputs") or {}
    files: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    if not isinstance(outputs, dict):
        return files
    for node_id, node_output in outputs.items():
        candidates = _collect_media_items(node_output, node_id=str(node_id))
        if isinstance(node_output, dict):
            for nested_key in ("ui", "output"):
                candidates.extend(
                    _collect_media_items(node_output.get(nested_key), node_id=str(node_id))
                )
        for parsed in candidates:
            key = (parsed["node_id"], parsed["filename"], parsed["subfolder"])
            if key in seen:
                continue
            seen.add(key)
            files.append(parsed)
    return files


def collect_named_file_mentions(history_entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect any {filename, subfolder, type} dicts anywhere in a history entry."""
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def _walk(node: Any, *, parent_key: str = "") -> None:
        if isinstance(node, dict):
            filename = node.get("filename")
            if isinstance(filename, str) and filename:
                parsed = _file_item_from_dict(
                    node,
                    node_id=str(node.get("node_id") or parent_key or ""),
                    kind="images",
                )
                if parsed is not None:
                    key = (parsed["node_id"], parsed["filename"], parsed["subfolder"])
                    if key not in seen:
                        seen.add(key)
                        found.append(parsed)
            for key, value in node.items():
                _walk(value, parent_key=str(key))
        elif isinstance(node, list):
            for item in node:
                _walk(item, parent_key=parent_key)

    if isinstance(history_entry, dict):
        _walk(history_entry)
    return found


def describe_history_output_shape(history_entry: dict[str, Any]) -> dict[str, Any]:
    """Read-only classification of how (or whether) outputs are represented."""
    outputs = history_entry.get("outputs") if isinstance(history_entry, dict) else None
    flattened = False
    nested_ui = False
    nested_output = False
    if isinstance(outputs, dict):
        for node_output in outputs.values():
            if not isinstance(node_output, dict):
                continue
            if isinstance(node_output.get("images"), list) and node_output.get("images"):
                flattened = True
            ui = node_output.get("ui")
            if isinstance(ui, dict) and isinstance(ui.get("images"), list) and ui.get("images"):
                nested_ui = True
            inner = node_output.get("output")
            if isinstance(inner, dict) and isinstance(inner.get("images"), list) and inner.get("images"):
                nested_output = True
    return {
        "has_outputs_object": isinstance(outputs, dict),
        "flattened_images_found": flattened,
        "nested_ui_images_found": nested_ui,
        "nested_output_images_found": nested_output,
        "named_file_mentions": collect_named_file_mentions(history_entry)
        if isinstance(history_entry, dict)
        else [],
        "extractable_files": extract_output_files(history_entry)
        if isinstance(history_entry, dict)
        else [],
    }


def prompt_execution_epoch(history_entry: dict[str, Any]) -> float | None:
    """Best-effort execution timestamp from a history entry. None if unproven."""
    if not isinstance(history_entry, dict):
        return None
    status = history_entry.get("status")
    candidates: list[Any] = []
    if isinstance(status, dict):
        for key in ("timestamp", "completed_at", "started_at", "execution_start"):
            candidates.append(status.get(key))
        messages = status.get("messages") or []
        if isinstance(messages, list):
            for message in messages:
                if isinstance(message, (list, tuple)) and len(message) >= 2:
                    candidates.append(message[1])
                elif isinstance(message, dict):
                    candidates.append(message.get("timestamp"))
    for raw in candidates:
        if isinstance(raw, (int, float)) and raw > 1_000_000_000:
            return float(raw)
        if isinstance(raw, str):
            try:
                value = float(raw)
            except ValueError:
                continue
            if value > 1_000_000_000:
                return value
    return None


def save_image_prefixes(history_entry: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (node_id, filename_prefix) pairs from the API prompt."""
    prompt_field = history_entry.get("prompt") if isinstance(history_entry, dict) else None
    candidates: list[Any] = []
    if isinstance(prompt_field, dict):
        candidates.append(prompt_field)
    elif isinstance(prompt_field, list):
        candidates.extend(prompt_field)
    if isinstance(history_entry, dict):
        candidates.append(history_entry.get("api_prompt"))
    pairs: list[tuple[str, str]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for node_id, node in candidate.items():
            if not isinstance(node, dict) or node.get("class_type") != "SaveImage":
                continue
            prefix = (node.get("inputs") or {}).get("filename_prefix")
            if isinstance(prefix, str) and prefix:
                pairs.append((str(node_id), prefix))
    return pairs


def history_prompt_has_save_image(history_entry: dict[str, Any]) -> bool:
    """True when the API prompt in history includes a SaveImage node."""
    prompt_field = history_entry.get("prompt") if isinstance(history_entry, dict) else None
    candidates: list[Any] = []
    if isinstance(prompt_field, dict):
        candidates.append(prompt_field)
    elif isinstance(prompt_field, list):
        candidates.extend(prompt_field)
    if isinstance(history_entry, dict):
        candidates.append(history_entry.get("api_prompt"))
    for candidate in candidates:
        if not isinstance(candidate, dict) or not candidate:
            continue
        for value in candidate.values():
            if isinstance(value, dict) and value.get("class_type") == "SaveImage":
                return True
    return False


def parse_ws_message(payload: dict[str, Any]) -> ExecutionCompleteEvent | None:
    """Parse a ComfyUI websocket JSON message for execution completion."""
    msg_type = payload.get("type")
    data = payload.get("data") or {}
    if msg_type == "executed":
        prompt_id = str(data.get("prompt_id") or "")
        if not prompt_id:
            return None
        return ExecutionCompleteEvent(prompt_id=prompt_id, node=str(data.get("node") or "") or None, raw=payload)
    if msg_type == "execution_success":
        prompt_id = str(data.get("prompt_id") or "")
        if not prompt_id:
            return None
        return ExecutionCompleteEvent(prompt_id=prompt_id, raw=payload)
    return None


class HistoryFallbackWatcher:
    """History polling safety net.

    Prompt IDs are only marked seen after the caller confirms successful resolution.
    Marking seen before sync was the Package 4.5 live-failure root cause: a transient
    miss permanently dropped the generation.
    """

    def __init__(self, *, base_url: str = DEFAULT_COMFY_BASE) -> None:
        self.base_url = base_url
        self.seen: set[str] = set()

    def bootstrap(self) -> None:
        """Do not pre-mark history. Startup reconcile + processed index prevent duplicates."""
        self.seen = set()

    def mark_seen(self, prompt_id: str) -> None:
        if prompt_id:
            self.seen.add(str(prompt_id))

    def unmark(self, prompt_id: str) -> None:
        self.seen.discard(str(prompt_id))

    def poll(self) -> list[str]:
        """Return unseen prompt IDs without marking them seen."""
        return poll_completed_prompt_ids(self.seen, base_url=self.base_url)
