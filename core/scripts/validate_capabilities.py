#!/usr/bin/env python3
"""Validate capability readiness from capability registry."""

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


from core.runtime.capability_manager import CapabilityManager
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _to_summary_line(data: dict) -> str:
    s = data["summary"]
    return (
        f"Capabilities: {s['total']} total | "
        f"Ready: {s['ready']} | "
        f"Partial: {s['partial']} | "
        f"Unavailable: {s['unavailable']} | "
        f"Blocked: {s['blocked']}"
    )


def _to_human(data: dict, selected_id: str | None = None) -> str:
    s = data["summary"]
    lines = [
        "AI Studio — Capability Validation",
        "=" * 40,
        f"Total:        {s['total']}",
        f"Ready:        {s['ready']}",
        f"Partial:      {s['partial']}",
        f"Unavailable:  {s['unavailable']}",
        f"Blocked:      {s['blocked']}",
    ]
    if selected_id:
        lines.append(f"\nFilter: capability={selected_id}")
    lines.append("\nBy status:")
    for key in sorted(s.get("by_status", {})):
        lines.append(f"  {key}: {s['by_status'][key]}")
    lines.append("\nCapabilities:")
    for cap in data["capabilities"]:
        evidence = cap.get("evidence_status")
        execution = cap.get("execution_input_status")
        evidence_suffix = ""
        if evidence and evidence != "not_evaluated":
            evidence_suffix = f" | evidence={evidence}"
        execution_suffix = ""
        if execution and execution != "not_applicable":
            execution_suffix = f" | input={execution}"
        lines.append(f"  [{cap['computed_status'].upper():11}] {cap['id']} ({cap['name']}){evidence_suffix}{execution_suffix}")
        if cap.get("reasons"):
            for reason in cap["reasons"]:
                lines.append(f"      - {reason}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate capability registry readiness.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--capability", default=None, help="Show a single capability by id.")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
        bundle = RegistryLoader(repo_root).load_all()
        manager = CapabilityManager(bundle=bundle)
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    data = manager.to_dict()

    if args.capability:
        cap = next((c for c in data["capabilities"] if c["id"] == args.capability), None)
        if cap is None:
            print(f"ERROR: Unknown capability id: {args.capability}", file=sys.stderr)
            return 1
        data["capabilities"] = [cap]
        data["summary"] = {
            "total": 1,
            "ready": 1 if cap["computed_status"] == "ready" else 0,
            "partial": 1 if cap["computed_status"] == "partial" else 0,
            "unavailable": 1 if cap["computed_status"] == "unavailable" else 0,
            "blocked": 1 if cap["computed_status"] == "blocked" else 0,
            "by_category": {cap["category"]: 1},
            "by_maturity": {cap["maturity"]: 1},
            "by_status": {cap["computed_status"]: 1},
        }

    if args.json:
        print(json.dumps(data, indent=2))
    elif args.summary:
        print(_to_summary_line(data))
    else:
        print(_to_human(data, selected_id=args.capability))
        print()
        print(_to_summary_line(data))

    print("\nRESULT: OK — capability validation complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
