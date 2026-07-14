#!/usr/bin/env python3
"""Unified runtime health and status report for AI Studio."""

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


from core.runtime.runtime_manager import RuntimeManager
from core.runtime.registry_loader import find_repo_root


EDITING_CAPABILITY_IDS = ("img2img", "inpainting", "outpainting")


def _capability_block(capability: dict | None, default_path: str) -> dict:
    if not capability:
        return {
            "workflow_present": False,
            "workflow_status": "missing",
            "workflow_path": default_path,
            "capability_status": "unknown",
            "evidence_status": "not_evaluated",
            "execution_input_status": "not_applicable",
            "capability_reasons": [],
            "runtime_checks": [],
        }
    return {
        "workflow_present": True,
        "workflow_status": "active",
        "workflow_path": default_path,
        "capability_status": capability.get("computed_status", "unknown"),
        "evidence_status": capability.get("evidence_status", "not_evaluated"),
        "execution_input_status": capability.get("execution_input_status", "not_applicable"),
        "capability_reasons": capability.get("reasons", []),
        "runtime_checks": capability.get("runtime_checks", []),
    }


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
    editing_capabilities = {
        cap_id: _capability_block(
            next((c for c in capabilities.get("capabilities", []) if c.get("id") == cap_id), None),
            {
                "img2img": "workflows/base/img2img/workflow.json",
                "inpainting": "workflows/base/inpainting/workflow.json",
                "outpainting": "workflows/base/outpainting/workflow.json",
            }[cap_id],
        )
        for cap_id in EDITING_CAPABILITY_IDS
    }
    node_details = checks.get("node_registry", {}).get("details", {})
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
            "evidence_status": txt2img_capability.get("evidence_status", "not_evaluated")
            if txt2img_capability
            else "not_evaluated",
            "capability_reasons": txt2img_capability.get("reasons", []) if txt2img_capability else [],
            "runtime_checks": txt2img_capability.get("runtime_checks", []) if txt2img_capability else [],
        },
        "image_editing": editing_capabilities,
        "nodes": {
            "core_ready": node_details.get("core_ready", False),
            "missing_required": node_details.get("missing_required", []),
            "missing_optional": node_details.get("missing_optional", []),
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
                f"  Readiness:  {txt2img.get('capability_status', 'unknown')}",
                f"  Evidence:   {txt2img.get('evidence_status', 'not_evaluated')}",
            ]
        )
        for reason in txt2img.get("capability_reasons", []):
            lines.append(f"  Reason:     {reason}")
        for reason in txt2img.get("runtime_checks", []):
            lines.append(f"  Runtime:    {reason}")
    editing = report.get("image_editing", {})
    if editing:
        lines.extend(["", "Image Editing Runtime Status", "-" * 40])
        for cap_id in EDITING_CAPABILITY_IDS:
            cap = editing.get(cap_id, {})
            lines.append(
                f"  {cap_id:11} readiness={cap.get('capability_status', 'unknown')} "
                f"evidence={cap.get('evidence_status', 'not_evaluated')} "
                f"input={cap.get('execution_input_status', 'not_applicable')}"
            )
    nodes = report.get("nodes", {})
    if nodes:
        lines.extend(
            [
                "",
                "Node Health",
                "-" * 40,
                f"  Core ready: {nodes.get('core_ready', False)}",
                f"  Missing required: {', '.join(nodes.get('missing_required', [])) or 'none'}",
                f"  Missing optional: {', '.join(nodes.get('missing_optional', [])) or 'none'}",
            ]
        )
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
    evidence_state = report.get("txt2img", {}).get("evidence_status", "not_evaluated")
    node_details = report.get("nodes", {})
    optional_missing = len(node_details.get("missing_optional", []))
    node_part = f" | CoreNodes: {'OK' if node_details.get('core_ready') else 'WARN'}"
    if optional_missing:
        node_part += f" | OptionalMissing: {optional_missing}"
    editing_states = [
        report.get("image_editing", {}).get(cap_id, {}).get("capability_status", "unknown")
        for cap_id in EDITING_CAPABILITY_IDS
    ]
    editing_part = ""
    if any(state != "unknown" for state in editing_states):
        editing_part = (
            f" | editing: img2img={editing_states[0]} inpaint={editing_states[1]} outpaint={editing_states[2]}"
        )
    watcher_check = next(
        (c for c in health.get("checks", []) if c.get("component") == "output_watcher"),
        None,
    )
    watcher_part = ""
    if watcher_check:
        watcher_part = f" | OutputWatcher: {str(watcher_check.get('status', 'unknown')).upper()}"
    return (
        f"Health: {health['overall_status'].upper()} | "
        f"Env: {report['runtime_status']['environment']} | "
        f"ComfyUI: {comfyui_state} | Nodes: {node_state} | ModelCheck: {model_state}{node_part} | "
        f"Models: {reg['models']} | Nodes: {reg['nodes']} | "
        f"Workflows: {reg['workflows']} | txt2img: {txt2img_state} | evidence: {evidence_state}"
        f"{editing_part}{watcher_part}{asset_part}{capability_part}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Studio unified runtime report.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="Output structured JSON.")
    parser.add_argument("--summary", action="store_true", help="One-line summary only.")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
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
