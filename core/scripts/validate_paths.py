#!/usr/bin/env python3
"""Validate important AI Studio Colab paths from configs/paths/colab_paths.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in (current, *current.parents):
        if (path / "README.md").is_file() and (path / "configs").is_dir():
            return path
    raise FileNotFoundError("Could not locate repository root.")


def load_colab_paths(repo_root: Path) -> dict:
    manifest = repo_root / "configs" / "paths" / "colab_paths.json"
    if not manifest.is_file():
        raise FileNotFoundError(f"Missing path manifest: {manifest}")

    with manifest.open(encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict) or "paths" not in data:
        raise ValueError("colab_paths.json must contain a top-level 'paths' object.")

    return data["paths"]


def check_path(label: str, path: Path, required: bool) -> bool:
    if path.exists():
        kind = "dir" if path.is_dir() else "file"
        print(f"  [ok]   {label}: {path} ({kind})")
        return True

    level = "MISS" if required else "warn"
    suffix = " (required)" if required else " (optional)"
    print(f"  [{level}] {label}: {path}{suffix}")
    return not required


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate AI Studio Colab paths.")
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args()

    print("AI Studio Colab — Path Validation")
    print("=" * 40)

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
        paths_cfg = load_colab_paths(repo_root)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Repository root: {repo_root}\n")

    all_ok = True

    print("Colab / Drive runtime paths (from colab_paths.json):")
    for key, value in paths_cfg.items():
        if not check_path(key, Path(value), required=False):
            all_ok = False

    print("\nRepository paths (required):")
    repo_checks = {
        "repo_root": repo_root,
        "workflows": repo_root / "workflows",
        "configs": repo_root / "configs",
    }
    for label, path in repo_checks.items():
        if not check_path(label, path, required=True):
            all_ok = False

    if all_ok:
        print("\nRESULT: OK — all required paths present.")
        return 0

    print("\nRESULT: ISSUES FOUND — see messages above.", file=sys.stderr)
    print("  [info] Missing Colab runtime paths are normal before first notebook run.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
