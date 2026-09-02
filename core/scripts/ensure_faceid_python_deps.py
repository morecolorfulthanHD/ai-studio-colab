#!/usr/bin/env python3
"""Ensure pinned IPAdapter FaceID Python runtime dependencies (insightface + onnxruntime).

Uses the same Python interpreter as ComfyUI launch (PYTHON env or sys.executable).
Does not download or mutate restricted FaceID model weights.
"""

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

from core.runtime.faceid_python_deps import (
    INSIGHTFACE_PACKAGE_VERSION,
    ONNXRUNTIME_MIN_VERSION,
    assess_faceid_python_runtime,
    default_comfy_python_executable,
    ensure_faceid_python_runtime,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Install/verify audited Python packages required by pinned IPAdapter FaceID "
            f"(insightface=={INSIGHTFACE_PACKAGE_VERSION}, onnxruntime>={ONNXRUNTIME_MIN_VERSION})."
        )
    )
    parser.add_argument(
        "--python",
        dest="python_executable",
        default=None,
        help="ComfyUI Python interpreter (default: PYTHON env or sys.executable).",
    )
    parser.add_argument("--execute", action="store_true", help="Apply pip install when missing.")
    parser.add_argument("--dry-run", action="store_true", help="Plan only (default).")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--assess-only", action="store_true", help="Probe only; never pip install.")
    args = parser.parse_args()

    exe = args.python_executable or default_comfy_python_executable()
    if args.assess_only:
        assessment = assess_faceid_python_runtime(python_executable=exe)
        if args.json:
            print(json.dumps(assessment, indent=2))
        else:
            print(f"Python: {exe}")
            print(f"InsightFace Python module: {assessment.get('status')}")
            print(f"notes: {assessment.get('notes')}")
        return 0 if assessment.get("verified") else 2

    dry_run = not args.execute or args.dry_run
    result = ensure_faceid_python_runtime(python_executable=exe, dry_run=dry_run)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"Python: {exe}")
        for msg in result.messages:
            print(msg)
        for err in result.errors:
            print(err, file=sys.stderr)
        if result.pip_command and dry_run:
            print("Would run:", " ".join(result.pip_command))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
