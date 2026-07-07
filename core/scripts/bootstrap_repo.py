#!/usr/bin/env python3
"""Bootstrap and validate AI Studio Colab repository structure.

Safe to run from Colab or local shell. Does not perform destructive operations.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REQUIRED_TOP_LEVEL_DIRS = (
    "docs",
    "colab",
    "core",
    "configs",
    "assets",
    "workflows",
    "use_cases",
    "output",
    "tests",
)

REQUIRED_CONFIG_FILES = (
    "configs/paths/colab_paths.json",
    "configs/models/model_registry.json",
    "configs/nodes/node_registry.json",
    "configs/presets/default_generation_presets.json",
    "configs/workflows/workflow_registry.json",
    "configs/assets/asset_registry.json",
)

CANONICAL_NOTEBOOK = "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb"


def find_repo_root(start: Path | None = None) -> Path:
    """Walk upward from *start* (or cwd) to locate the repository root."""
    current = (start or Path.cwd()).resolve()
    markers = {".git", "workflows", "configs"}

    for path in (current, *current.parents):
        if (path / "README.md").is_file() and any((path / m).exists() for m in markers):
            return path

    raise FileNotFoundError(
        "Could not locate AI Studio Colab repository root. "
        "Run this script from inside the cloned repository."
    )


def validate_structure(repo_root: Path) -> tuple[list[str], list[str]]:
    """Return (present_dirs, missing_dirs) for required top-level folders."""
    missing: list[str] = []
    present: list[str] = []

    for name in REQUIRED_TOP_LEVEL_DIRS:
        path = repo_root / name
        if path.is_dir():
            present.append(name)
        else:
            missing.append(name)

    return present, missing


def validate_config_files(repo_root: Path) -> tuple[list[str], list[str]]:
    """Return (present_files, missing_files) for required manifest files."""
    missing: list[str] = []
    present: list[str] = []

    for rel in REQUIRED_CONFIG_FILES:
        path = repo_root / rel
        if path.is_file():
            present.append(rel)
        else:
            missing.append(rel)

    return present, missing


def print_git_pull_hook(repo_root: Path, dry_run: bool) -> None:
    """Document future git sync hook without executing destructive commands."""
    git_dir = repo_root / ".git"
    print("\n--- Git sync hook (future) ---")
    if not git_dir.is_dir():
        print("  [info] No .git directory detected — git pull hook skipped.")
        print("  [info] In Colab, clone or copy the repo before bootstrapping.")
        return

    print(f"  [info] Repository root: {repo_root}")
    print("  [info] Future notebook integration may run:")
    print(f"         git -C {repo_root} fetch --dry-run")
    print(f"         git -C {repo_root} pull --ff-only")
    if dry_run:
        print("  [dry-run] No git commands were executed.")
    else:
        print("  [skip] Auto git pull is intentionally disabled in bootstrap_repo.py.")
        print("         Use explicit notebook cells or CI to sync when ready.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate AI Studio Colab repository bootstrap status."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Override repository root (default: auto-detect from cwd).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned actions without side effects (default behavior).",
    )
    args = parser.parse_args()

    print("AI Studio Colab — Repository Bootstrap")
    print("=" * 40)

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Repository root: {repo_root}")
    print(f"Working directory: {Path.cwd()}")

    present_dirs, missing_dirs = validate_structure(repo_root)
    print(f"\nTop-level directories: {len(present_dirs)}/{len(REQUIRED_TOP_LEVEL_DIRS)} present")
    for name in present_dirs:
        print(f"  [ok]   {name}/")
    for name in missing_dirs:
        print(f"  [MISS] {name}/")

    present_files, missing_files = validate_config_files(repo_root)
    print(f"\nConfig manifests: {len(present_files)}/{len(REQUIRED_CONFIG_FILES)} present")
    for rel in present_files:
        print(f"  [ok]   {rel}")
    for rel in missing_files:
        print(f"  [MISS] {rel}")

    notebook = repo_root / CANONICAL_NOTEBOOK
    if notebook.is_file():
        print(f"\n[ok] Canonical control panel: {CANONICAL_NOTEBOOK}")
    else:
        print(f"\n[WARN] Canonical notebook not found: {CANONICAL_NOTEBOOK}")

    print_git_pull_hook(repo_root, dry_run=True)

    if missing_dirs or missing_files:
        print("\nRESULT: INCOMPLETE — missing required structure.", file=sys.stderr)
        return 1

    print("\nRESULT: OK — repository structure is ready for bootstrap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
