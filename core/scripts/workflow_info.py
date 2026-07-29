#!/usr/bin/env python3
"""Show workflow library manifest details."""

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

from core.runtime.registry_loader import find_repo_root
from core.runtime.workflow_manifest import (
    load_workflow_manifest,
    validate_manifest_against_canonical,
    validate_manifest_structure,
)
from core.runtime.workflow_readiness import evaluate_workflow_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description="Show workflow library manifest details.")
    parser.add_argument("--workflow", required=True, help="Workflow identifier or alias.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--show-parameters", action="store_true", help="Also dump raw parameter schema.")
    parser.add_argument("--check-readiness", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    try:
        manifest = load_workflow_manifest(repo_root, args.workflow)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    structure_errors = validate_manifest_structure(manifest)
    hash_errors = validate_manifest_against_canonical(repo_root, manifest)
    readiness = evaluate_workflow_readiness(
        repo_root, manifest.get("_workflow_identifier", args.workflow)
    )
    parameter_schema = manifest.get("parameter_schema") or {}
    default_parameters = manifest.get("default_parameters") or {}
    required_models = list(manifest.get("required_model_files") or [])
    optional_nodes = list(manifest.get("optional_nodes") or [])
    license_notes = list(manifest.get("license_notes") or [])
    status_reason = str(manifest.get("status_reason") or "").strip()

    payload = {
        "workflow_identifier": manifest.get("_workflow_identifier"),
        "display_name": manifest.get("display_name"),
        "description": manifest.get("description"),
        "capability": manifest.get("capability"),
        "implementation_status": manifest.get("implementation_status"),
        "runtime_status": manifest.get("runtime_status"),
        "quality_status": manifest.get("quality_status"),
        "production_status": manifest.get("production_status"),
        "status_reason": status_reason or None,
        "readiness_status": readiness.status,
        "required_model_files": required_models,
        "required_nodes": list(manifest.get("required_nodes") or []),
        "optional_nodes": optional_nodes,
        "canonical_workflow_path": manifest.get("canonical_workflow_path"),
        "workflow_hash": manifest.get("workflow_hash"),
        "workflow_hash_type": manifest.get("workflow_hash_type"),
        "parameter_schema": parameter_schema,
        "default_parameters": default_parameters,
        "license_notes": license_notes,
        "manifest_path": manifest.get("_manifest_path"),
        "structure_errors": structure_errors,
        "hash_errors": hash_errors,
        "readiness": readiness.to_dict(),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 1 if structure_errors or hash_errors else 0

    print("AI Studio — Workflow Info")
    print("=" * 40)
    print(f"Workflow identifier:   {payload['workflow_identifier']}")
    print(f"Display name:          {payload['display_name']}")
    print(f"Description:           {payload.get('description') or ''}")
    print(f"Capability:            {payload.get('capability') or ''}")
    print(f"Implementation status: {payload.get('implementation_status') or ''}")
    print(f"Runtime status:        {payload.get('runtime_status') or ''}")
    print(f"Quality status:        {payload.get('quality_status') or ''}")
    print(f"Production status:     {payload.get('production_status') or ''}")
    print(f"Readiness status:      {readiness.status}")
    if status_reason:
        print(f"Status reason:         {status_reason}")
    print(f"Required checkpoint:   {', '.join(required_models) if required_models else '(none)'}")
    print(
        f"Required model files:  {', '.join(required_models) if required_models else '(none)'}"
    )
    required_nodes = payload.get("required_nodes") or []
    print(f"Required nodes:        {', '.join(required_nodes) if required_nodes else '(none)'}")
    if optional_nodes:
        print(f"Optional nodes:        {', '.join(optional_nodes)}")
    print(f"Canonical path:        {payload.get('canonical_workflow_path') or ''}")
    print(f"Canonical hash:        {payload.get('workflow_hash') or ''}")
    print(f"Hash type:             {payload.get('workflow_hash_type') or ''}")

    print("\nSupported parameters:")
    if not parameter_schema:
        print("  (none)")
    else:
        for name, spec in parameter_schema.items():
            required = "required" if spec.get("required") else "optional"
            ptype = spec.get("type") or "unknown"
            default = default_parameters.get(name, spec.get("default"))
            allowed = spec.get("allowed_values")
            line = f"  - {name} ({ptype}, {required})"
            if default not in (None, ""):
                line += f" default={default!r}"
            print(line)
            if allowed:
                print(f"      allowed: {', '.join(str(v) for v in allowed)}")

    print("\nDefault parameter values:")
    if not default_parameters:
        print("  (none)")
    else:
        for key, value in default_parameters.items():
            print(f"  {key}: {value!r}")

    if license_notes:
        print("\nLicense notes:")
        for note in license_notes:
            print(f"  - {note}")

    if args.check_readiness or args.summary:
        if readiness.reasons:
            print("\nReadiness notes:")
            for reason in readiness.reasons:
                print(f"  - {reason}")
    if structure_errors:
        print("Structure errors:", file=sys.stderr)
        for err in structure_errors:
            print(f"  - {err}", file=sys.stderr)
    if hash_errors:
        print("Hash errors:", file=sys.stderr)
        for err in hash_errors:
            print(f"  - {err}", file=sys.stderr)
    if args.show_parameters:
        print("\nRaw parameter schema:")
        print(json.dumps(parameter_schema, indent=2))
    return 1 if structure_errors or hash_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
