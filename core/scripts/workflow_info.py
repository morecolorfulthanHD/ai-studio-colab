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
from core.runtime.workflow_manifest import load_workflow_manifest, validate_manifest_against_canonical, validate_manifest_structure
from core.runtime.workflow_readiness import evaluate_workflow_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description="Show workflow library manifest details.")
    parser.add_argument("--workflow", required=True, help="Workflow identifier or alias.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--show-parameters", action="store_true")
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
    readiness = evaluate_workflow_readiness(repo_root, manifest.get("_workflow_identifier", args.workflow))

    payload = {
        "workflow_identifier": manifest.get("_workflow_identifier"),
        "display_name": manifest.get("display_name"),
        "capability": manifest.get("capability"),
        "production_status": manifest.get("production_status"),
        "manifest_path": manifest.get("_manifest_path"),
        "structure_errors": structure_errors,
        "hash_errors": hash_errors,
        "readiness": readiness.to_dict(),
    }
    if args.show_parameters:
        payload["parameter_schema"] = manifest.get("parameter_schema")
        payload["default_parameters"] = manifest.get("default_parameters")

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("AI Studio — Workflow Info")
    print("=" * 40)
    print(f"Workflow: {payload['workflow_identifier']}")
    print(f"Name:     {payload['display_name']}")
    print(f"Status:   production={payload['production_status']} readiness={readiness.status}")
    if args.check_readiness or args.summary:
        if readiness.reasons:
            print("Readiness notes:")
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
        print("\nParameters:")
        for name, spec in (manifest.get("parameter_schema") or {}).items():
            print(f"  {name}: type={spec.get('type')} required={spec.get('required')}")
    return 1 if structure_errors or hash_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
