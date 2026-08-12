#!/usr/bin/env python3
"""Prepared workflow → ComfyUI frontend loading (Package 4.8.4).

Package 4.8.3 live evidence established the failure boundary:
  Localhost userdata registration/GET PASS; browser through Colab prod.colab.dev
  FAILS (native Save As POST 405, prepared GET 404) because the proxy decodes
  workflows%2F to workflows/ and stock aiohttp `/userdata/{file}` is single-segment.
  Serialization is NOT the primary cause. Package 4.8.4 applies reversible
  `{file:.*}` userdata route compatibility at install/launch.

Package 4.8.2 live operational acceptance FAILED:
  prep_870c685b-751a-4ed8-ac2c-ad12c4bae42b — userdata registered/verified/listed,
  schema 7/9, archival unchanged, but after hard-reload left-click left the canvas blank.
  Server registration alone is never treated as browser graph open.

Reverse-engineered mechanism (Comfy-Org/ComfyUI_frontend + ComfyUI user_manager):
  1. Sidebar discovery uses listUserDataFullInfo:
       GET /api/userdata?dir=workflows&recurse=true&split=false&full_info=true
  2. Left-click leaf calls workflowService.openWorkflow → ComfyWorkflow.load:
       GET /api/userdata/{encodeURIComponent('workflows/<file>.json')}
       → JSON.parse → app.loadGraphData(graph)
  3. Collision-safe sibling names (ai_studio_<id>_1.json) can leave an older
     broken ai_studio_<id>.json visible while registration targets the sibling.

Loading method (still used; browser open remains unverified until user confirms):
  - Build a frontend-compatible UI workflow load copy (do not mutate archival).
  - Write/overwrite deterministic: user/default/workflows/ai_studio_<prep_id>.json
  - POST the same bytes via /api/userdata/...&full_info=true
  - GET + SHA-256 + schema + graph integrity + listing size
  - Instruct hard-reload + left-click; never claim browser canvas confirmation.
  - Never call /prompt. No browser automation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .comfyui_userdata import (
    DEFAULT_COMFY_BASE_URL,
    comfyui_reachable,
    userdata_get_workflow,
    userdata_list_workflows,
    userdata_put_workflow,
)
from .comfyui_workflow_integrity import validate_graph_integrity
from .workflow_provenance import hash_ui_workflow

COMFYUI_LOAD_SCHEMA_VERSION = "0.4"
PACKAGE_VERSION = "4.8.4"


@dataclass
class OpenPreparedResult:
    preparation_id: str
    source_path: str = ""
    archival_unchanged: bool = True
    filesystem_destination: str = ""
    userdata_relative_path: str = ""
    load_filename: str = ""
    load_schema_version: str = COMFYUI_LOAD_SCHEMA_VERSION
    prepared_workflow_hash: str = ""
    comfyui_load_workflow_hash: str = ""
    source_sha256: str = ""
    destination_sha256: str = ""
    userdata_registered: bool = False
    userdata_verified: bool = False
    userdata_listed: bool = False
    userdata_list_size_matches: bool = False
    schema_valid: bool = False
    integrity_valid: bool = False
    integrity_errors: list[str] = field(default_factory=list)
    comfyui_reachable: bool = False
    node_count: int = 0
    link_count: int = 0
    dry_run: bool = False
    server_registration: str = "UNVERIFIED"
    browser_graph_open: str = "UNVERIFIED"
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    verification_limits: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def server_registration_verified(self) -> bool:
        return self.server_registration == "VERIFIED"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["server_registration_verified"] = self.server_registration_verified
        payload["operational_browser_open_accepted"] = False
        return payload


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_comfyui_ui_workflow_schema(data: dict[str, Any]) -> list[str]:
    """Validate required fields of ComfyUI UI schema version 0.4.

    Mirrors the frontend zod schema's required surface for loading
    (last_node_id, last_link_id, nodes, links, version). Does not claim
    full zod parity. Rejects non-objects so callers never substitute
    defaultGraph silently.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["workflow root must be a JSON object"]
    if "version" not in data:
        errors.append("missing version")
    else:
        try:
            float(data["version"])
        except (TypeError, ValueError):
            errors.append(f"invalid version: {data.get('version')!r}")
    if "last_node_id" not in data:
        errors.append("missing last_node_id")
    if "last_link_id" not in data:
        errors.append("missing last_link_id")
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        errors.append("nodes must be an array")
    elif not nodes:
        errors.append("nodes must be a non-empty array")
    else:
        for index, node in enumerate(nodes):
            if not isinstance(node, dict):
                errors.append(f"nodes[{index}] must be an object")
                continue
            if "id" not in node:
                errors.append(f"nodes[{index}] missing id")
            if not str(node.get("type") or "").strip():
                errors.append(f"nodes[{index}] missing type")
    links = data.get("links")
    if not isinstance(links, list):
        errors.append("links must be an array")
    else:
        for index, link in enumerate(links):
            if isinstance(link, list):
                if len(link) < 5:
                    errors.append(f"links[{index}] tuple too short")
            elif isinstance(link, dict):
                for key in ("id", "origin_id", "target_id"):
                    if key not in link:
                        errors.append(f"links[{index}] missing {key}")
            else:
                errors.append(f"links[{index}] must be a list or object")
    extra = data.get("extra")
    if extra is not None and not isinstance(extra, dict):
        errors.append("extra must be an object when present")
    return errors


def build_comfyui_load_workflow(archival: dict[str, Any]) -> dict[str, Any]:
    """Return a frontend-loadable copy without mutating the archival dict."""
    data = copy.deepcopy(archival)
    if "version" not in data or data.get("version") in (None, ""):
        data["version"] = float(COMFYUI_LOAD_SCHEMA_VERSION)
    else:
        try:
            data["version"] = float(data["version"])
        except (TypeError, ValueError):
            data["version"] = float(COMFYUI_LOAD_SCHEMA_VERSION)

    # Modern Save As often stamps a top-level UUID id; optional but helps tab identity.
    existing_id = data.get("id")
    if not isinstance(existing_id, str) or not existing_id.strip():
        data["id"] = str(uuid.uuid4())

    if "last_node_id" not in data and isinstance(data.get("nodes"), list) and data["nodes"]:
        try:
            data["last_node_id"] = max(int(n.get("id")) for n in data["nodes"] if isinstance(n, dict))
        except (TypeError, ValueError):
            pass
    if "last_link_id" not in data and isinstance(data.get("links"), list) and data["links"]:
        try:
            data["last_link_id"] = max(int(link[0]) for link in data["links"] if isinstance(link, list) and link)
        except (TypeError, ValueError, IndexError):
            pass

    extra = data.setdefault("extra", {})
    if isinstance(extra, dict):
        ai = extra.setdefault("ai_studio", {})
        if isinstance(ai, dict):
            ai["comfyui_load_schema_version"] = COMFYUI_LOAD_SCHEMA_VERSION
            ai["package_version_open"] = PACKAGE_VERSION
            # extra is ignored by hash_ui_workflow; stamp after other extra fields.
            ai["comfyui_load_workflow_hash"] = hash_ui_workflow(data)
    return data


def open_prepared_workflow_for_comfyui(
    *,
    preparation_id: str,
    source_workflow_path: Path,
    comfyui_runtime: Path,
    base_url: str | None = DEFAULT_COMFY_BASE_URL,
    dry_run: bool = False,
) -> OpenPreparedResult:
    result = OpenPreparedResult(preparation_id=preparation_id, dry_run=dry_run)
    result.verification_limits = [
        "Browser canvas/graph rendering is not verified programmatically.",
        "Left-click open is instructed for the user; AI Studio does not automate the browser.",
        "Server-side checks: filesystem copy, /api/userdata POST+GET, full_info listing, schema, integrity, node/link counts.",
        "SERVER REGISTRATION VERIFIED is not operational acceptance of browser graph open.",
    ]
    result.browser_graph_open = "UNVERIFIED"
    result.server_registration = "UNVERIFIED"
    source = source_workflow_path
    result.source_path = str(source)
    if not source.is_file():
        result.errors.append(f"Prepared workflow missing: {source}")
        return result

    try:
        archival = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.errors.append(f"Cannot parse prepared workflow: {exc}")
        return result
    if not isinstance(archival, dict):
        result.errors.append("Prepared workflow root must be a JSON object.")
        return result

    result.source_sha256 = file_sha256(source)
    result.prepared_workflow_hash = hash_ui_workflow(archival)
    load_data = build_comfyui_load_workflow(archival)
    schema_errors = validate_comfyui_ui_workflow_schema(load_data)
    result.schema_valid = not schema_errors
    if schema_errors:
        result.errors.append("Frontend load schema invalid: " + "; ".join(schema_errors))
        return result
    integrity_errors = validate_graph_integrity(load_data)
    result.integrity_errors = integrity_errors
    result.integrity_valid = not integrity_errors
    if integrity_errors:
        result.errors.append("Graph integrity invalid: " + "; ".join(integrity_errors))
        return result

    result.comfyui_load_workflow_hash = hash_ui_workflow(load_data)
    result.load_schema_version = str(load_data.get("version") or COMFYUI_LOAD_SCHEMA_VERSION)
    result.node_count = len(load_data.get("nodes") or [])
    result.link_count = len(load_data.get("links") or [])
    # Compact JSON matches frontend storeUserData of an already-stringified body.
    # Pretty-print remains valid; keep stable indent for hash diagnostics.
    load_text = json.dumps(load_data, indent=2) + "\n"
    load_bytes = load_text.encode("utf-8")

    # Deterministic AI Studio-owned name — overwrite in place (no _1 siblings).
    load_filename = f"ai_studio_{preparation_id}.json"
    dest_dir = Path(comfyui_runtime) / "user" / "default" / "workflows"
    dest_path = dest_dir / load_filename
    result.load_filename = load_filename
    result.filesystem_destination = str(dest_path)
    result.userdata_relative_path = f"workflows/{load_filename}"

    if dry_run:
        result.messages.append("Dry run — no filesystem write or userdata POST performed.")
        result.comfyui_reachable = comfyui_reachable(base_url)
        result.instructions = _instructions(result, registered=False, verified=False)
        result.server_registration = "UNVERIFIED"
        result.browser_graph_open = "UNVERIFIED"
        return result

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(load_bytes)
    result.destination_sha256 = file_sha256(dest_path)
    if result.destination_sha256 != bytes_sha256(load_bytes):
        result.errors.append("Filesystem loading copy hash mismatch after write.")
        return result
    result.messages.append(f"Wrote ComfyUI loading copy (overwrite): {dest_path}")

    if file_sha256(source) != result.source_sha256:
        result.errors.append("Archival prepared workflow changed unexpectedly during open.")
        result.archival_unchanged = False
        return result

    result.comfyui_reachable = comfyui_reachable(base_url)
    if result.comfyui_reachable:
        put = userdata_put_workflow(
            base_url=base_url,
            filename=load_filename,
            content=load_bytes,
            overwrite=True,
            full_info=True,
        )
        result.userdata_registered = bool(put.get("ok"))
        if result.userdata_registered:
            result.messages.append(
                f"Registered with ComfyUI userdata: {put.get('relative_path')} via {put.get('url')}"
            )
            got = userdata_get_workflow(base_url=base_url, filename=load_filename)
            got_body = got.get("body") or b""
            if got.get("ok") and bytes_sha256(got_body) == bytes_sha256(load_bytes):
                try:
                    parsed = json.loads(got_body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    result.messages.append(f"WARNING: userdata GET JSON parse failed: {exc}")
                else:
                    parse_errors = validate_comfyui_ui_workflow_schema(parsed if isinstance(parsed, dict) else {})
                    if parse_errors:
                        result.messages.append(
                            "WARNING: userdata GET body failed schema validation: "
                            + "; ".join(parse_errors)
                        )
                    elif len(parsed.get("nodes") or []) != result.node_count:
                        result.messages.append(
                            "WARNING: userdata GET node count mismatch "
                            f"({len(parsed.get('nodes') or [])} != {result.node_count})."
                        )
                    else:
                        result.userdata_verified = True
                        result.messages.append(
                            "Verified userdata GET bytes + schema + node count match loading copy."
                        )
            else:
                result.messages.append(
                    "WARNING: userdata GET did not verify matching bytes; "
                    "filesystem copy is present for File → Load fallback."
                )

            listing = userdata_list_workflows(base_url=base_url)
            names = listing.get("names") or []
            result.userdata_listed = load_filename in names or any(
                load_filename in str(n) for n in names
            )
            for entry in listing.get("entries") or []:
                if str(entry.get("name") or "") == load_filename:
                    size = entry.get("size")
                    if size is None or int(size) == len(load_bytes):
                        result.userdata_list_size_matches = True
                    else:
                        result.messages.append(
                            f"WARNING: listing size {size} != load bytes {len(load_bytes)}"
                        )
                    break
            if result.userdata_listed:
                result.messages.append(
                    f"Workflow listed by ComfyUI userdata discovery ({listing.get('url')})."
                )
            else:
                result.messages.append(
                    "WARNING: workflow not present in userdata full_info listing yet. "
                    "Hard-reload the ComfyUI browser tab (not the sidebar Refresh icon), "
                    "then left-click the workflow name."
                )
        else:
            result.messages.append(
                "WARNING: ComfyUI userdata registration failed "
                f"(status={put.get('status_code')}: {put.get('error')}). "
                "Filesystem loading copy was still written."
            )
    else:
        result.messages.append(
            "ComfyUI HTTP API unreachable — wrote filesystem loading copy only. "
            "Start ComfyUI, hard-reload the browser tab, then re-run open."
        )

    result.instructions = _instructions(
        result,
        registered=result.userdata_registered and result.userdata_verified,
        verified=result.userdata_verified,
    )
    if (
        result.userdata_registered
        and result.userdata_verified
        and result.userdata_listed
        and result.userdata_list_size_matches
        and result.schema_valid
        and result.integrity_valid
        and result.archival_unchanged
    ):
        result.server_registration = "VERIFIED"
    elif result.filesystem_destination and Path(result.filesystem_destination).is_file():
        result.server_registration = "PARTIAL"
    else:
        result.server_registration = "FAILED"
    result.browser_graph_open = "UNVERIFIED"
    return result


def _instructions(result: OpenPreparedResult, *, registered: bool, verified: bool) -> list[str]:
    lines = [
        "Prepared workflow registered with ComfyUI."
        if registered and verified
        else "Prepared workflow loading copy is available.",
        "Automatic browser graph confirmation is unavailable.",
        "Opening does not queue a prompt and does not call /prompt.",
        "1. Open the ComfyUI page.",
        "2. Hard-reload the entire browser tab after external registration.",
        "3. Do not use the Workflows sidebar Refresh icon for this test",
        "   (sidebar refresh can leave workflows listed but unable to open until a full page reload).",
        "4. Open the Workflows sidebar.",
        f"5. Left-click the exact deterministic workflow filename: {result.load_filename}",
        "6. Confirm a graph with nodes appears on the canvas.",
        "7. Review the graph parameters.",
        "8. Click Run manually when ready.",
    ]
    if not (registered and verified):
        lines.append("Fallback if left-click fails: File → Load and select:")
        lines.append(f"   {result.filesystem_destination}")
    return lines
