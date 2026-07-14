#!/usr/bin/env python3
"""Compare canonical and reference inpainting workflows."""

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

from core.runtime.inpainting_workflow_compare import (
    CANONICAL_INPAINTING_PATH,
    REFERENCE_INPAINTING_PATH,
    compare_inpainting_workflows,
    format_comparison_summary,
)
from core.runtime.registry_loader import find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare canonical AI Studio and reference ComfyUI inpainting workflows."
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--canonical", type=Path, default=None)
    parser.add_argument("--reference", type=Path, default=None)
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary.")
    parser.add_argument("--json", action="store_true", help="Print structured JSON.")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    canonical_path = args.canonical or (repo_root / CANONICAL_INPAINTING_PATH)
    reference_path = args.reference or (repo_root / REFERENCE_INPAINTING_PATH)

    if not canonical_path.is_file():
        print(f"ERROR: Canonical workflow missing: {canonical_path}", file=sys.stderr)
        return 1
    if not reference_path.is_file():
        print(f"ERROR: Reference workflow missing: {reference_path}", file=sys.stderr)
        return 1

    comparison = compare_inpainting_workflows(canonical_path, reference_path)
    if args.json:
        print(json.dumps(comparison.to_dict(), indent=2))
    else:
        print(format_comparison_summary(comparison))

    print("\nRESULT: OK — inpainting workflow comparison complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
