#!/usr/bin/env python3
"""User-facing workflow catalog with runtime, quality, and production status."""

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

from core.runtime.capability_manager import CapabilityManager
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_provenance import WORKFLOW_ID_TO_IDENTIFIER


def _capability_for_workflow(workflow_id: str, manager: CapabilityManager) -> dict | None:
    for cap in manager.capabilities:
        if workflow_id in cap.get("required_workflows", []):
            return manager.evaluate_capability(cap["id"]).to_dict()
        if workflow_id.replace("reference_", "") in cap.get("id", ""):
            return manager.evaluate_capability(cap["id"]).to_dict()
    if workflow_id.startswith("reference_qwen"):
        return manager.evaluate_capability("qwen_image_edit_benchmark").to_dict()
    if workflow_id.startswith("reference_flux"):
        return manager.evaluate_capability("flux_fill_benchmark").to_dict()
    return None


def build_catalog(repo_root: Path) -> list[dict]:
    bundle = RegistryLoader(repo_root).load_all()
    manager = CapabilityManager(bundle=bundle)
    entries: list[dict] = []
    for workflow in bundle.workflows:
        workflow_id = str(workflow.get("id") or "")
        rel_path = str(workflow.get("path") or "")
        identifier, source = WORKFLOW_ID_TO_IDENTIFIER.get(workflow_id, (workflow_id, "registered"))
        cap_eval = _capability_for_workflow(workflow_id, manager)
        classification = "benchmark" if "benchmark" in identifier else (
            "reference" if identifier.startswith("reference/") else "canonical"
        )
        entries.append(
            {
                "workflow_id": workflow_id,
                "workflow_identifier": identifier,
                "name": workflow.get("name", workflow_id),
                "path": rel_path,
                "classification": classification,
                "registry_status": workflow.get("status", "unknown"),
                "capability": cap_eval.get("id") if cap_eval else "",
                "runtime_status": cap_eval.get("runtime_status") if cap_eval else "unknown",
                "quality_status": cap_eval.get("quality_status") if cap_eval else "untested",
                "production_status": cap_eval.get("production_status") if cap_eval else "experimental",
                "required_models": workflow.get("required_models", []),
                "prepare_command": f"python core/scripts/prepare_workflow.py --workflow {workflow_id.replace('base_', '')}"
                if workflow_id.startswith("base_")
                else "",
                "workflow_source": source,
            }
        )
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Studio workflow catalog.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    entries = build_catalog(repo_root)

    if args.json:
        print(json.dumps(entries, indent=2))
        return 0

    print("AI Studio — Workflow Catalog")
    print("=" * 40)
    for entry in entries:
        if args.summary:
            print(
                f"{entry['workflow_identifier']:30} "
                f"runtime={entry['runtime_status']} quality={entry['quality_status']} "
                f"production={entry['production_status']}"
            )
        else:
            print(f"{entry['name']} ({entry['workflow_identifier']})")
            print(f"  path: {entry['path']}")
            print(
                f"  runtime={entry['runtime_status']} quality={entry['quality_status']} "
                f"production={entry['production_status']} class={entry['classification']}"
            )
            if entry.get("prepare_command"):
                print(f"  prepare: {entry['prepare_command']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
