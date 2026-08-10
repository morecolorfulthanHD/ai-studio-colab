#!/usr/bin/env python3
"""Read-only live ComfyUI environment + workflow-open diagnostics (Package 4.8.3).

Captures backend/frontend version signals, custom nodes, object_info presence,
prepared/load hashes, and prints exact manual browser evidence steps.

Never mutates workflows, userdata, settings, or runtime state.
Never calls /prompt. Never automates the browser.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from .comfyui_userdata import (
    DEFAULT_COMFY_BASE_URL,
    comfyui_reachable,
    normalize_comfy_base_url,
    userdata_get_workflow,
    userdata_list_workflows,
)
from .comfyui_workflow_integrity import (
    check_nodes_against_object_info,
    compare_workflow_structures,
    summarize_workflow_structure,
    validate_graph_integrity,
)
from .comfyui_workflow_loading import (
    build_comfyui_load_workflow,
    bytes_sha256,
    file_sha256,
    validate_comfyui_ui_workflow_schema,
)
from .workflow_provenance import hash_ui_workflow


KNOWN_GOOD_CONTROL_FILENAME = "ai_studio_known_good_control.json"


def _request_json(base_url: str, route: str, *, timeout: float = 8.0) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    base = normalize_comfy_base_url(base_url)
    candidates = [f"{base}/api{route}", f"{base}{route}"]
    last_error = "unreachable"
    for url in candidates:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                body = resp.read()
                status = int(resp.status)
        except urllib.error.HTTPError as exc:
            body = exc.read() if getattr(exc, "fp", None) is not None else b""
            status = int(exc.code)
            last_error = str(exc)
        except urllib.error.URLError as exc:
            last_error = str(exc.reason if hasattr(exc, "reason") else exc)
            continue
        if status != 200:
            last_error = f"status {status}"
            continue
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = f"invalid JSON: {exc}"
            continue
        return {"ok": True, "url": url, "payload": payload, "error": ""}
    return {"ok": False, "url": "", "payload": None, "error": last_error}


def _git_head(path: Path) -> dict[str, Any]:
    if not path.is_dir():
        return {"available": False, "error": f"missing: {path}"}
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
        describe = subprocess.check_output(
            ["git", "-C", str(path), "describe", "--tags", "--always", "--dirty"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
        return {"available": True, "commit": commit, "describe": describe, "error": ""}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "commit": None, "describe": None, "error": str(exc)}


def _read_package_version(path: Path) -> str | None:
    for candidate in (
        path / "package.json",
        path / "web_custom_versions" / "desktop_app" / "package.json",
    ):
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("version"):
                    return str(data["version"])
            except (OSError, json.JSONDecodeError):
                continue
    return None


def list_custom_node_packages(comfyui_runtime: Path) -> list[dict[str, Any]]:
    custom_nodes = Path(comfyui_runtime) / "custom_nodes"
    if not custom_nodes.is_dir():
        return []
    packages: list[dict[str, Any]] = []
    for entry in sorted(custom_nodes.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith("."):
            continue
        if not entry.is_dir():
            continue
        if entry.name in {"__pycache__", "websocket_image_save.py"}:
            continue
        packages.append(
            {
                "name": entry.name,
                "path": str(entry),
                "git": _git_head(entry),
                "has_js": any(entry.rglob("*.js")) or (entry / "web").is_dir() or (entry / "js").is_dir(),
            }
        )
    return packages


def capture_live_environment(
    *,
    comfyui_runtime: Path,
    base_url: str | None = DEFAULT_COMFY_BASE_URL,
) -> dict[str, Any]:
    """Gather read-only environment signals for workflow-open investigations."""
    runtime = Path(comfyui_runtime)
    base = normalize_comfy_base_url(base_url)
    reachable = comfyui_reachable(base)
    system_stats = _request_json(base, "/system_stats") if reachable else {"ok": False, "error": "unreachable"}
    features = _request_json(base, "/features") if reachable else {"ok": False, "error": "unreachable"}
    object_info = _request_json(base, "/object_info") if reachable else {"ok": False, "error": "unreachable"}
    extensions = _request_json(base, "/extensions") if reachable else {"ok": False, "error": "unreachable"}

    frontend_version = None
    frontend_package = None
    if isinstance(system_stats.get("payload"), dict):
        system = system_stats["payload"].get("system") or {}
        if isinstance(system, dict):
            frontend_version = system.get("comfyui_version") or system.get("frontend_version")
            # Some builds nest differently.
            for key in ("comfyui_version", "argv", "python_version", "pytorch_version"):
                system.setdefault(key, system.get(key))
    # Embedded web package markers.
    for rel in (
        "web/package.json",
        "web_custom_versions/desktop_app/package.json",
        "web/index.html",
    ):
        candidate = runtime / rel
        if candidate.name == "package.json" and candidate.is_file():
            frontend_package = _read_package_version(candidate.parent)
            break

    launch_argv = None
    if isinstance(system_stats.get("payload"), dict):
        system = system_stats["payload"].get("system") or {}
        if isinstance(system, dict):
            launch_argv = system.get("argv")

    object_info_payload = object_info.get("payload") if object_info.get("ok") else None
    node_count = len(object_info_payload) if isinstance(object_info_payload, dict) else None

    extension_list: list[str] = []
    if isinstance(extensions.get("payload"), list):
        extension_list = [str(x) for x in extensions["payload"]]
    elif isinstance(features.get("payload"), dict):
        # features may advertise extension-related flags only.
        pass

    return {
        "read_only": True,
        "mutates_state": False,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "comfyui_base_url": base,
        "comfyui_reachable": reachable,
        "comfyui_runtime": str(runtime),
        "comfyui_backend_git": _git_head(runtime),
        "comfyui_frontend_version_signal": frontend_version,
        "comfyui_frontend_package_version": frontend_package,
        "launch_arguments": launch_argv,
        "system_stats_ok": bool(system_stats.get("ok")),
        "system_stats": system_stats.get("payload") if system_stats.get("ok") else None,
        "system_stats_error": system_stats.get("error") or None,
        "features_ok": bool(features.get("ok")),
        "features": features.get("payload") if features.get("ok") else None,
        "extensions": extension_list,
        "custom_node_packages": list_custom_node_packages(runtime),
        "loaded_node_count": node_count,
        "object_info_available": isinstance(object_info_payload, dict),
        "browser_accessible_comfyui_url": base,
        "notes": [
            "Frontend package/build identifiers vary by install method; "
            "prefer system_stats + web package.json + browser DevTools Network for the live build.",
            "Custom-node isolation uses ComfyUI --disable-all-custom-nodes temporarily; "
            "do not uninstall or delete packages for this investigation.",
        ],
    }


def browser_evidence_instructions(load_filename: str) -> list[str]:
    return [
        "MANUAL BROWSER EVIDENCE CAPTURE (required — no browser automation):",
        "1. Open the ComfyUI page in the browser tab that talks to this runtime.",
        "2. Hard-reload the tab (Windows: Ctrl+Shift+R or Ctrl+F5).",
        "3. Open DevTools → Console. Clear the console.",
        "4. Open DevTools → Network. Clear network log. Enable Preserve log.",
        f"5. Open the Workflows sidebar (do NOT click the sidebar Refresh icon).",
        f"6. Left-click exactly once: {load_filename}",
        "7. Console: copy every red error and full stack trace (JSON.parse, loadGraphData,",
        "   graph.configure, node reconstruction, extension hooks).",
        "8. Network: locate the userdata GET for this file",
        f"   (path contains workflows%2F{load_filename} or workflows/{load_filename}).",
        "9. Record for that request: status code, content-type, content-disposition,",
        "   response size, and the first ~200 chars of the response body preview.",
        "10. Confirm whether the response body starts with '{' (object) or '\"' (string).",
        "11. If the body is a JSON string (double-encoded), note that explicitly.",
        "12. Save notes under keys: console_errors, network_get_status, network_get_preview,",
        "    canvas_blank (true/false), tab_changed (true/false).",
    ]


def control_test_instructions() -> list[str]:
    return [
        "CONTROL TEST — known-good workflow saved by THIS frontend (do this BEFORE changing AI Studio):",
        "1. In ComfyUI, open a working txt2img graph manually (or build one).",
        f"2. Use ComfyUI Save / Save As and save as: {KNOWN_GOOD_CONTROL_FILENAME}",
        "3. Hard-reload the browser tab.",
        f"4. Left-click {KNOWN_GOOD_CONTROL_FILENAME} in the Workflows sidebar.",
        "5. Record known_good_saved_by_comfyui:",
        "   - appears_in_sidebar",
        "   - get_succeeds",
        "   - left_click_opens_graph",
        "   - canvas_populated",
        "6. If the known-good workflow ALSO fails to open after hard-reload:",
        "   STOP — treat this as a ComfyUI/frontend/runtime problem, not AI Studio serialization.",
        "7. Then run custom-node isolation (temporary):",
        "   A) Current Full mode (baseline)",
        "   B) Restart ComfyUI with --disable-all-custom-nodes (do not uninstall/delete)",
        "   C) Retest known-good AND AI Studio prepared workflow in that mode",
        "8. If BOTH start working with custom nodes disabled, isolate the offending package",
        "   by re-enabling packages one at a time; do not conclude 'custom nodes' generically.",
    ]


def round_trip_test_instructions() -> list[str]:
    return [
        "ROUND-TRIP CONTROL (high value before any serialization refactor):",
        f"1. Retrieve {KNOWN_GOOD_CONTROL_FILENAME} via GET /api/userdata/...",
        "2. Change ONLY the positive prompt text.",
        "3. Register under a new deterministic filename via the same AI Studio userdata POST path.",
        "4. Hard-reload, left-click the new filename.",
        "5. If round-trip succeeds → failure is likely in AI Studio prepared/canonical structure.",
        "6. If round-trip fails → failure is likely registration/runtime/frontend behavior.",
    ]


def analyze_preparation_open(
    *,
    preparation_id: str,
    source_workflow_path: Path,
    comfyui_runtime: Path,
    base_url: str | None = DEFAULT_COMFY_BASE_URL,
    known_good_filename: str = KNOWN_GOOD_CONTROL_FILENAME,
) -> dict[str, Any]:
    """Read-only analysis of a preparation vs live ComfyUI state."""
    env = capture_live_environment(comfyui_runtime=comfyui_runtime, base_url=base_url)
    load_filename = f"ai_studio_{preparation_id}.json"
    source = Path(source_workflow_path)
    dest = Path(comfyui_runtime) / "user" / "default" / "workflows" / load_filename

    source_exists = source.is_file()
    dest_exists = dest.is_file()
    archival: dict[str, Any] | None = None
    load_data: dict[str, Any] | None = None
    source_sha = file_sha256(source) if source_exists else ""
    dest_sha = file_sha256(dest) if dest_exists else ""
    prepared_hash = ""
    load_hash = ""
    schema_errors: list[str] = []
    integrity_errors: list[str] = []
    version_observed = None

    if source_exists:
        try:
            archival = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                **env,
                "preparation_id": preparation_id,
                "error": f"cannot parse archival workflow: {exc}",
            }
        if isinstance(archival, dict):
            prepared_hash = hash_ui_workflow(archival)
            load_data = build_comfyui_load_workflow(archival)
            # build_comfyui_load_workflow is pure (deepcopy); archival dict unchanged.
            load_hash = hash_ui_workflow(load_data)
            schema_errors = validate_comfyui_ui_workflow_schema(load_data)
            integrity_errors = validate_graph_integrity(load_data)
            version_observed = load_data.get("version")

    userdata_get = None
    userdata_get_sha = ""
    userdata_body_preview = ""
    userdata_starts_with_object = None
    listing = None
    listed = False
    list_size_match = False
    if env["comfyui_reachable"]:
        listing = userdata_list_workflows(base_url=base_url)
        names = listing.get("names") or []
        listed = load_filename in names
        for entry in listing.get("entries") or []:
            if str(entry.get("name") or "") == load_filename:
                size = entry.get("size")
                if dest_exists and size is not None:
                    list_size_match = int(size) == dest.stat().st_size
                elif size is None:
                    list_size_match = listed
                break
        userdata_get = userdata_get_workflow(base_url=base_url, filename=load_filename)
        if userdata_get.get("ok"):
            body = userdata_get.get("body") or b""
            userdata_get_sha = bytes_sha256(body)
            userdata_body_preview = body[:200].decode("utf-8", errors="replace")
            stripped = body.lstrip()
            userdata_starts_with_object = bool(stripped.startswith(b"{"))

    object_info_payload = None
    if env.get("object_info_available"):
        # Re-fetch for typed checks (env already confirmed availability).
        fetched = _request_json(normalize_comfy_base_url(base_url), "/object_info")
        if fetched.get("ok") and isinstance(fetched.get("payload"), dict):
            object_info_payload = fetched["payload"]

    object_info_check = check_nodes_against_object_info(load_data or {}, object_info_payload)

    known_good_analysis = None
    if env["comfyui_reachable"]:
        kg = userdata_get_workflow(base_url=base_url, filename=known_good_filename)
        if kg.get("ok"):
            try:
                known_good = json.loads((kg.get("body") or b"").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                known_good_analysis = {"available": False, "error": f"parse failed: {exc}"}
            else:
                comparison = None
                if load_data is not None:
                    comparison = compare_workflow_structures(known_good, load_data)
                known_good_analysis = {
                    "available": True,
                    "filename": known_good_filename,
                    "sha256": bytes_sha256(kg.get("body") or b""),
                    "structure": summarize_workflow_structure(known_good),
                    "integrity": validate_graph_integrity(known_good),
                    "frontend_version_in_extra": (
                        (known_good.get("extra") or {}).get("frontendVersion")
                        if isinstance(known_good, dict)
                        else None
                    ),
                    "comparison_to_ai_studio_load_copy": comparison,
                }
        else:
            known_good_analysis = {
                "available": False,
                "filename": known_good_filename,
                "error": kg.get("error") or f"status {kg.get('status_code')}",
                "hint": f"Save a known-good workflow as {known_good_filename} via ComfyUI Save As first.",
            }

    root_cause_status = {
        "status": "unproven",
        "statement": (
            "Package 4.8.2 live failure is confirmed (sidebar visible, left-click blank canvas) "
            "but the exact browser-side refusal reason is NOT yet proven without console/network "
            "evidence and the known-good control result."
        ),
        "do_not_speculate": True,
        "next_required_evidence": [
            "known_good_saved_by_comfyui left-click result after hard-reload",
            "browser console stack on AI Studio left-click",
            "userdata GET response preview (object vs string)",
            "structured diff vs known-good when available",
            "custom-node isolation matrix if known-good also fails",
        ],
    }

    return {
        **env,
        "preparation_id": preparation_id,
        "prepared_workflow_load_filename": load_filename,
        "archival_source_path": str(source),
        "filesystem_load_copy_path": str(dest),
        "source_exists": source_exists,
        "destination_exists": dest_exists,
        "source_sha256": source_sha or None,
        "destination_sha256": dest_sha or None,
        "canonical_prepared_hash": prepared_hash or None,
        "frontend_load_copy_hash": load_hash or None,
        "observed_workflow_version": version_observed,
        "schema_errors": schema_errors,
        "integrity_errors": integrity_errors,
        "schema_valid": not schema_errors if source_exists else False,
        "integrity_valid": not integrity_errors if source_exists else False,
        "object_info_node_check": object_info_check,
        "userdata_listing_ok": bool(listing and listing.get("ok")),
        "userdata_listing_url": (listing or {}).get("url"),
        "workflow_listed": listed,
        "listing_size_match": list_size_match,
        "userdata_get_ok": bool(userdata_get and userdata_get.get("ok")),
        "userdata_get_url": (userdata_get or {}).get("url"),
        "userdata_get_sha256": userdata_get_sha or None,
        "userdata_get_starts_with_object": userdata_starts_with_object,
        "userdata_get_preview": userdata_body_preview or None,
        "known_good_control": known_good_analysis,
        "browser_graph_open": "UNVERIFIED",
        "server_registration": (
            "VERIFIED"
            if (
                listed
                and list_size_match
                and userdata_get
                and userdata_get.get("ok")
                and dest_exists
                and userdata_get_sha
                and dest_sha
                and userdata_get_sha == dest_sha
                and not schema_errors
                and not integrity_errors
            )
            else "INCOMPLETE_OR_UNVERIFIED"
        ),
        "root_cause": root_cause_status,
        "browser_evidence_instructions": browser_evidence_instructions(load_filename),
        "control_test_instructions": control_test_instructions(),
        "round_trip_test_instructions": round_trip_test_instructions(),
        "custom_node_isolation_notes": [
            "Supported temporary flag: --disable-all-custom-nodes",
            "Do not uninstall or delete custom node packages for this test.",
            "Retest both known-good and AI Studio workflows in each state.",
            "Only pin/disable a specific extension after it is isolated.",
        ],
    }
