#!/usr/bin/env python3
"""Show read-only details for one generation snapshot."""

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

from core.runtime.generation_history import generation_display_id, provenance_label, snapshot_status_label
from core.runtime.generation_identity import InvalidGenerationIdError, normalize_generation_id
from core.runtime.generation_snapshot import MANIFEST_FILENAME, METADATA_FILENAME, WORKFLOW_FILENAME, load_snapshot_by_id
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _find_evidence_row(ledger_path: Path, generation_id: str) -> dict | None:
    if not ledger_path.is_file():
        return None
    latest = None
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("generation_id") or "") == generation_id:
            latest = row
    return latest


def main() -> int:
    parser = argparse.ArgumentParser(description="Show AI Studio generation snapshot details.")
    parser.add_argument(
        "--generation-id",
        required=True,
        help="Generation ID as gen_<UUID> or bare UUID.",
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--show-workflow-path", action="store_true")
    parser.add_argument("--show-image-path", action="store_true")
    args = parser.parse_args()

    try:
        generation_id = normalize_generation_id(args.generation_id)
    except InvalidGenerationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    drive_root = bundle.path("drive_root")
    try:
        manifest = load_snapshot_by_id(drive_root, generation_id)
    except InvalidGenerationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if manifest is None:
        print(f"ERROR: Generation not found:\n{generation_id}", file=sys.stderr)
        return 1

    snapshot_root = Path(str(manifest.get("snapshot_root") or ""))
    metadata_path = snapshot_root / METADATA_FILENAME
    workflow_path = snapshot_root / WORKFLOW_FILENAME
    manifest_path = snapshot_root / MANIFEST_FILENAME
    metadata = {}
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    ledger_path = bundle.path("drive_logs") / "generation_evidence.jsonl"
    evidence = _find_evidence_row(ledger_path, generation_id) or {}

    payload = {
        "generation_id": generation_id,
        "project_id": metadata.get("project_id") or evidence.get("project_id"),
        "project_slug": metadata.get("project_slug"),
        "capability": metadata.get("capability") or evidence.get("capability"),
        "model_family": metadata.get("model_family") or evidence.get("model_family"),
        "positive_prompt": metadata.get("positive_prompt") or evidence.get("positive_prompt"),
        "negative_prompt": metadata.get("negative_prompt") or evidence.get("negative_prompt"),
        "seed": metadata.get("seed") if metadata.get("seed") is not None else evidence.get("seed"),
        "workflow_identifier": metadata.get("workflow_identifier") or evidence.get("workflow_identifier"),
        "workflow_hash": metadata.get("workflow_hash") or evidence.get("workflow_hash"),
        "canonical_output_path": metadata.get("canonical_output_path") or manifest.get("canonical_output_path"),
        "project_output_path": metadata.get("project_output_path") or manifest.get("project_output_path"),
        "image_sha256": metadata.get("image_sha256") or manifest.get("image_sha256"),
        "snapshot_status": snapshot_status_label(evidence) if evidence else "complete",
        "provenance_status": provenance_label(evidence) if evidence else metadata.get("provenance_status"),
        "workflow_snapshot_status": metadata.get("workflow_snapshot_status"),
        "metadata_path": str(metadata_path),
        "workflow_path": str(workflow_path),
        "manifest_path": str(manifest_path),
    }

    if args.show_workflow_path:
        print(payload["workflow_path"])
        return 0
    if args.show_image_path:
        print(payload["canonical_output_path"] or "")
        return 0
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    if args.summary:
        print(
            f"{generation_display_id(evidence or {'generation_id': generation_id})} | "
            f"{payload.get('capability')} | {payload.get('workflow_identifier')} | "
            f"snapshot={payload.get('snapshot_status')}"
        )
        return 0

    print("AI Studio — Generation Info")
    print("=" * 40)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
