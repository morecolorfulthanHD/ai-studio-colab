#!/usr/bin/env python3
"""Validate important AI Studio Colab paths from configs/paths/colab_paths.json."""

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

from core.runtime.registry_loader import find_repo_root


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
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
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
