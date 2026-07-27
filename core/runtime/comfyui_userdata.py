#!/usr/bin/env python3
"""ComfyUI userdata API helpers for prepared workflow registration (Package 4.8.1)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_COMFY_BASE_URL = "http://127.0.0.1:8188"
_SAFE_WORKFLOW_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.json$")


def normalize_comfy_base_url(base_url: str | None) -> str:
    text = (base_url or DEFAULT_COMFY_BASE_URL).strip().rstrip("/")
    return text or DEFAULT_COMFY_BASE_URL


def sanitize_workflow_userdata_filename(filename: str) -> str:
    """Return a basename-only workflow JSON name safe for userdata routes.

    Rejects absolute paths, traversal (`..`), nested directories, and names that
    are not constrained to the workflows namespace.
    """
    raw = str(filename or "").strip()
    if not raw:
        raise ValueError("Workflow userdata filename is empty.")
    # Normalize separators for inspection; reject any directory component.
    normalized = raw.replace("\\", "/")
    if "://" in normalized or normalized.startswith("//"):
        raise ValueError(f"Unsafe workflow userdata filename (URL/UNC): {filename!r}")
    # Drive-letter absolute paths (C:/...) and POSIX absolute (/...).
    if normalized.startswith("/") or (len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/"):
        raise ValueError(f"Unsafe workflow userdata filename (absolute path): {filename!r}")
    if "/" in normalized:
        raise ValueError(f"Unsafe workflow userdata filename (nested path): {filename!r}")
    if ".." in normalized:
        raise ValueError(f"Unsafe workflow userdata filename (path traversal): {filename!r}")
    name = normalized
    if not name or name in {".", ".."}:
        raise ValueError(f"Unsafe workflow userdata filename: {filename!r}")
    if not _SAFE_WORKFLOW_NAME.match(name):
        raise ValueError(
            f"Unsafe workflow userdata filename (must be a simple *.json name): {filename!r}"
        )
    return name


def userdata_workflows_relpath(filename: str) -> str:
    """Relative userdata path for a workflow JSON under workflows/."""
    name = sanitize_workflow_userdata_filename(filename)
    return f"workflows/{name}"


def _request(
    method: str,
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return int(resp.status), body, ""
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp is not None else b""
        return int(exc.code), body, str(exc)
    except urllib.error.URLError as exc:
        return 0, b"", str(exc.reason if hasattr(exc, "reason") else exc)


def comfyui_reachable(base_url: str | None = None, *, timeout: float = 3.0) -> bool:
    base = normalize_comfy_base_url(base_url)
    status, _body, _err = _request("GET", f"{base}/system_stats", timeout=timeout)
    return status == 200


def userdata_put_workflow(
    *,
    base_url: str | None,
    filename: str,
    content: bytes,
    overwrite: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """POST workflow bytes to ComfyUI /userdata/workflows/<file>.

    Modern frontend Workflows sidebar reads from userdata, not raw filesystem
    copies alone. Encoding slash as %2F matches ComfyUI frontend behavior.
    """
    try:
        rel = userdata_workflows_relpath(filename)
    except ValueError as exc:
        return {
            "ok": False,
            "status_code": 0,
            "url": "",
            "relative_path": "",
            "error": str(exc),
            "response_bytes": 0,
        }
    base = normalize_comfy_base_url(base_url)
    encoded = urllib.parse.quote(rel, safe="")
    query = "overwrite=true" if overwrite else "overwrite=false"
    url = f"{base}/userdata/{encoded}?{query}"
    status, body, err = _request(
        "POST",
        url,
        data=content,
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )
    return {
        "ok": status in {200, 201},
        "status_code": status,
        "url": url,
        "relative_path": rel,
        "error": err or (body.decode("utf-8", errors="replace") if status not in {200, 201} else ""),
        "response_bytes": len(body),
    }


def userdata_get_workflow(
    *,
    base_url: str | None,
    filename: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    try:
        rel = userdata_workflows_relpath(filename)
    except ValueError as exc:
        return {
            "ok": False,
            "status_code": 0,
            "url": "",
            "relative_path": "",
            "error": str(exc),
            "body": b"",
        }
    base = normalize_comfy_base_url(base_url)
    encoded = urllib.parse.quote(rel, safe="")
    url = f"{base}/userdata/{encoded}"
    status, body, err = _request("GET", url, timeout=timeout)
    return {
        "ok": status == 200,
        "status_code": status,
        "url": url,
        "relative_path": rel,
        "error": err,
        "body": body if status == 200 else b"",
    }


def userdata_list_workflows(*, base_url: str | None, timeout: float = 10.0) -> dict[str, Any]:
    """List workflow files via /userdata?dir=workflows (best-effort across versions)."""
    base = normalize_comfy_base_url(base_url)
    candidates = [
        f"{base}/userdata?dir=workflows",
        f"{base}/v2/userdata?path=workflows",
        f"{base}/userdata?dir={urllib.parse.quote('workflows')}",
    ]
    last: dict[str, Any] = {"ok": False, "names": [], "error": "no list endpoint succeeded"}
    for url in candidates:
        status, body, err = _request("GET", url, timeout=timeout)
        if status != 200:
            last = {"ok": False, "status_code": status, "url": url, "names": [], "error": err}
            continue
        names: list[str] = []
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            last = {"ok": False, "status_code": status, "url": url, "names": [], "error": "invalid JSON list"}
            continue
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, str):
                    names.append(item.split("/")[-1])
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("path") or item.get("file")
                    if name:
                        names.append(str(name).split("/")[-1])
        elif isinstance(payload, dict):
            files = payload.get("files") or payload.get("entries") or payload.get("items") or []
            if isinstance(files, list):
                for item in files:
                    if isinstance(item, str):
                        names.append(item.split("/")[-1])
                    elif isinstance(item, dict):
                        name = item.get("name") or item.get("path") or item.get("file")
                        if name:
                            names.append(str(name).split("/")[-1])
        return {"ok": True, "status_code": status, "url": url, "names": names, "error": ""}
    return last
