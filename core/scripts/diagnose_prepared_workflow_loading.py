#!/usr/bin/env python3
"""Read-only diagnostic for prepared workflow ComfyUI loading (Package 4.8.2)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.comfyui_userdata import (
    DEFAULT_COMFY_BASE_URL,
    comfyui_reachable,
    userdata_get_workflow,
    userdata_list_workflows,
)
from core.runtime.comfyui_workflow_loading import bytes_sha256, file_sha256
from core.runtime.preparation_identity import InvalidPreparationIdError, normalize_preparation_id
from core.runtime.prepared_workflow_index import find_by_preparation_id, preparations_log_path
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_provenance import hash_ui_workflow


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose prepared workflow loading against ComfyUI.")
    parser.add_argument("--preparation-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--comfyui-runtime", type=Path, default=None)
    parser.add_argument("--comfy-url", default=DEFAULT_COMFY_BASE_URL)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        preparation_id = normalize_preparation_id(args.preparation_id)
    except InvalidPreparationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    record = find_by_preparation_id(preparations_log_path(bundle.path("drive_root")), preparation_id)
    if record is None:
        print(f"ERROR: Preparation not found: {preparation_id}", file=sys.stderr)
        return 1

    prepared_dir = Path(str(record.get("drive_prepared_dir") or record.get("runtime_prepared_dir") or ""))
    source = prepared_dir / f"{preparation_id}.workflow.json"
    load_filename = f"ai_studio_{preparation_id}.json"
    comfyui_runtime = Path(args.comfyui_runtime or bundle.path("comfyui_runtime"))
    dest = comfyui_runtime / "user" / "default" / "workflows" / load_filename

    source_exists = source.is_file()
    dest_exists = dest.is_file()
    source_sha = file_sha256(source) if source_exists else ""
    dest_sha = file_sha256(dest) if dest_exists else ""
    schema_version = None
    node_count = 0
    link_count = 0
    ui_hash = ""
    if source_exists:
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
            schema_version = data.get("version")
            node_count = len(data.get("nodes") or [])
            link_count = len(data.get("links") or [])
            ui_hash = hash_ui_workflow(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            print(f"ERROR: Cannot parse source workflow: {exc}", file=sys.stderr)
            return 1

    reachable = comfyui_reachable(args.comfy_url)
    listed = False
    listing_url = ""
    listing_size_match = False
    retrieved_match = False
    userdata_get_sha = ""
    retrieve_error = ""
    if reachable:
        listing = userdata_list_workflows(base_url=args.comfy_url)
        listing_url = str(listing.get("url") or "")
        names = listing.get("names") or []
        listed = load_filename in names or any(load_filename in str(n) for n in names)
        for entry in listing.get("entries") or []:
            if str(entry.get("name") or "") == load_filename:
                size = entry.get("size")
                if dest_exists and size is not None:
                    listing_size_match = int(size) == dest.stat().st_size
                elif size is None:
                    listing_size_match = listed
                break
        got = userdata_get_workflow(base_url=args.comfy_url, filename=load_filename)
        if got.get("ok"):
            body = got.get("body") or b""
            userdata_get_sha = bytes_sha256(body)
            retrieved_match = bool(dest_exists and userdata_get_sha == dest_sha)
            if not dest_exists:
                retrieve_error = "userdata entry exists but filesystem loading copy missing"
        else:
            retrieve_error = str(got.get("error") or f"status {got.get('status_code')}")

    conclusion = "not_ready"
    recommended = (
        "Run open_prepared_workflow.py while ComfyUI is running, hard-reload the browser tab, "
        "then left-click the deterministic workflow filename."
    )
    if source_exists and dest_exists and reachable and retrieved_match and listed:
        conclusion = "registered_and_verified"
        recommended = (
            f"Hard-reload the ComfyUI browser tab (not sidebar Refresh). "
            f"Left-click {load_filename}. Automatic browser graph confirmation is unavailable."
        )
    elif source_exists and dest_exists and not reachable:
        conclusion = "filesystem_only_comfy_unreachable"
        recommended = "Start ComfyUI and re-run open_prepared_workflow.py, or File → Load the destination JSON."
    elif source_exists and not dest_exists:
        conclusion = "not_opened_yet"
        recommended = "Run: python core/scripts/open_prepared_workflow.py --preparation-id " + preparation_id
    elif dest_exists and source_exists and dest_sha != source_sha:
        conclusion = "loading_copy_present_hash_differs_from_archival"
        recommended = "Expected when load conversion stamps metadata; verify userdata GET match instead."

    payload = {
        "preparation_id": preparation_id,
        "source_workflow_path": str(source),
        "deterministic_loading_filename": load_filename,
        "comfyui_destination_path": str(dest),
        "userdata_relative_path": f"workflows/{load_filename}",
        "source_exists": source_exists,
        "destination_exists": dest_exists,
        "source_sha256": source_sha,
        "destination_sha256": dest_sha,
        "userdata_get_sha256": userdata_get_sha or None,
        "hashes_match_source_destination": bool(source_sha and dest_sha and source_sha == dest_sha),
        "workflow_json_schema_version": schema_version,
        "node_count": node_count,
        "link_count": link_count,
        "prepared_workflow_hash": ui_hash,
        "comfyui_base_url_available": reachable,
        "full_info_listing_url": listing_url or None,
        "workflow_appears_in_userdata_listing": listed,
        "listing_size_match": listing_size_match,
        "workflow_bytes_retrievable_from_comfyui": bool(reachable and not retrieve_error) or retrieved_match,
        "retrieved_bytes_match_destination": retrieved_match,
        "browser_load_verification_available": False,
        "browser_verification_limitations": (
            "AI Studio cannot confirm the browser canvas rendered. "
            "After hard-reload, left-click the deterministic filename and inspect the graph manually."
        ),
        "server_side_conclusion": conclusion,
        "recommended_user_action": recommended,
        "load_related_error": retrieve_error or None,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — Prepared Workflow Loading Diagnostic")
        print("=" * 40)
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
