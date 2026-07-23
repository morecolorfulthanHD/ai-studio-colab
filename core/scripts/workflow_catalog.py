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
from core.runtime.workflow_manifest import list_workflow_manifests
from core.runtime.workflow_readiness import evaluate_workflow_readiness

SECTION_ORDER = {
    "ready": 0,
    "partial": 1,
    "experimental": 2,
    "benchmark_only": 3,
    "blocked": 4,
}

SECTION_TITLES = {
    "ready": "READY",
    "partial": "AVAILABLE WITH CAUTION",
    "experimental": "EXPERIMENTAL",
    "benchmark_only": "BENCHMARK ONLY",
    "blocked": "BLOCKED",
}


def _capability_eval(capability_id: str, manager: CapabilityManager) -> dict | None:
    if not capability_id:
        return None
    try:
        return manager.evaluate_capability(capability_id).to_dict()
    except KeyError:
        return None


def build_catalog(
    repo_root: Path,
    *,
    category: str = "",
    capability: str = "",
    status: str = "",
    include_experimental: bool = True,
    include_benchmark: bool = False,
    ready_only: bool = False,
) -> list[dict]:
    bundle = RegistryLoader(repo_root).load_all()
    manager = CapabilityManager(bundle=bundle)
    entries: list[dict] = []

    for manifest in list_workflow_manifests(repo_root):
        identifier = str(manifest.get("_workflow_identifier") or manifest.get("workflow_identifier") or "")
        if category and str(manifest.get("category") or "") != category:
            continue
        cap_id = str(manifest.get("capability") or "")
        if capability and cap_id != capability:
            continue

        cap_eval = _capability_eval(cap_id, manager)
        readiness = evaluate_workflow_readiness(repo_root, identifier)
        production_status = str(manifest.get("production_status") or readiness.status)
        runtime_status = str(
            cap_eval.get("runtime_status") if cap_eval else manifest.get("runtime_status") or "unknown"
        )
        quality_status = str(
            cap_eval.get("quality_status") if cap_eval else manifest.get("quality_status") or "untested"
        )

        if status and production_status != status and readiness.status != status:
            continue
        if ready_only and production_status not in {"ready"} and readiness.status not in {"ready"}:
            continue
        if production_status == "benchmark_only" and not include_benchmark:
            continue

        entries.append(
            {
                "workflow_identifier": identifier,
                "display_name": manifest.get("display_name", identifier),
                "category": manifest.get("category", ""),
                "capability": cap_id,
                "manifest_path": manifest.get("_manifest_path", ""),
                "canonical_workflow_path": manifest.get("canonical_workflow_path", ""),
                "runtime_status": runtime_status,
                "quality_status": quality_status,
                "production_status": production_status,
                "readiness_status": readiness.status,
                "readiness_reasons": readiness.reasons,
                "launchable": manifest.get("launchable", False),
                "requires_experimental": manifest.get("requires_experimental", False),
                "requires_benchmark": manifest.get("requires_benchmark", False),
                "prepare_command": f"python core/scripts/prepare_workflow.py --workflow {identifier}",
            }
        )

    entries.sort(
        key=lambda item: (
            SECTION_ORDER.get(str(item.get("production_status") or item.get("readiness_status")), 99),
            str(item.get("workflow_identifier") or ""),
        )
    )
    return entries


def _section_for_entry(entry: dict) -> str:
    production = str(entry.get("production_status") or "")
    if production in SECTION_TITLES:
        return production
    readiness = str(entry.get("readiness_status") or "partial")
    if readiness in SECTION_TITLES:
        return readiness
    return "partial"


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Studio workflow catalog.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--category", default="")
    parser.add_argument("--capability", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--include-experimental", action="store_true", default=True)
    parser.add_argument("--no-include-experimental", action="store_false", dest="include_experimental")
    parser.add_argument("--include-benchmark", action="store_true")
    parser.add_argument("--ready-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    entries = build_catalog(
        repo_root,
        category=args.category,
        capability=args.capability,
        status=args.status,
        include_experimental=args.include_experimental,
        include_benchmark=args.include_benchmark,
        ready_only=args.ready_only,
    )

    if args.json:
        print(json.dumps(entries, indent=2))
        return 0

    print("AI Studio — Workflow Catalog")
    print("=" * 40)
    current_section = None
    for entry in entries:
        section = _section_for_entry(entry)
        if section != current_section:
            current_section = section
            print(f"\n{SECTION_TITLES.get(section, section.upper())}")
            print("-" * len(SECTION_TITLES.get(section, section)))
        if args.summary:
            print(
                f"{entry['workflow_identifier']:30} "
                f"runtime={entry['runtime_status']} quality={entry['quality_status']} "
                f"production={entry['production_status']} readiness={entry['readiness_status']}"
            )
        else:
            print(f"{entry['display_name']} ({entry['workflow_identifier']})")
            print(
                f"  runtime={entry['runtime_status']} quality={entry['quality_status']} "
                f"production={entry['production_status']} readiness={entry['readiness_status']}"
            )
            print(f"  prepare: {entry['prepare_command']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
