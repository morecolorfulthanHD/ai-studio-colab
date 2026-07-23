#!/usr/bin/env python3
"""Copy a prepared workflow into ComfyUI user workflows for manual loading."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.preparation_identity import InvalidPreparationIdError, normalize_preparation_id
from core.runtime.prepared_workflow_index import find_by_preparation_id, preparations_log_path
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Place prepared workflow JSON in ComfyUI user workflows directory."
    )
    parser.add_argument("--preparation-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--comfyui-runtime", type=Path, default=None)
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
    source = prepared_dir / f"{preparation_id}.workflow.json"
    if not source.is_file():
        print(f"ERROR: Prepared workflow missing: {source}", file=sys.stderr)
        return 1

    comfyui_runtime = args.comfyui_runtime or bundle.path("comfyui_runtime")
    dest_dir = Path(comfyui_runtime) / "user" / "default" / "workflows"
    dest_name = f"ai_studio_{preparation_id}.json"
    dest_path = dest_dir / dest_name
    if dest_path.exists():
        stamp = 1
        while True:
            candidate = dest_dir / f"ai_studio_{preparation_id}_{stamp}.json"
            if not candidate.exists():
                dest_path = candidate
                dest_name = candidate.name
                break
            stamp += 1

    payload = {
        "preparation_id": preparation_id,
        "source": str(source),
        "destination": str(dest_path),
        "dry_run": args.dry_run,
    }

    if args.dry_run:
        payload["action"] = "would_copy"
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest_path)
        payload["action"] = "copied"

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — Open Prepared Workflow")
        print("=" * 40)
        print(f"Preparation ID: {preparation_id}")
        print(f"Source:         {source}")
        print(f"Destination:    {dest_path}")
        if args.dry_run:
            print("\nDry run — no file copied.")
        else:
            print("\nPrepared workflow copied to ComfyUI user workflows.")
        print("\nNext steps (manual):")
        print("  1. Open ComfyUI in your browser.")
        print("  2. Open the Workflows sidebar and choose Load.")
        print(f"  3. Select workflow file: {dest_name}")
        print("  4. Review the graph, then queue the prompt when ready.")
        print("\nThis command only performs deterministic file placement; it does not open ComfyUI or auto-queue.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
