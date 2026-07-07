#!/usr/bin/env python3
"""Validate assets against asset_registry.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.runtime.asset_manager import AssetManager
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def to_human(data: dict) -> str:
    summary = data["summary"]
    lines = [
        "AI Studio — Asset Validation",
        "=" * 40,
        f"Total:   {summary['total']}",
        f"Present: {summary['present']}",
        f"Missing: {summary['missing']}",
        f"Planned: {summary['planned']}",
    ]
    if summary.get("required_missing"):
        lines.append(f"Required missing: {', '.join(summary['required_missing'])}")
    lines.append("\nBy type:")
    for key in sorted(summary.get("by_type", {})):
        lines.append(f"  {key}: {summary['by_type'][key]}")
    lines.append("\nBy detected status:")
    for key in sorted(summary.get("by_status", {})):
        lines.append(f"  {key}: {summary['by_status'][key]}")
    return "\n".join(lines)


def to_summary_line(data: dict) -> str:
    s = data["summary"]
    return (
        f"Assets: {s['total']} total | "
        f"{s['present']} present | "
        f"{s['missing']} missing | "
        f"{s['planned']} planned"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate AI Studio asset registry.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--type", dest="asset_type", default=None, help="Filter by asset_type.")
    parser.add_argument("--workflow", default=None, help="Filter by workflow id.")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
        bundle = RegistryLoader(repo_root).load_all()
        manager = AssetManager(bundle=bundle)
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    data = manager.to_dict(workflow_id=args.workflow)

    if args.asset_type:
        data["assets"] = [a for a in data["assets"] if a["asset_type"] == args.asset_type]
        data["summary"]["total"] = len(data["assets"])

    if args.json:
        print(json.dumps(data, indent=2))
    elif args.summary:
        print(to_summary_line(data))
    else:
        print(to_human(data))
        print()
        print(to_summary_line(data))

    print("\nRESULT: OK — asset validation complete (informational).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
