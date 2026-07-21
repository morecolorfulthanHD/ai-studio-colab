#!/usr/bin/env python3
"""List/search generation evidence records with Package 4.7 filters."""

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

from core.runtime.generation_history import (
    collapse_generations,
    generation_display_id,
    prompt_excerpt,
    provenance_label,
    snapshot_status_label,
)
from core.runtime.generation_identity import InvalidGenerationIdError
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _project_slug_from_row(row: dict) -> str:
    path = str(row.get("project_output_path") or "").replace("\\", "/")
    if "/projects/" in path:
        return path.split("/projects/", 1)[1].split("/", 1)[0]
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="List/search AI Studio generation evidence.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--verified-only", action="store_true", default=True)
    parser.add_argument("--raw", action="store_true", help="Return raw ledger rows without collapse.")
    parser.add_argument(
        "--generation-id",
        default="",
        help="Generation ID as gen_<UUID> or bare UUID.",
    )
    parser.add_argument("--project", default="", help="Project slug or project_id.")
    parser.add_argument("--capability", default="")
    parser.add_argument("--workflow", default="")
    parser.add_argument("--model-family", default="")
    parser.add_argument("--model-file", default="")
    parser.add_argument("--seed", default="")
    parser.add_argument("--date-from", default="")
    parser.add_argument("--date-to", default="")
    parser.add_argument("--prompt-contains", default="")
    parser.add_argument("--sync-status", default="verified")
    parser.add_argument("--provenance-status", default="")
    parser.add_argument("--snapshot-status", default="")
    parser.add_argument("--image-sha256", default="")
    parser.add_argument("--drive-filename", default="")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    ledger_path = bundle.path("drive_logs") / "generation_evidence.jsonl"
    project_slug = args.project
    project_id = ""
    if args.project:
        workspace = ProjectWorkspace(bundle.path("drive_root"))
        try:
            resolved = workspace.resolve_project(args.project)
            project_slug = resolved.slug
            project_id = resolved.project_id
        except (FileNotFoundError, ValueError):
            project_slug = args.project
            project_id = args.project
    try:
        rows = collapse_generations(
            ledger_path,
            generation_id=args.generation_id,
            project=project_slug,
            project_id=project_id,
            capability=args.capability,
            workflow=args.workflow,
            model_family=args.model_family,
            model_file=args.model_file,
            seed=args.seed,
            date_from=args.date_from,
            date_to=args.date_to,
            prompt_contains=args.prompt_contains,
            sync_status="" if args.raw and not args.sync_status else args.sync_status,
            provenance_status=args.provenance_status,
            snapshot_status=args.snapshot_status,
            image_sha256=args.image_sha256,
            drive_filename=args.drive_filename,
            verified_only=False if args.raw else bool(args.verified_only or args.sync_status == "verified"),
            raw=args.raw,
            limit=args.limit,
        )
    except InvalidGenerationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if args.summary:
        print(f"Matched generations: {len(rows)}")
        return 0

    print("AI Studio — Generations")
    print("=" * 40)
    print("You may enter either the full gen_<uuid> ID or the UUID portion alone.")
    if not rows:
        print("No matching generation records found.")
        return 0
    for row in rows:
        gid = generation_display_id(row)
        stamp = row.get("synchronized_timestamp") or row.get("created_timestamp") or ""
        project = _project_slug_from_row(row) or "-"
        model = row.get("model_family") or "unknown"
        seed = row.get("seed", "-")
        snapshot = snapshot_status_label(row)
        filename = row.get("drive_filename") or Path(str(row.get("drive_path") or "")).name
        print(gid)
        print(
            f"{stamp} | {project} | {row.get('capability') or 'unknown'} | "
            f"{row.get('workflow_identifier') or 'unknown'} | {model} | {seed} | {snapshot} | {filename}"
        )
        print(f"  prompt_id={row.get('prompt_id')} provenance={provenance_label(row)}")
        if row.get("drive_path"):
            print(f"  drive={row.get('drive_path')}")
        if row.get("project_output_path"):
            print(f"  project={row.get('project_output_path')}")
        if row.get("snapshot_root"):
            print(f"  snapshot={row.get('snapshot_root')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
