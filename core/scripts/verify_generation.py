#!/usr/bin/env python3
"""Report local and Drive generation evidence without modifying files."""

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


from core.runtime.generation_evidence_ledger import EvidenceLedger
from core.runtime.output_evidence import inspect_generation_evidence
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_validation import WORKFLOW_OUTPUT_PREFIXES

WORKFLOW_CHOICES = {
    "txt2img": WORKFLOW_OUTPUT_PREFIXES["base_txt2img"],
    "img2img": WORKFLOW_OUTPUT_PREFIXES["base_img2img"],
    "inpainting": WORKFLOW_OUTPUT_PREFIXES["base_inpainting"],
    "outpainting": WORKFLOW_OUTPUT_PREFIXES["base_outpainting"],
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect newest eligible ComfyUI generation evidence (read-only)."
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--summary", action="store_true", help="Print one-line summary.")
    parser.add_argument("--json", action="store_true", help="Print structured JSON.")
    parser.add_argument(
        "--require-local",
        action="store_true",
        help="Exit non-zero when no eligible local output exists.",
    )
    parser.add_argument(
        "--require-drive",
        action="store_true",
        help="Exit non-zero when no eligible Drive output exists.",
    )
    parser.add_argument(
        "--workflow",
        choices=sorted(WORKFLOW_CHOICES),
        default=None,
        help="Filter evidence by workflow output prefix.",
    )
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
        bundle = RegistryLoader(repo_root).load_all()
    except (FileNotFoundError, ValueError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output_prefix = WORKFLOW_CHOICES.get(args.workflow) if args.workflow else None
    evidence = inspect_generation_evidence(
        bundle.path("comfyui_output"),
        bundle.path("drive_outputs"),
        output_prefix=output_prefix,
    )
    payload = evidence.to_dict()

    ledger_summary = {"path": "", "rows": 0, "verified": 0, "pending": 0, "failed": 0}
    try:
        ledger_path = bundle.path("drive_logs") / "generation_evidence.jsonl"
        ledger_summary["path"] = str(ledger_path)
        rows = EvidenceLedger(ledger_path).read_all()
        ledger_summary["rows"] = len(rows)
        for row in rows:
            status = str(row.get("sync_status") or "")
            if status == "verified":
                ledger_summary["verified"] += 1
            elif status == "pending":
                ledger_summary["pending"] += 1
            elif status == "failed":
                ledger_summary["failed"] += 1
    except KeyError:
        pass
    payload["autosync_ledger"] = ledger_summary

    if args.json:
        print(json.dumps(payload, indent=2))
    elif args.summary:
        local_file = payload.get("local_file") or {}
        drive_file = payload.get("drive_file") or {}
        local_name = local_file.get("filename", "none")
        drive_name = drive_file.get("filename", "none")
        print(
            f"Generation evidence: {payload['evidence_status']} | "
            f"workflow={args.workflow or 'latest'} | "
            f"local={local_name} | drive={drive_name} | "
            f"ledger_verified={ledger_summary['verified']} "
            f"pending={ledger_summary['pending']} failed={ledger_summary['failed']}"
        )
    else:
        print("AI Studio — Generation Evidence")
        print("=" * 40)
        print(f"Status:            {payload['evidence_status']}")
        print(f"Local output dir:  {payload['local_output_dir']}")
        print(f"Drive output dir:  {payload['drive_output_dir']}")
        if payload.get("local_file"):
            local = payload["local_file"]
            print(
                f"Local file:        {local['filename']} "
                f"({local['size_bytes']} bytes, {local['modified_at']})"
            )
        else:
            print("Local file:        none")
        if payload.get("drive_file"):
            drive = payload["drive_file"]
            print(
                f"Drive file:        {drive['filename']} "
                f"({drive['size_bytes']} bytes, {drive['modified_at']})"
            )
        else:
            print("Drive file:        none")
        if payload.get("historical_drive_evidence"):
            historical = payload["historical_drive_evidence"]
            print(
                f"Historical drive:  {historical['filename']} "
                f"({historical['size_bytes']} bytes, {historical['modified_at']})"
            )
        print(
            f"Autosync ledger:   {ledger_summary['rows']} rows "
            f"(verified={ledger_summary['verified']}, "
            f"pending={ledger_summary['pending']}, failed={ledger_summary['failed']})"
        )
        for message in payload.get("messages", []):
            print(f"Note:              {message}")

    exit_code = 0
    if args.require_local and not evidence.local_verified:
        exit_code = 1
    if args.require_drive and not evidence.drive_verified:
        exit_code = max(exit_code, 1)

    if exit_code == 0:
        print("\nRESULT: OK — generation evidence inspection complete.")
    else:
        print("\nRESULT: WARN — required generation evidence not found.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
