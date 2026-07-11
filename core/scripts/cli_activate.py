#!/usr/bin/env python3
"""Shared activation helper for core/scripts CLI entry points."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def activate(caller_file: str | Path) -> Path:
    """Bootstrap repository imports for a CLI script and return repo root."""
    caller = Path(caller_file).resolve()
    bootstrap_path = caller.parent / "repo_bootstrap.py"
    spec = importlib.util.spec_from_file_location("ai_studio_repo_bootstrap", bootstrap_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load CLI bootstrap helper: {bootstrap_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.bootstrap(caller)
