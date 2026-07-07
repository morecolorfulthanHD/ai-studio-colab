#!/usr/bin/env python3
"""Copy the latest ComfyUI output file to persistent Google Drive storage.

Safe to run after generation. Copies only the single newest file in the
ComfyUI output directory — not a bulk sync of the entire folder.

Use --dry-run to preview source/destination without writing files.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in (current, *current.parents):
        if (path / "README.md").is_file() and (path / "configs").is_dir():
            return path
    raise FileNotFoundError("Could not locate repository root.")


def load_paths(repo_root: Path) -> tuple[Path, Path]:
    manifest = repo_root / "configs" / "paths" / "colab_paths.json"
    with manifest.open(encoding="utf-8") as fh:
        data = json.load(fh)
    paths = data["paths"]
    return Path(paths["comfyui_output"]), Path(paths["drive_outputs"])


def latest_file(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None

    candidates = [p for p in directory.rglob("*") if p.is_file()]
    if not candidates:
        return None

    return max(candidates, key=lambda p: p.stat().st_mtime)


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
    args = parser.parse_args()

    print("AI Studio Colab — Sync Latest Output")
    print("=" * 40)

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
        source_dir, dest_dir = load_paths(repo_root)
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Source directory: {source_dir}")
    print(f"Destination:      {dest_dir}")
    print(f"Dry run:          {args.dry_run}")

    if not source_dir.is_dir():
        print(f"ERROR: Source directory does not exist: {source_dir}", file=sys.stderr)
        return 1

    latest = latest_file(source_dir)
    if latest is None:
        print("ERROR: No files found in ComfyUI output directory.", file=sys.stderr)
        return 1

    dest_path = dest_dir / latest.name
    print(f"\nLatest file: {latest}")
    print(f"Would copy to: {dest_path}")

    if args.dry_run:
        print("\nRESULT: DRY RUN — no files copied.")
        return 0

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(latest, dest_path)
    except OSError as exc:
        print(f"ERROR: Copy failed: {exc}", file=sys.stderr)
        return 1

    print(f"\nRESULT: OK — copied {latest.name} to {dest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
