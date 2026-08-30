#!/usr/bin/env python3
"""Recover uncaptured identity-benchmark executions from ComfyUI /history."""

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

from core.runtime.identity_benchmark_capture import recover_identity_benchmarks_from_history
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_provenance import load_registered_workflow_hashes


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scan live ComfyUI history for prepared identity-benchmark executions "
            "missing from identity_benchmark.jsonl. Idempotent; fail closed on ambiguity."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--comfyui-base-url", default=None)
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    drive_root = bundle.path("drive_root")
    ledger = args.ledger or (bundle.path("drive_logs") / "identity_benchmark.jsonl")
    comfy = bundle.path("comfyui_runtime")
    base = args.comfyui_base_url
    if not base:
        from core.runtime.comfyui_userdata import DEFAULT_COMFY_BASE_URL

        base = DEFAULT_COMFY_BASE_URL

    registered = load_registered_workflow_hashes(repo_root, bundle.workflows)
    report = recover_identity_benchmarks_from_history(
        drive_root=drive_root,
        ledger_path=ledger,
        comfy_output_dir=comfy / "output",
        base_url=base,
        registered_hashes=registered,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("AI Studio — Identity Benchmark History Recovery")
        print("=" * 40)
        print(f"Examined history prompts: {report.get('examined')}")
        print(f"Newly captured: {report.get('captured')}")
        print(f"Duplicates skipped: {report.get('duplicates')}")
        print(f"Non-benchmark skipped: {report.get('skipped_non_benchmark')}")
        print(f"Failed: {report.get('failed')}")
        for msg in report.get("messages") or []:
            print(f"  {msg}")
        for err in report.get("errors") or []:
            print(err, file=sys.stderr)
        print(f"RESULT: {'OK' if report.get('ok') else 'FAIL'}")
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
