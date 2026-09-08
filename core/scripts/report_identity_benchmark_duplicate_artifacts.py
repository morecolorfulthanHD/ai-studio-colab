#!/usr/bin/env python3
"""Report-only scan for historical duplicate identity-benchmark Drive artifacts.

Defaults to dry-run / report-only. Never deletes Drive files.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.generation_evidence_ledger import EvidenceLedger, file_sha256
from core.runtime.identity_benchmark_artifact import (
    choose_canonical_drive_path,
    execution_artifact_key,
    format_historical_duplicate_report,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def scan_historical_duplicates(
    *,
    evidence_path: Path,
    drive_output_dir: Path | None = None,
) -> list[dict]:
    """Group verified evidence by prompt|node|sha and report multi-path groups."""
    groups: dict[str, list[Path]] = defaultdict(list)
    if not evidence_path.is_file():
        return []
    for row in EvidenceLedger(evidence_path).read_all():
        if str(row.get("sync_status") or "") != "verified":
            continue
        prompt_id = str(row.get("prompt_id") or "")
        node_id = str(row.get("output_node_id") or "")
        sha = str(row.get("drive_sha256") or row.get("local_sha256") or "").strip().lower()
        drive_path = Path(str(row.get("drive_path") or ""))
        if not prompt_id or not node_id or not sha or not drive_path.is_file():
            continue
        if drive_output_dir is not None:
            try:
                drive_path.resolve().relative_to(Path(drive_output_dir).resolve())
            except (OSError, ValueError):
                continue
        try:
            if file_sha256(drive_path).lower() != sha:
                continue
        except OSError:
            continue
        key = execution_artifact_key(prompt_id, node_id, sha)
        if drive_path not in groups[key]:
            groups[key].append(drive_path)

    reports: list[dict] = []
    for key, paths in sorted(groups.items()):
        unique = list({str(p.resolve()): p for p in paths}.values())
        if len(unique) < 2:
            continue
        canonical, duplicates = choose_canonical_drive_path(unique)
        sha = key.rsplit("|", 1)[-1]
        reports.append(
            {
                "execution_key": key,
                "canonical": str(canonical),
                "duplicates": [str(p) for p in duplicates],
                "same_sha": True,
                "action": "none (report-only)",
                "messages": format_historical_duplicate_report(
                    canonical=canonical, duplicates=duplicates, sha=sha
                ),
            }
        )
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report historical duplicate identity-benchmark Drive artifacts "
            "(prompt_id + output_node_id + SHA). Never deletes files."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--evidence-path", type=Path, default=None)
    parser.add_argument("--drive-output-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Reserved; this tool is report-only and never mutates Drive files.",
    )
    args = parser.parse_args()
    if args.execute:
        print(
            "NOTE: --execute is accepted for CLI consistency but this tool never "
            "deletes or rewrites Drive files (report-only).",
            file=sys.stderr,
        )

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    drive_root = bundle.path("drive_root")
    evidence = Path(args.evidence_path or (drive_root / "logs" / "autosync" / "evidence.jsonl"))
    out_dir = Path(args.drive_output_dir or (drive_root / "outputs"))
    reports = scan_historical_duplicates(evidence_path=evidence, drive_output_dir=out_dir)
    if args.json:
        print(json.dumps({"duplicate_groups": reports, "count": len(reports)}, indent=2))
    else:
        print(f"Historical duplicate groups: {len(reports)}")
        for row in reports:
            for line in row.get("messages") or []:
                print(line)
                print()
        if not reports:
            print("No historical duplicate identity-benchmark artifacts detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
