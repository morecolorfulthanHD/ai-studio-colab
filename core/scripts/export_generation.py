#!/usr/bin/env python3
"""Export a generation snapshot to a self-contained ZIP archive."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.generation_evidence_ledger import file_sha256
from core.runtime.generation_identity import InvalidGenerationIdError, normalize_generation_id
from core.runtime.generation_snapshot import (
    EXPORT_SCHEMA_VERSION,
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    PACKAGE_VERSION,
    WORKFLOW_FILENAME,
    load_snapshot_by_id,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _collision_safe_path(base: Path) -> Path:
    if not base.exists():
        return base
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base.with_name(f"{base.stem}_{stamp}{base.suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export an AI Studio generation snapshot to ZIP.")
    parser.add_argument(
        "--generation-id",
        required=True,
        help="Generation ID as gen_<UUID> or bare UUID.",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
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
    image_path = Path(str(manifest.get("canonical_output_path") or ""))
    if not image_path.is_file():
        print(f"ERROR: Canonical output missing: {image_path}", file=sys.stderr)
        return 1

    out_dir = args.output_dir.resolve() if args.output_dir else drive_root / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = _collision_safe_path(out_dir / f"{generation_id}.zip")

    file_hashes: dict[str, str] = {}
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(image_path, f"image/{image_path.name}")
        file_hashes[f"image/{image_path.name}"] = file_sha256(image_path)
        archive.write(metadata_path, METADATA_FILENAME)
        file_hashes[METADATA_FILENAME] = file_sha256(metadata_path)
        archive.write(workflow_path, WORKFLOW_FILENAME)
        file_hashes[WORKFLOW_FILENAME] = file_sha256(workflow_path)
        archive.write(manifest_path, MANIFEST_FILENAME)
        file_hashes[MANIFEST_FILENAME] = file_sha256(manifest_path)
        export_manifest = {
            "export_schema_version": EXPORT_SCHEMA_VERSION,
            "generation_id": generation_id,
            "exported_timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "source_paths": {
                "snapshot_root": str(snapshot_root),
                "canonical_output_path": str(image_path),
            },
            "file_hashes": file_hashes,
            "package_version": PACKAGE_VERSION,
        }
        archive.writestr("export_manifest.json", json.dumps(export_manifest, indent=2) + "\n")

    with zipfile.ZipFile(zip_path, "r") as verify:
        names = set(verify.namelist())
        required = {METADATA_FILENAME, WORKFLOW_FILENAME, MANIFEST_FILENAME, "export_manifest.json"}
        if not required.issubset(names):
            print("ERROR: Export ZIP missing required entries.", file=sys.stderr)
            return 1

    payload = {"generation_id": generation_id, "export_path": str(zip_path), "files": len(file_hashes) + 1}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Exported generation: {generation_id}")
        print(f"Archive: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
