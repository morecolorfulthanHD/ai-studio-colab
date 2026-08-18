#!/usr/bin/env python3
"""Register a prepared workflow for ComfyUI frontend loading (Package 4.8.3).

Server registration success is NOT operational browser-open acceptance.
"""

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

from core.runtime.comfyui_userdata import DEFAULT_COMFY_BASE_URL
from core.runtime.comfyui_workflow_loading import open_prepared_workflow_for_comfyui
from core.runtime.preparation_identity import InvalidPreparationIdError, normalize_preparation_id
from core.runtime.prepared_workflow_index import find_by_preparation_id, preparations_log_path
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register a prepared workflow with ComfyUI (userdata + loading copy). "
            "Does not auto-queue or open the browser graph. "
            "Server registration VERIFIED != browser graph open."
        )
    )
    parser.add_argument("--preparation-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--comfyui-runtime", type=Path, default=None)
    parser.add_argument("--comfy-url", default=DEFAULT_COMFY_BASE_URL)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
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
    comfyui_runtime = args.comfyui_runtime or bundle.path("comfyui_runtime")
    metadata_path = prepared_dir / f"{preparation_id}.metadata.json"
    metadata = {}
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}

    from core.runtime.generation_derivation import restage_derivation_inputs_for_open

    restage_messages, restage_errors = restage_derivation_inputs_for_open(
        prepared_dir=prepared_dir,
        metadata=metadata if isinstance(metadata, dict) else {},
        comfyui_input_dir=Path(comfyui_runtime) / "input",
    )

    source = prepared_dir / f"{preparation_id}.workflow.json"

    result = open_prepared_workflow_for_comfyui(
        preparation_id=preparation_id,
        source_workflow_path=source,
        comfyui_runtime=Path(comfyui_runtime),
        base_url=args.comfy_url,
        dry_run=args.dry_run,
    )
    payload = result.to_dict()

    if args.json:
        if restage_errors:
            print(json.dumps({"restage_errors": restage_errors}, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — Open Prepared Workflow")
        print("=" * 40)
        for message in restage_messages:
            print(f"Note: {message}")
        for error in restage_errors:
            print(error, file=sys.stderr)
        if restage_errors:
            return 1
        print(f"Preparation ID:     {result.preparation_id}")
        print(f"Archival source:    {result.source_path}")
        print(f"Loading copy:       {result.filesystem_destination}")
        print(f"Userdata path:      {result.userdata_relative_path}")
        print(f"ComfyUI reachable:  {result.comfyui_reachable}")
        print(f"Userdata registered:{result.userdata_registered}")
        print(f"Userdata verified:  {result.userdata_verified}")
        print(f"Userdata listed:    {result.userdata_listed}")
        print(f"List size match:    {result.userdata_list_size_matches}")
        print(f"Schema valid:       {result.schema_valid}")
        print(f"Integrity valid:    {result.integrity_valid}")
        print(f"Nodes/links:        {result.node_count}/{result.link_count}")
        print(f"Archival unchanged: {result.archival_unchanged}")
        print(f"SERVER REGISTRATION:{result.server_registration}")
        print(f"BROWSER GRAPH OPEN: {result.browser_graph_open}")
        for message in result.messages:
            print(f"Note: {message}")
        print()
        for line in result.instructions:
            print(line)
        for limit in result.verification_limits:
            print(f"Limit: {limit}")
        for error in result.errors:
            print(f"Error: {error}", file=sys.stderr)

    if not result.ok:
        return 1
    if args.dry_run:
        print("\nSERVER REGISTRATION: UNVERIFIED (dry-run)")
        print("BROWSER GRAPH OPEN: UNVERIFIED")
        return 0
    if not result.comfyui_reachable:
        print("\nSERVER REGISTRATION: PARTIAL", file=sys.stderr)
        print("BROWSER GRAPH OPEN: UNVERIFIED", file=sys.stderr)
        print(
            "Loading copy written; ComfyUI unreachable for userdata registration.",
            file=sys.stderr,
        )
        return 2
    full = (
        result.userdata_registered
        and result.userdata_verified
        and result.userdata_listed
        and result.userdata_list_size_matches
        and result.schema_valid
        and result.integrity_valid
        and result.archival_unchanged
    )
    if not full:
        print("\nSERVER REGISTRATION: PARTIAL", file=sys.stderr)
        print("BROWSER GRAPH OPEN: UNVERIFIED", file=sys.stderr)
        print(
            "Loading copy written; userdata verification or discovery incomplete.",
            file=sys.stderr,
        )
        return 2
    print("\nSERVER REGISTRATION: VERIFIED")
    print("BROWSER GRAPH OPEN: UNVERIFIED")
    print(
        "Operational acceptance requires a live hard-reload + left-click that "
        "opens the graph on the ComfyUI canvas."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
