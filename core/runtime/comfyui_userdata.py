#!/usr/bin/env python3
"""ComfyUI userdata API helpers — aligned to current ComfyUI_frontend api.ts.

Package 4.8.2 reverse-engineering notes
--------------------------------------
Modern ComfyUI (Comfy-Org/ComfyUI + ComfyUI_frontend) loads a sidebar workflow as:

  1. Discovery:
     GET /api/userdata?dir=workflows&recurse=true&split=false&full_info=true
     (frontend: api.listUserDataFullInfo('workflows'))
     Each entry: {path, size, modified, created} relative to the workflows dir.
     Sync prepends 'workflows/' → ComfyWorkflow.path = 'workflows/<file>.json'

  2. Open (left-click leaf):
     workflowService.openWorkflow(workflow)
       → ComfyWorkflow.load()
       → GET /api/userdata/{encodeURIComponent('workflows/<file>.json')}
       → JSON.parse(content)
       → app.loadGraphData(activeState, ...)

  3. Save As (reference write path):
     POST /api/userdata/{encodeURIComponent(path)}?overwrite=...&full_info=true
     body = raw JSON string (stringify defaults off when options object is passed)

Both /userdata and /api/userdata are registered by server.py. Frontend always
uses the /api prefix; AI Studio prefers /api and falls back to bare paths.

Does not call /prompt. Performs no browser automation.
"""

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
    """Return a basename-only workflow JSON name safe for userdata routes."""
    raw = str(filename or "").strip()
    if not raw:
        raise ValueError("Workflow userdata filename is empty.")
    normalized = raw.replace("\\", "/")
    if "://" in normalized or normalized.startswith("//"):
        raise ValueError(f"Unsafe workflow userdata filename (URL/UNC): {filename!r}")
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
    """Relative userdata path matching ComfyWorkflow.basePath + filename."""
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
        body = exc.read() if getattr(exc, "fp", None) is not None else b""
        return int(exc.code), body, str(exc)
    except urllib.error.URLError as exc:
        return 0, b"", str(exc.reason if hasattr(exc, "reason") else exc)


def _api_and_bare(base: str, route_with_query: str) -> list[str]:
    """Prefer /api-prefixed routes (frontend fetchApi), then bare routes."""
    if route_with_query.startswith("/"):
        route = route_with_query
    else:
        route = "/" + route_with_query
    return [f"{base}/api{route}", f"{base}{route}"]


def comfyui_reachable(base_url: str | None = None, *, timeout: float = 3.0) -> bool:
    base = normalize_comfy_base_url(base_url)
    for url in _api_and_bare(base, "/system_stats"):
        status, _body, _err = _request("GET", url, timeout=timeout)
        if status == 200:
            return True
    return False


def userdata_put_workflow(
    *,
    base_url: str | None,
    filename: str,
    content: bytes,
    overwrite: bool = True,
    full_info: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """POST workflow bytes exactly as ComfyUI_frontend api.storeUserData does.

    URL shape: /api/userdata/{encodeURIComponent('workflows/<file>.json')}
               ?overwrite=true|false&full_info=true|false
    Body: raw JSON bytes (not double-encoded).
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
            "full_info": None,
        }
    base = normalize_comfy_base_url(base_url)
    encoded = urllib.parse.quote(rel, safe="")
    query = (
        f"overwrite={'true' if overwrite else 'false'}"
        f"&full_info={'true' if full_info else 'false'}"
    )
    last: dict[str, Any] = {
        "ok": False,
        "status_code": 0,
        "url": "",
        "relative_path": rel,
        "error": "no userdata PUT endpoint succeeded",
        "response_bytes": 0,
        "full_info": None,
    }
    # Do not set Content-Type to force JSON object parsing — frontend posts a
    # raw string body identical to disk JSON.
    for url in _api_and_bare(base, f"/userdata/{encoded}?{query}"):
        status, body, err = _request("POST", url, data=content, timeout=timeout)
        full_info_payload = None
        if status in {200, 201} and body:
            try:
                parsed = json.loads(body.decode("utf-8"))
                if isinstance(parsed, (dict, str)):
                    full_info_payload = parsed
            except (UnicodeDecodeError, json.JSONDecodeError):
                full_info_payload = None
        result = {
            "ok": status in {200, 201},
            "status_code": status,
            "url": url,
            "relative_path": rel,
            "error": err
            or (body.decode("utf-8", errors="replace") if status not in {200, 201} else ""),
            "response_bytes": len(body),
            "full_info": full_info_payload,
        }
        if result["ok"]:
            return result
        last = result
    return last


def userdata_get_workflow(
    *,
    base_url: str | None,
    filename: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """GET workflow bytes via the same path encoding the frontend uses."""
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
    last: dict[str, Any] = {
        "ok": False,
        "status_code": 0,
        "url": "",
        "relative_path": rel,
        "error": "no userdata GET endpoint succeeded",
        "body": b"",
    }
    for url in _api_and_bare(base, f"/userdata/{encoded}"):
        status, body, err = _request("GET", url, timeout=timeout)
        result = {
            "ok": status == 200,
            "status_code": status,
            "url": url,
            "relative_path": rel,
            "error": err,
            "body": body if status == 200 else b"",
        }
        if result["ok"]:
            return result
        last = result
    return last


def userdata_list_workflows(*, base_url: str | None, timeout: float = 10.0) -> dict[str, Any]:
    """List workflows using the frontend's listUserDataFullInfo query shape.

    Primary:
      GET /api/userdata?dir=workflows&recurse=true&split=false&full_info=true
    """
    base = normalize_comfy_base_url(base_url)
    primary = "/userdata?dir=workflows&recurse=true&split=false&full_info=true"
    candidates: list[str] = []
    for route in (
        primary,
        "/userdata?dir=workflows&full_info=true",
        "/userdata?dir=workflows",
        "/v2/userdata?path=workflows",
    ):
        candidates.extend(_api_and_bare(base, route))

    last: dict[str, Any] = {
        "ok": False,
        "names": [],
        "entries": [],
        "error": "no list endpoint succeeded",
        "url": "",
        "status_code": 0,
    }
    for url in candidates:
        status, body, err = _request("GET", url, timeout=timeout)
        if status != 200:
            last = {
                "ok": False,
                "status_code": status,
                "url": url,
                "names": [],
                "entries": [],
                "error": err,
            }
            continue
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            last = {
                "ok": False,
                "status_code": status,
                "url": url,
                "names": [],
                "entries": [],
                "error": "invalid JSON list",
            }
            continue
        names: list[str] = []
        entries: list[dict[str, Any]] = []
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, str):
                    names.append(item.split("/")[-1])
                    entries.append({"path": item, "name": item.split("/")[-1]})
                elif isinstance(item, dict):
                    path = str(item.get("path") or item.get("name") or item.get("file") or "")
                    if not path:
                        continue
                    name = path.split("/")[-1]
                    names.append(name)
                    entries.append(
                        {
                            "path": path,
                            "name": name,
                            "size": item.get("size"),
                            "modified": item.get("modified"),
                            "type": item.get("type"),
                        }
                    )
        elif isinstance(payload, dict):
            files = payload.get("files") or payload.get("entries") or payload.get("items") or []
            if isinstance(files, list):
                for item in files:
                    if isinstance(item, str):
                        names.append(item.split("/")[-1])
                        entries.append({"path": item, "name": item.split("/")[-1]})
                    elif isinstance(item, dict):
                        path = str(item.get("path") or item.get("name") or item.get("file") or "")
                        if not path:
                            continue
                        name = path.split("/")[-1]
                        names.append(name)
                        entries.append(
                            {
                                "path": path,
                                "name": name,
                                "size": item.get("size"),
                                "modified": item.get("modified"),
                                "type": item.get("type"),
                            }
                        )
        return {
            "ok": True,
            "status_code": status,
            "url": url,
            "names": names,
            "entries": entries,
            "error": "",
        }
    return last
