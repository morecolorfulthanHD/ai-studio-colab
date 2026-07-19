#!/usr/bin/env python3
"""Report AI Studio project statistics."""

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

from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute AI Studio project statistics.")
    parser.add_argument("--project", required=True, help="Project slug or project_id.")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    workspace = ProjectWorkspace(bundle.path("drive_root"))
    evidence = bundle.path("drive_logs") / "generation_evidence.jsonl"
    try:
        stats = workspace.compute_statistics(args.project, evidence_path=evidence)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(stats, indent=2))
        return 0
    print("AI Studio — Project Statistics")
    print("=" * 40)
    print(f"Project: {stats['name']} ({stats['slug']})")
    print(f"ID: {stats['project_id']}")
    print(f"Status: {stats['status']} | archived={stats['archived']}")
    if args.summary:
        print(
            f"Verified generations={stats['verified_generations']} | "
            f"project outputs={stats['project_output_count']} | "
            f"storage={stats['project_storage_bytes']} bytes"
        )
        return 0
    print(f"Created: {stats['created_timestamp']}")
    print(f"Updated: {stats['updated_timestamp']}")
    print(f"Last generation: {stats['last_generation_timestamp'] or '(none)'}")
    print(f"Verified generations: {stats['verified_generations']}")
    print(f"Canonical global assets: {stats['canonical_global_assets']}")
    print(f"Project outputs: {stats['project_output_count']}")
    print(
        f"Counts: inputs={stats['input_count']} masks={stats['mask_count']} "
        f"references={stats['reference_count']} workflows={stats['workflow_count']} "
        f"metadata={stats['metadata_file_count']}"
    )
    print(f"Storage: project={stats['project_storage_bytes']} output={stats['project_output_storage_bytes']}")
    print(f"Capability breakdown: {stats['capability_breakdown']}")
    print(f"Model-family breakdown: {stats['model_family_breakdown']}")
    print(f"Workflow breakdown: {stats['workflow_breakdown']}")
    print(f"Date range: {stats['date_range']}")
    print(f"Missing project output refs: {stats['missing_project_output_references']}")
    print(f"Duplicate content groups: {stats['duplicate_content_count']}")
    print("Note: mirrored project files are not counted as separate generations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
