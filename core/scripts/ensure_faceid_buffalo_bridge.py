#!/usr/bin/env python3
"""Ensure FaceID buffalo_l InsightFace pack bridges from Drive canonical storage."""

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

from core.runtime.faceid_buffalo_bridge import (
    assess_faceid_buffalo_runtime,
    default_canonical_insightface_dir,
    ensure_faceid_buffalo_bridge,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bridge required buffalo_l InsightFace artifacts (det_10g + w600k_r50) "
            "into ComfyUI/models/insightface/models/buffalo_l/. Manual Drive placement only."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--comfyui-runtime", type=Path, default=None)
    parser.add_argument("--canonical-insightface-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--assess-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    comfyui_runtime = Path(args.comfyui_runtime or bundle.path("comfyui_runtime"))
    canonical_dir = Path(
        args.canonical_insightface_dir or default_canonical_insightface_dir(bundle.path("drive_models"))
    )

    if args.assess_only:
        report = assess_faceid_buffalo_runtime(
            bundle_models=list(bundle.models),
            canonical_insightface_dir=canonical_dir,
            comfyui_runtime=comfyui_runtime if comfyui_runtime.is_dir() else None,
        )
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"InsightFace buffalo_l runtime: {report.get('status')}")
            print(f"  detection: {report.get('detection_status')} (verified={report.get('detection_verified')})")
            print(f"  recognition: {report.get('recognition_status')} (verified={report.get('recognition_verified')})")
            print(f"  initialization: {report.get('initialization_status')}")
            print(f"notes: {report.get('notes')}")
        return 0 if report.get("verified") else 2

    dry_run = not args.execute or args.dry_run
    result = ensure_faceid_buffalo_bridge(
        comfyui_runtime=comfyui_runtime,
        canonical_insightface_dir=canonical_dir,
        bundle_models=list(bundle.models),
        dry_run=dry_run,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        for msg in result.messages:
            print(msg)
        for err in result.errors:
            print(err, file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
