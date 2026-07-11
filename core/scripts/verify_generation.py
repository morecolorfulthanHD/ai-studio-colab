#!/usr/bin/env python3
"""Report local and Drive generation evidence without modifying files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.runtime.output_evidence import inspect_generation_evidence
from core.runtime.registry_loader import RegistryLoader, find_repo_root


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
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
        bundle = RegistryLoader(repo_root).load_all()
    except (FileNotFoundError, ValueError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    evidence = inspect_generation_evidence(
        bundle.path("comfyui_output"),
        bundle.path("drive_outputs"),
    )
    payload = evidence.to_dict()

    if args.json:
        print(json.dumps(payload, indent=2))
    elif args.summary:
        local_file = payload.get("local_file") or {}
        drive_file = payload.get("drive_file") or {}
        local_name = local_file.get("filename", "none")
        drive_name = drive_file.get("filename", "none")
        print(
            f"Generation evidence: {payload['evidence_status']} | "
            f"local={local_name} | drive={drive_name}"
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
