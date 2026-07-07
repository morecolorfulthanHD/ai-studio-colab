#!/usr/bin/env python3
"""Unified runtime health and status report for AI Studio."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.runtime.runtime_manager import RuntimeManager
from core.runtime.registry_loader import find_repo_root


def build_report(manager: RuntimeManager) -> dict:
    health = manager.health_report()
    status = manager.get_runtime_status()
    assets = manager.asset_summary()
    return {
        "runtime_status": status,
        "health": health.to_dict(),
        "assets": assets,
        "extension_points": manager.extension_points(),
    }


def to_human(report: dict) -> str:
    health = report["health"]
    lines = [
        "AI Studio — Runtime Report",
        "=" * 40,
        f"Overall health: {health['overall_status'].upper()}",
        f"Environment:      {report['runtime_status']['environment']}",
        f"Repo root:        {report['runtime_status']['repo_root']}",
        "",
        "Component Summary",
        "-" * 40,
    ]
    for check in health["checks"]:
        lines.append(f"  [{check['status'].upper():7}] {check['component']}: {check['message']}")

    summary = report["runtime_status"]["registry_summary"]
    asset_summary = report.get("assets", {}).get("summary", {})
    lines.extend(
        [
            "",
            "Registry Summary",
            "-" * 40,
            f"  Models:    {summary['models']}",
            f"  Nodes:     {summary['nodes']}",
            f"  Workflows: {summary['workflows']}",
            f"  Presets:   {summary['presets']}",
            f"  Assets:    {summary.get('assets', 0)}",
            f"  Manifests: {summary['manifests']}",
        ]
    )
    if asset_summary:
        lines.extend(
            [
                "",
                "Asset Summary",
                "-" * 40,
                f"  Present: {asset_summary.get('present', 0)}",
                f"  Missing: {asset_summary.get('missing', 0)}",
                f"  Planned: {asset_summary.get('planned', 0)}",
            ]
        )
    return "\n".join(lines)


def to_summary(report: dict) -> str:
    health = report["health"]
    reg = report["runtime_status"]["registry_summary"]
    asset = report.get("assets", {}).get("summary", {})
    asset_part = ""
    if asset:
        asset_part = (
            f" | Assets: {asset.get('present', 0)} present"
            f"/{asset.get('total', 0)} total"
        )
    return (
        f"Health: {health['overall_status'].upper()} | "
        f"Env: {report['runtime_status']['environment']} | "
        f"Models: {reg['models']} | Nodes: {reg['nodes']} | "
        f"Workflows: {reg['workflows']}{asset_part}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Studio unified runtime report.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="Output structured JSON.")
    parser.add_argument("--summary", action="store_true", help="One-line summary only.")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
        manager = RuntimeManager(repo_root)
        report = build_report(manager)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    elif args.summary:
        print(to_summary(report))
    else:
        print(to_human(report))
        print()
        print(to_summary(report))

    overall = report["health"]["overall_status"]
    if overall == "fail":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
