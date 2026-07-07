#!/usr/bin/env python3
"""Read-only dogfooding checks for core runtime + base txt2img workflow."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.runtime_manager import RuntimeManager

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
    if overall == "fail":
        return DogfoodCheck(
            "runtime_report",
            "WARN",
            f"Runtime health is {overall.upper()} (environment-dependent).",
            {"overall": overall},
        )
    return DogfoodCheck(
        "runtime_report",
        "PASS" if overall == "ok" else "WARN",
        f"Runtime health: {overall.upper()}",
        {"overall": overall},
    )


def check_capability_summary(repo_root: Path) -> DogfoodCheck:
    manager = RuntimeManager(repo_root)
    data = manager.capability_summary()
    txt2img = next((c for c in data.get("capabilities", []) if c.get("id") == "txt2img"), None)
    if not txt2img:
        return DogfoodCheck("capability_summary", "FAIL", "txt2img capability not found in registry.")
    status = txt2img.get("computed_status", "unknown")
    if status == "ready" and not _sd15_present(repo_root):
        return DogfoodCheck(
            "capability_summary",
            "WARN",
            "txt2img marked ready but SD1.5 checkpoint not detected.",
            {"txt2img_status": status, "reasons": txt2img.get("reasons", [])},
        )
    if status in {"partial", "planned"}:
        return DogfoodCheck(
            "capability_summary",
            "WARN",
            f"txt2img capability is {status} (expected before full Colab validation).",
            {"txt2img_status": status, "reasons": txt2img.get("reasons", [])},
        )
    return DogfoodCheck(
        "capability_summary",
        "PASS",
        f"txt2img capability status: {status}",
        {"txt2img_status": status},
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
    if "missing required" in output.lower():
        return DogfoodCheck(
            "node_status",
            "WARN",
            "One or more required custom nodes are missing.",
            {"exit_code": result.returncode},
        )
    if result.returncode != 0:
        return DogfoodCheck(
            "node_status",
            "WARN",
            "Node check reported incomplete state.",
            {"exit_code": result.returncode},
        )
    return DogfoodCheck("node_status", "PASS", "All registered nodes present.")


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
    if not workflow_path.is_file():
        return DogfoodCheck("txt2img_workflow", "FAIL", f"Missing workflow file: {TXT2IMG_WORKFLOW}")
    try:
        with workflow_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        return DogfoodCheck("txt2img_workflow", "FAIL", f"Invalid workflow JSON: {exc}")
    nodes = data.get("nodes", [])
    required_types = {
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "EmptyLatentImage",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    }
    present_types = {node.get("type") for node in nodes if isinstance(node, dict)}
    missing_types = sorted(required_types - present_types)
    if missing_types:
        return DogfoodCheck(
            "txt2img_workflow",
            "FAIL",
            f"Workflow missing required node types: {', '.join(missing_types)}",
        )
    return DogfoodCheck(
        "txt2img_workflow",
        "PASS",
        f"Workflow JSON valid with {len(nodes)} nodes.",
        {"path": str(workflow_path)},
    )


def check_comfyui_output(repo_root: Path) -> DogfoodCheck:
    bundle = RegistryLoader(repo_root).load_all()
    output_dir = bundle.path("comfyui_output")
    comfyui_runtime = bundle.path("comfyui_runtime")

    if not comfyui_runtime.exists():
        return DogfoodCheck(
            "comfyui_output",
            "WARN",
            "ComfyUI runtime not installed yet.",
            {"runtime_path": str(comfyui_runtime)},
        )
    if not output_dir.is_dir():
        return DogfoodCheck(
            "comfyui_output",
            "WARN",
            "ComfyUI output directory not present yet.",
            {"output_path": str(output_dir)},
        )

    files = [p for p in output_dir.rglob("*") if p.is_file()]
    if not files:
        return DogfoodCheck(
            "comfyui_output",
            "WARN",
            "Output directory exists but no generated files yet.",
            {"output_path": str(output_dir)},
        )
    latest = max(files, key=lambda p: p.stat().st_mtime)
    return DogfoodCheck(
        "comfyui_output",
        "PASS",
        f"Latest output file detected: {latest.name}",
        {"output_path": str(output_dir), "latest_file": str(latest)},
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
        check_comfyui_output(repo_root),
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
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
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
