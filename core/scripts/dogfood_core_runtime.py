#!/usr/bin/env python3
"""Read-only dogfooding checks for core runtime + base txt2img workflow."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)


from core.runtime.output_evidence import inspect_generation_evidence
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.runtime_manager import RuntimeManager
from core.runtime.workflow_validation import validate_base_txt2img_workflow

TXT2IMG_WORKFLOW = "workflows/base/txt2img/workflow.json"
SD15_RUNTIME_PATH = "/content/drive/MyDrive/AI_Studio/models/shared/checkpoints/sd15.safetensors"


@dataclass
class DogfoodCheck:
    name: str
    status: str
    message: str
    details: dict[str, object] = field(default_factory=dict)


def _detect_environment() -> str:
    return RuntimeManager._detect_environment()


def check_repo_root(repo_root: Path) -> DogfoodCheck:
    required = ("configs", "workflows", "core", "colab", "docs")
    missing = [name for name in required if not (repo_root / name).is_dir()]
    if missing:
        return DogfoodCheck("repo_root", "FAIL", f"Missing required directories: {', '.join(missing)}")
    return DogfoodCheck("repo_root", "PASS", f"Repository root OK: {repo_root}")


def check_manifests(repo_root: Path) -> DogfoodCheck:
    script = repo_root / "core/scripts/validate_manifests.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return DogfoodCheck(
            "manifests",
            "FAIL",
            "Manifest validation failed.",
            {"stderr": (result.stderr or result.stdout).strip()},
        )
    return DogfoodCheck("manifests", "PASS", "All manifests passed schema validation.")


def check_runtime_report(repo_root: Path) -> DogfoodCheck:
    manager = RuntimeManager(repo_root)
    report = manager.health_report()
    overall = report.overall_status.value
    node_check = next((c for c in report.checks if c.component == "node_registry"), None)
    node_message = node_check.message if node_check else "unknown"
    if overall == "fail":
        return DogfoodCheck(
            "runtime_report",
            "WARN",
            f"Runtime health is {overall.upper()} (environment-dependent). {node_message}",
            {"overall": overall},
        )
    return DogfoodCheck(
        "runtime_report",
        "PASS" if overall == "ok" else "WARN",
        f"Runtime health: {overall.upper()}. {node_message}",
        {"overall": overall},
    )


def check_capability_summary(repo_root: Path) -> DogfoodCheck:
    manager = RuntimeManager(repo_root)
    data = manager.capability_summary("txt2img")
    txt2img = next((c for c in data.get("capabilities", []) if c.get("id") == "txt2img"), None)
    if not txt2img:
        return DogfoodCheck("capability_summary", "FAIL", "txt2img capability not found in registry.")
    status = txt2img.get("computed_status", "unknown")
    evidence = txt2img.get("evidence_status", "not_evaluated")
    details = {
        "txt2img_status": status,
        "txt2img_evidence": evidence,
        "reasons": txt2img.get("reasons", []),
        "runtime_checks": txt2img.get("runtime_checks", []),
    }
    if status == "ready":
        message = f"txt2img readiness: READY; evidence: {evidence.upper().replace('_', ' ')}"
        return DogfoodCheck("capability_summary", "PASS", message, details)
    if status == "partial":
        return DogfoodCheck(
            "capability_summary",
            "WARN",
            f"txt2img readiness: PARTIAL; evidence: {evidence.upper().replace('_', ' ')}",
            details,
        )
    return DogfoodCheck(
        "capability_summary",
        "WARN",
        f"txt2img readiness: {status.upper()}; evidence: {evidence.upper().replace('_', ' ')}",
        details,
    )


def _sd15_present(repo_root: Path) -> bool:
    bundle = RegistryLoader(repo_root).load_all()
    for entry in bundle.models:
        if entry.get("name") != "sd15_checkpoint":
            continue
        paths = [repo_root / entry.get("intended_path", "")]
        runtime = entry.get("runtime_path")
        if runtime:
            paths.append(Path(runtime))
        paths.append(Path(SD15_RUNTIME_PATH))
        for path in paths:
            if path.is_file() and path.stat().st_size > 0:
                return True
    return False


def _parse_node_summary(output: str) -> tuple[int, int]:
    match = re.search(
        r"(\d+) installed/present,\s*(\d+) required missing,\s*(\d+) optional missing",
        output,
    )
    if not match:
        return 0, 0
    return int(match.group(2)), int(match.group(3))


def check_node_status(repo_root: Path) -> DogfoodCheck:
    script = repo_root / "core/scripts/check_nodes.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout or "") + (result.stderr or "")
    missing_required, missing_optional = _parse_node_summary(output)

    if "INCOMPLETE" in output or missing_required > 0:
        return DogfoodCheck(
            "node_status",
            "WARN",
            f"Required custom nodes missing ({missing_required}).",
            {"exit_code": result.returncode, "missing_required": missing_required},
        )
    if missing_optional > 0:
        return DogfoodCheck(
            "node_status",
            "WARN",
            f"Required nodes OK; {missing_optional} optional node(s) missing.",
            {"exit_code": result.returncode, "missing_optional": missing_optional},
        )
    if result.returncode != 0:
        return DogfoodCheck(
            "node_status",
            "WARN",
            "Node check reported incomplete state.",
            {"exit_code": result.returncode},
        )
    return DogfoodCheck("node_status", "PASS", "Required nodes OK; all registered nodes present.")


def check_model_status(repo_root: Path) -> DogfoodCheck:
    if _sd15_present(repo_root):
        return DogfoodCheck(
            "model_status",
            "PASS",
            "SD1.5 checkpoint detected at configured path(s).",
            {"sd15_path": SD15_RUNTIME_PATH},
        )
    return DogfoodCheck(
        "model_status",
        "WARN",
        "SD1.5 checkpoint not found (manual placement required; no auto-download).",
        {"expected_path": SD15_RUNTIME_PATH},
    )


def check_txt2img_workflow(repo_root: Path) -> DogfoodCheck:
    workflow_path = repo_root / TXT2IMG_WORKFLOW
    validation = validate_base_txt2img_workflow(workflow_path)
    if not validation.valid:
        return DogfoodCheck(
            "txt2img_workflow",
            "FAIL",
            validation.reasons[0] if validation.reasons else "Workflow validation failed.",
            {"path": str(workflow_path), "reasons": validation.reasons},
        )
    return DogfoodCheck(
        "txt2img_workflow",
        "PASS",
        f"Workflow JSON valid with {validation.node_count} nodes.",
        {"path": str(workflow_path), "present_node_types": validation.present_node_types},
    )


def check_generation_evidence(repo_root: Path) -> DogfoodCheck:
    bundle = RegistryLoader(repo_root).load_all()
    evidence = inspect_generation_evidence(
        bundle.path("comfyui_output"),
        bundle.path("drive_outputs"),
    )
    details = evidence.to_dict()

    if evidence.local_verified and evidence.drive_verified:
        return DogfoodCheck(
            "generation_evidence",
            "PASS",
            "Local and Drive generation evidence verified.",
            details,
        )
    if evidence.local_verified:
        return DogfoodCheck(
            "generation_evidence",
            "WARN",
            "Local generation evidence verified; Drive synchronization not yet verified.",
            details,
        )
    if evidence.local_output_dir and Path(evidence.local_output_dir).is_dir():
        return DogfoodCheck(
            "generation_evidence",
            "WARN",
            "Output directory exists but no eligible generated output found yet.",
            details,
        )
    return DogfoodCheck(
        "generation_evidence",
        "WARN",
        "No generation evidence yet (expected before first successful txt2img run).",
        details,
    )


def run_checks(repo_root: Path) -> list[DogfoodCheck]:
    return [
        check_repo_root(repo_root),
        check_manifests(repo_root),
        check_runtime_report(repo_root),
        check_capability_summary(repo_root),
        check_node_status(repo_root),
        check_model_status(repo_root),
        check_txt2img_workflow(repo_root),
        check_generation_evidence(repo_root),
    ]


def print_summary(checks: list[DogfoodCheck], environment: str) -> None:
    print("AI Studio — Dogfooding: Core Runtime + Base txt2img")
    print("=" * 50)
    print(f"Environment: {environment}")
    print()
    for check in checks:
        print(f"[{check.status:4}] {check.name}: {check.message}")
    print()
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    print(
        f"Summary: {counts.get('PASS', 0)} pass, "
        f"{counts.get('WARN', 0)} warn, {counts.get('FAIL', 0)} fail"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only dogfooding checks for core runtime + base txt2img."
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="Output structured JSON.")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
        checks = run_checks(repo_root)
    except (FileNotFoundError, ValueError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    environment = _detect_environment()

    if args.json:
        payload = {
            "environment": environment,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                    "details": c.details,
                }
                for c in checks
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        print_summary(checks, environment)

    if any(c.status == "FAIL" for c in checks):
        print("\nRESULT: FAIL — repository/schema checks failed.", file=sys.stderr)
        return 1

    if any(c.status == "WARN" for c in checks):
        print("\nRESULT: WARN — checks completed with environment/runtime warnings.")
        return 0

    print("\nRESULT: PASS — all dogfooding checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
