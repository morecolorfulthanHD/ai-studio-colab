#!/usr/bin/env python3
"""Prepared workflow → ComfyUI frontend loading (Package 4.8.1).

Root cause (live Colab Package 4.8):
  open_prepared_workflow.py only copied JSON onto the filesystem under
  ComfyUI/user/default/workflows/. Modern ComfyUI frontends list and open
  sidebar workflows through the /userdata API. A raw disk copy can appear in
  some listings but clicking/Insert/drag fails because the workflow was never
  registered via userdata POST.

Verified loading method:
  1. Build a frontend load copy (preserves graph + extra.ai_studio).
  2. Write a separate filesystem loading copy under user/default/workflows/.
  3. POST the same bytes to /userdata/workflows%2F<name>.json when ComfyUI is up.
  4. GET the userdata entry back and verify SHA-256 match.
  5. Instruct the user to click the workflow name in the Workflows sidebar
     (or File → Load). Never claim browser graph open completed.
"""

from __future__ import annotations

import copy
import hashlib
import json
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
from .workflow_provenance import hash_ui_workflow

COMFYUI_LOAD_SCHEMA_VERSION = "0.4"
PACKAGE_VERSION = "4.8.1"


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
    comfyui_reachable: bool = False
    node_count: int = 0
    link_count: int = 0
    dry_run: bool = False
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def build_comfyui_load_workflow(archival: dict[str, Any]) -> dict[str, Any]:
    """Return a frontend-loadable copy without mutating the archival dict.

    Keeps UI graph structure (nodes/links). Ensures version and extra.ai_studio
    survive. Does not convert to API prompt format.
    """
    data = copy.deepcopy(archival)
    if "version" not in data or data.get("version") in (None, ""):
        data["version"] = float(COMFYUI_LOAD_SCHEMA_VERSION)
    else:
        # Preserve numeric 0.4 / 1.0 as JSON number when possible.
        try:
            data["version"] = float(data["version"])
        except (TypeError, ValueError):
            data["version"] = float(COMFYUI_LOAD_SCHEMA_VERSION)
    extra = data.setdefault("extra", {})
    if isinstance(extra, dict):
        ai = extra.setdefault("ai_studio", {})
        if isinstance(ai, dict):
            ai["comfyui_load_schema_version"] = COMFYUI_LOAD_SCHEMA_VERSION
            ai["package_version_open"] = PACKAGE_VERSION
    return data


def _collision_safe_path(dest_dir: Path, dest_name: str) -> Path:
    candidate = dest_dir / dest_name
    if not candidate.exists():
        return candidate
    stem = Path(dest_name).stem
    suffix = Path(dest_name).suffix
    stamp = 1
    while True:
        alt = dest_dir / f"{stem}_{stamp}{suffix}"
        if not alt.exists():
            return alt
        stamp += 1


def open_prepared_workflow_for_comfyui(
    *,
    preparation_id: str,
    source_workflow_path: Path,
    comfyui_runtime: Path,
    base_url: str | None = DEFAULT_COMFY_BASE_URL,
    dry_run: bool = False,
) -> OpenPreparedResult:
    result = OpenPreparedResult(preparation_id=preparation_id, dry_run=dry_run)
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
    result.comfyui_load_workflow_hash = hash_ui_workflow(load_data)
    result.load_schema_version = str(load_data.get("version") or COMFYUI_LOAD_SCHEMA_VERSION)
    result.node_count = len(load_data.get("nodes") or [])
    result.link_count = len(load_data.get("links") or [])
    load_bytes = (json.dumps(load_data, indent=2) + "\n").encode("utf-8")

    load_filename = f"ai_studio_{preparation_id}.json"
    dest_dir = Path(comfyui_runtime) / "user" / "default" / "workflows"
    dest_path = _collision_safe_path(dest_dir, load_filename)
    result.load_filename = dest_path.name
    result.filesystem_destination = str(dest_path)
    result.userdata_relative_path = f"workflows/{dest_path.name}"

    if dry_run:
        result.messages.append("Dry run — no filesystem write or userdata POST performed.")
        result.comfyui_reachable = comfyui_reachable(base_url)
        result.instructions = _instructions(result, registered=False, verified=False)
        return result

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(load_bytes)
    result.destination_sha256 = file_sha256(dest_path)
    if result.destination_sha256 != bytes_sha256(load_bytes):
        result.errors.append("Filesystem loading copy hash mismatch after write.")
        return result
    result.messages.append(f"Wrote ComfyUI loading copy: {dest_path}")

    # Confirm archival source unchanged.
    if file_sha256(source) != result.source_sha256:
        result.errors.append("Archival prepared workflow changed unexpectedly during open.")
        result.archival_unchanged = False
        return result

    result.comfyui_reachable = comfyui_reachable(base_url)
    if result.comfyui_reachable:
        put = userdata_put_workflow(
            base_url=base_url,
            filename=dest_path.name,
            content=load_bytes,
            overwrite=True,
        )
        result.userdata_registered = bool(put.get("ok"))
        if result.userdata_registered:
            result.messages.append(f"Registered with ComfyUI userdata: {put.get('relative_path')}")
            got = userdata_get_workflow(base_url=base_url, filename=dest_path.name)
            if got.get("ok") and bytes_sha256(got.get("body") or b"") == bytes_sha256(load_bytes):
                result.userdata_verified = True
                result.messages.append("Verified userdata bytes match loading copy.")
            else:
                result.messages.append(
                    "WARNING: userdata GET did not verify matching bytes; "
                    "filesystem copy is present for File → Load."
                )
            listing = userdata_list_workflows(base_url=base_url)
            names = listing.get("names") or []
            result.userdata_listed = dest_path.name in names or any(
                dest_path.name in str(n) for n in names
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
            "Start ComfyUI, then re-run open or use File → Load on the destination file."
        )

    result.instructions = _instructions(
        result,
        registered=result.userdata_registered and result.userdata_verified,
        verified=result.userdata_verified,
    )
    return result


def _instructions(result: OpenPreparedResult, *, registered: bool, verified: bool) -> list[str]:
    lines = [
        "Prepared workflow registered with ComfyUI."
        if registered
        else "Prepared workflow loading copy is available on disk.",
        "Automatic browser graph confirmation is unavailable.",
        "Opening does not queue a prompt and does not call /prompt.",
        "1. Open the ComfyUI page in your browser (refresh the Workflows list if needed).",
        "2. Open the Workflows sidebar.",
    ]
    if registered or verified:
        lines.append(f"3. Left-click the workflow name: {result.load_filename}")
        lines.append("   The workflow should open in a tab for review.")
    else:
        lines.append("3. Use File → Load (or Load Workflow) and select:")
        lines.append(f"   {result.filesystem_destination}")
    lines.extend(
        [
            "4. Confirm the graph appears on the canvas with your prepared parameters.",
            "5. Review or edit, then click Run when ready.",
        ]
    )
    return lines
