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
    capabilities = manager.capability_summary()
    checks = {c["component"]: c for c in health.to_dict()["checks"]}
    txt2img_workflow = next(
        (w for w in manager.load_registries().workflows if w.get("id") == "base_txt2img"),
        None,
    )
    txt2img_capability = next(
        (c for c in capabilities.get("capabilities", []) if c.get("id") == "txt2img"),
        None,
    )
    return {
        "runtime_status": status,
        "health": health.to_dict(),
        "assets": assets,
        "capabilities": capabilities,
        "runtime_execution": {
            "comfyui": checks.get("comfyui", {}),
            "nodes": checks.get("node_registry", {}),
            "models": checks.get("model_registry", {}),
        },
        "txt2img": {
            "workflow_present": bool(txt2img_workflow),
            "workflow_status": txt2img_workflow.get("status", "unknown") if txt2img_workflow else "missing",
            "workflow_path": txt2img_workflow.get("path", "workflows/base/txt2img/workflow.json")
            if txt2img_workflow
            else "workflows/base/txt2img/workflow.json",
            "capability_status": txt2img_capability.get("computed_status", "unknown")
            if txt2img_capability
            else "unknown",
            "capability_reasons": txt2img_capability.get("reasons", []) if txt2img_capability else [],
        },
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
    capability_summary = report.get("capabilities", {}).get("summary", {})
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
            f"  Capabilities: {summary.get('capabilities', 0)}",
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
    if capability_summary:
        lines.extend(
            [
                "",
                "Capability Summary",
                "-" * 40,
                f"  Ready:       {capability_summary.get('ready', 0)}",
                f"  Partial:     {capability_summary.get('partial', 0)}",
                f"  Unavailable: {capability_summary.get('unavailable', 0)}",
                f"  Blocked:     {capability_summary.get('blocked', 0)}",
            ]
        )
    txt2img = report.get("txt2img", {})
    if txt2img:
        lines.extend(
            [
                "",
                "txt2img Runtime Status",
                "-" * 40,
                f"  Workflow:   {txt2img.get('workflow_status', 'unknown')} ({txt2img.get('workflow_path', '')})",
                f"  Capability: {txt2img.get('capability_status', 'unknown')}",
            ]
        )
        for reason in txt2img.get("capability_reasons", []):
            lines.append(f"  Reason:     {reason}")
    return "\n".join(lines)


def to_summary(report: dict) -> str:
    health = report["health"]
    reg = report["runtime_status"]["registry_summary"]
    asset = report.get("assets", {}).get("summary", {})
    cap = report.get("capabilities", {}).get("summary", {})
    asset_part = ""
    if asset:
        asset_part = (
            f" | Assets: {asset.get('present', 0)} present"
            f"/{asset.get('total', 0)} total"
        )
    capability_part = ""
    if cap:
        capability_part = (
            f" | Caps: {cap.get('ready', 0)} ready"
            f"/{cap.get('total', 0)} total"
        )
    runtime_exec = report.get("runtime_execution", {})
    comfyui_state = runtime_exec.get("comfyui", {}).get("status", "unknown").upper()
    node_state = runtime_exec.get("nodes", {}).get("status", "unknown").upper()
    model_state = runtime_exec.get("models", {}).get("status", "unknown").upper()
    txt2img_state = report.get("txt2img", {}).get("capability_status", "unknown")
    return (
        f"Health: {health['overall_status'].upper()} | "
        f"Env: {report['runtime_status']['environment']} | "
        f"ComfyUI: {comfyui_state} | Nodes: {node_state} | ModelCheck: {model_state} | "
        f"Models: {reg['models']} | Nodes: {reg['nodes']} | "
        f"Workflows: {reg['workflows']} | txt2img: {txt2img_state}{asset_part}{capability_part}"
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
