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


def fetch_history(base_url: str = DEFAULT_COMFY_BASE, prompt_id: str | None = None) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/history"
    if prompt_id:
        url = f"{url}/{prompt_id}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
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


def extract_output_files(history_entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return final output metadata from a single prompt history entry."""
    outputs = history_entry.get("outputs") or {}
    files: list[dict[str, Any]] = []
    if not isinstance(outputs, dict):
        return files
    for node_id, node_output in outputs.items():
        if not isinstance(node_output, dict):
            continue
        for key in ("images", "gifs", "videos"):
            items = node_output.get(key) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                filename = item.get("filename")
                if not filename:
                    continue
                # Ignore preview/temp subfolders.
                subfolder = str(item.get("subfolder") or "")
                file_type = str(item.get("type") or "output")
                if file_type.lower() in {"temp", "preview"} or subfolder.lower() in {"temp", "preview"}:
                    continue
                files.append(
                    {
                        "node_id": str(node_id),
                        "filename": filename,
                        "subfolder": subfolder,
                        "type": file_type,
                        "kind": key,
                    }
                )
    return files


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
