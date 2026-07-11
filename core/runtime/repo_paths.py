#!/usr/bin/env python3
"""Shared repository root resolution for CLI scripts and runtime loaders."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_MARKERS = ("README.md", "configs", "core", "workflows")

REPO_ROOT_ERROR = (
    "Could not locate AI Studio Colab repository root. "
    "Run from inside the cloned repository or invoke scripts by absolute path."
)


def is_repo_root(path: Path) -> bool:
    return all((path / marker).exists() for marker in REPO_MARKERS)


def locate_repo_root(
    *,
    script_file: Path | None = None,
    cwd_start: Path | None = None,
) -> Path:
    """Resolve repository root from script location, sys.path, then cwd."""
    candidates: list[Path] = []

    if script_file is not None:
        script = script_file.resolve()
        candidates.extend([script.parent, *script.parents])

    if sys.argv:
        try:
            argv_path = Path(sys.argv[0]).resolve()
        except OSError:
            argv_path = None
        if argv_path is not None and argv_path.suffix == ".py":
            candidates.extend([argv_path.parent, *argv_path.parents])

    module_root = Path(__file__).resolve().parents[2]
    candidates.append(module_root)

    for entry in sys.path:
        if not entry:
            continue
        try:
            candidates.append(Path(entry).resolve())
        except OSError:
            continue

    if cwd_start is not None:
        start = cwd_start.resolve()
        candidates.extend([start, *start.parents])
    else:
        cwd = Path.cwd().resolve()
        candidates.extend([cwd, *cwd.parents])

    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if is_repo_root(path):
            return path

    raise FileNotFoundError(REPO_ROOT_ERROR)


def bootstrap_sys_path(script_file: Path) -> Path:
    """Ensure repository root is on sys.path and return it."""
    repo_root = locate_repo_root(script_file=script_file)
    repo_str = str(repo_root)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
    return repo_root
