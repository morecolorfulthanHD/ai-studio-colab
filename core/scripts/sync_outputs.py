#!/usr/bin/env python3
"""Copy the latest ComfyUI output file to persistent Google Drive storage.

Safe to run after generation. Copies only the single newest file in the
ComfyUI output directory — not a bulk sync of the entire folder.

Use --dry-run to preview source/destination without writing files.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.output_evidence import ELIGIBLE_OUTPUT_SUFFIXES, latest_eligible_output
from core.runtime.output_sync import resolve_sync_destination
from core.runtime.registry_loader import find_repo_root


def load_paths(repo_root: Path) -> tuple[Path, Path]:
    manifest = repo_root / "configs" / "paths" / "colab_paths.json"
    with manifest.open(encoding="utf-8") as fh:
        data = json.load(fh)
    paths = data["paths"]
    return Path(paths["comfyui_output"]), Path(paths["drive_outputs"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Copy the single newest ComfyUI output file to Drive. "
            "Not a bulk sync. Safe after generation; use --dry-run to preview."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without writing files.",
    )
    parser.add_argument(
        "--fail-on-existing",
        action="store_true",
        help="Refuse to copy when the destination filename already exists.",
    )
    args = parser.parse_args()

    print("AI Studio Colab — Sync Latest Output")
    print("=" * 40)

    try:
        repo_root = (
            args.repo_root.resolve()
            if args.repo_root
            else find_repo_root(script_file=Path(__file__))
        )
        source_dir, dest_dir = load_paths(repo_root)
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Repository root:  {repo_root}")
    print(f"Source directory: {source_dir}")
    print(f"Destination:      {dest_dir}")
    print(f"Dry run:          {args.dry_run}")
    print(f"Fail on existing: {args.fail_on_existing}")

    if not source_dir.is_dir():
        print(f"ERROR: Source directory does not exist: {source_dir}", file=sys.stderr)
        return 1

    latest = latest_eligible_output(source_dir)
    if latest is None:
        print(
            "ERROR: No eligible generated output found in ComfyUI output directory.",
            file=sys.stderr,
        )
        print(
            "Expected a non-empty image or video file "
            f"({', '.join(sorted(ELIGIBLE_OUTPUT_SUFFIXES))}).",
            file=sys.stderr,
        )
        return 1

    dest_path, collision_detected, original_dest = resolve_sync_destination(
        dest_dir,
        latest.name,
        fail_on_existing=args.fail_on_existing,
    )

    print(f"\nLatest file: {latest}")

    if args.fail_on_existing and collision_detected and original_dest is not None:
        print(
            f"ERROR: Destination file already exists: {original_dest}",
            file=sys.stderr,
        )
        return 1

    if collision_detected and original_dest is not None:
        print("Destination collision detected.")
        print(f"Original destination: {original_dest}")
        print(f"Collision-safe destination: {dest_path}")
    else:
        print(f"Destination: {dest_path}")

    if args.dry_run:
        print("\nRESULT: DRY RUN — no files copied.")
        return 0

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(latest, dest_path)
    except OSError as exc:
        print(f"ERROR: Copy failed: {exc}", file=sys.stderr)
        return 1

    if collision_detected:
        print(
            f"\nRESULT: OK — copied {latest.name} to collision-safe destination {dest_path}"
        )
    else:
        print(f"\nRESULT: OK — copied {latest.name} to {dest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
