#!/usr/bin/env python3
"""Create a new corrected preparation from an existing one (Package 4.8.1).

Does not mutate the original immutable preparation archive. Allocates a new
prep_<uuid> using the archived parameters, optionally binding the active project.
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

from core.runtime.preparation_identity import InvalidPreparationIdError, normalize_preparation_id
from core.runtime.preparation_project_context import resolve_preparation_project
from core.runtime.prepared_workflow_index import find_by_preparation_id, preparations_log_path
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_library_preparation import prepare_library_workflow


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reprepare from an existing preparation archive without mutating it."
    )
    parser.add_argument("--preparation-id", required=True)
    parser.add_argument("--use-active-project", action="store_true")
    parser.add_argument("--project", default=None, help="Explicit project slug or id.")
    parser.add_argument("--global", dest="use_global", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.use_global and (args.project or args.use_active_project):
        print("ERROR: Conflicting project flags with --global.", file=sys.stderr)
        return 1

    try:
        preparation_id = normalize_preparation_id(args.preparation_id)
    except InvalidPreparationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    drive_root = bundle.path("drive_root")
    record = find_by_preparation_id(preparations_log_path(drive_root), preparation_id)
    if record is None:
        print(f"ERROR: Preparation not found: {preparation_id}", file=sys.stderr)
        return 1

    prepared_dir = Path(str(record.get("drive_prepared_dir") or record.get("runtime_prepared_dir") or ""))
    metadata_path = prepared_dir / f"{preparation_id}.metadata.json"
    if not metadata_path.is_file():
        print(f"ERROR: Preparation metadata missing: {metadata_path}", file=sys.stderr)
        return 1
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    workflow_identifier = str(metadata.get("workflow_identifier") or "")
    parameters = dict(metadata.get("parameters") or {})
    if not workflow_identifier:
        print("ERROR: Source preparation missing workflow_identifier.", file=sys.stderr)
        return 1

    use_global = bool(args.use_global)
    project_ref = args.project
    if args.use_active_project and not project_ref and not use_global:
        project_ref = None  # resolve_preparation_project uses active pointer
        context = resolve_preparation_project(drive_root, use_global=False, project_ref=None)
    elif use_global:
        context = resolve_preparation_project(drive_root, use_global=True, project_ref=None)
    elif project_ref:
        context = resolve_preparation_project(drive_root, use_global=False, project_ref=project_ref)
    else:
        # Default: keep original project fields if present, else active/global.
        slug = metadata.get("project_slug")
        if slug:
            context = resolve_preparation_project(drive_root, use_global=False, project_ref=str(slug))
        else:
            context = resolve_preparation_project(drive_root, use_global=False, project_ref=None)

    result = prepare_library_workflow(
        repo_root,
        workflow_identifier=workflow_identifier,
        parameters=parameters,
        runtime_prepared_root=bundle.path("runtime_root") / "prepared_workflows",
        drive_prepared_root=bundle.path("drive_workflows") / "prepared",
        comfyui_input_dir=bundle.path("comfyui_runtime") / "input",
        drive_root=drive_root,
        active_project=context.project,
        allow_experimental=bool(metadata.get("experimental_acknowledged")),
        allow_benchmark=bool(metadata.get("benchmark_acknowledged")),
        dry_run=args.dry_run,
        allowed_input_roots=[bundle.path("drive_inputs"), repo_root / "inputs"],
    )
    payload = {
        "source_preparation_id": preparation_id,
        "new_preparation_id": result.preparation_id,
        "workflow_identifier": result.workflow_identifier,
        "mode": f"Project — {context.project.slug}" if context.project else "Global outputs only",
        "project_path": result.project_prepared_dir,
        "drive_path": result.drive_prepared_dir,
        "ok": result.ok,
        "errors": result.errors,
        "messages": result.messages,
        "dry_run": args.dry_run,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — Reprepare Workflow")
        print("=" * 40)
        print(f"Source preparation: {preparation_id}")
        print(f"New preparation:    {result.preparation_id}")
        print(f"Mode:               {payload['mode']}")
        if result.drive_prepared_dir:
            print(f"Global Drive path:  {result.drive_prepared_dir}")
        if result.project_prepared_dir:
            print(f"Project path:       {result.project_prepared_dir}")
        for message in result.messages:
            print(f"Note: {message}")
        for error in result.errors:
            print(f"Error: {error}", file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
