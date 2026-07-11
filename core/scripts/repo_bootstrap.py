#!/usr/bin/env python3
"""Stdlib-only bootstrap helper for core/scripts CLI entry points."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_MARKERS = ("README.md", "configs", "core", "workflows")


def _load_repo_paths_module(script_file: Path):
    repo_paths_file = script_file.resolve().parent.parent / "runtime" / "repo_paths.py"
    spec = importlib.util.spec_from_file_location("ai_studio_repo_paths", repo_paths_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load repository path resolver: {repo_paths_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bootstrap(script_file: str | Path) -> Path:
    """Add repository root to sys.path and return the resolved root."""
    script = Path(script_file).resolve()
    try:
        repo_paths = _load_repo_paths_module(script)
        return repo_paths.bootstrap_sys_path(script)
    except (ImportError, FileNotFoundError, OSError):
        for path in (script.parent, *script.parents):
            if all((path / marker).exists() for marker in REPO_MARKERS):
                root_str = str(path)
                if root_str not in sys.path:
                    sys.path.insert(0, root_str)
                return path
        raise FileNotFoundError(
            "Could not locate AI Studio Colab repository root. "
            "Run from inside the cloned repository or invoke scripts by absolute path."
        ) from None
