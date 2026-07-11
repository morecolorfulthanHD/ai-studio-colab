#!/usr/bin/env python3
"""Structured health reporting for AI Studio runtime components."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .registry_loader import RegistryBundle


class HealthStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"
    PLANNED = "planned"


STATUS_RANK = {
    HealthStatus.OK: 0,
    HealthStatus.PLANNED: 1,
    HealthStatus.UNKNOWN: 2,
    HealthStatus.WARN: 3,
    HealthStatus.FAIL: 4,
}


@dataclass
class HealthCheck:
    component: str
    status: HealthStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class HealthReport:
    generated_at: str
    checks: list[HealthCheck] = field(default_factory=list)
    overall_status: HealthStatus = HealthStatus.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "overall_status": self.overall_status.value,
            "checks": [check.to_dict() for check in self.checks],
        }

    def to_human(self) -> str:
        lines = [
            "AI Studio — Runtime Health Report",
            "=" * 40,
            f"Generated: {self.generated_at}",
            f"Overall:   {self.overall_status.value.upper()}",
            "",
        ]
        for check in self.checks:
            lines.append(f"[{check.status.value.upper():7}] {check.component}")
            lines.append(f"          {check.message}")
        return "\n".join(lines)


def _overall_status(checks: list[HealthCheck]) -> HealthStatus:
    if not checks:
        return HealthStatus.UNKNOWN
    return max(checks, key=lambda c: STATUS_RANK[c.status]).status


def is_colab() -> bool:
    try:
        import google.colab  # noqa: F401, PLC0415

        return True
    except ImportError:
        return False


def check_notebook(bundle: RegistryBundle) -> HealthCheck:
    notebook = bundle.repo_root / "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb"
    if notebook.is_file():
        return HealthCheck(
            "notebook",
            HealthStatus.OK,
            "Canonical control panel notebook present.",
            {"path": str(notebook)},
        )
    return HealthCheck(
        "notebook",
        HealthStatus.FAIL,
        "Canonical notebook missing.",
        {"expected": str(notebook)},
    )


def check_repository(bundle: RegistryBundle) -> HealthCheck:
    required = ("configs", "workflows", "core", "colab")
    missing = [name for name in required if not (bundle.repo_root / name).is_dir()]
    if missing:
        return HealthCheck(
            "repository",
            HealthStatus.FAIL,
            f"Missing required directories: {', '.join(missing)}",
            {"repo_root": str(bundle.repo_root), "missing": missing},
        )
    return HealthCheck(
        "repository",
        HealthStatus.OK,
        "Repository structure present.",
        {"repo_root": str(bundle.repo_root), "manifest_count": len(bundle.manifests)},
    )


def check_drive(bundle: RegistryBundle) -> HealthCheck:
    drive_root = bundle.path("drive_root")
    mount_root = drive_root.parent.parent
    if not mount_root.is_dir():
        return HealthCheck(
            "drive",
            HealthStatus.WARN,
            "Google Drive does not appear mounted.",
            {"drive_root": str(drive_root)},
        )
    if not drive_root.is_dir():
        return HealthCheck(
            "drive",
            HealthStatus.WARN,
            "Drive mounted but AI_Studio root not created yet.",
            {"drive_root": str(drive_root)},
        )
    return HealthCheck(
        "drive",
        HealthStatus.OK,
        "Drive-backed AI_Studio root present.",
        {"drive_root": str(drive_root)},
    )


def check_engine_install(name: str, runtime_path: Path) -> HealthCheck:
    git_dir = runtime_path / ".git"
    if git_dir.is_dir():
        return HealthCheck(
            name,
            HealthStatus.OK,
            f"{name} installation detected.",
            {"path": str(runtime_path)},
        )
    if runtime_path.exists():
        return HealthCheck(
            name,
            HealthStatus.WARN,
            f"{name} path exists but is not a git clone.",
            {"path": str(runtime_path)},
        )
    return HealthCheck(
        name,
        HealthStatus.PLANNED,
        f"{name} not installed in this runtime session.",
        {"path": str(runtime_path)},
    )


def check_workflow_registry(bundle: RegistryBundle) -> HealthCheck:
    workflows_root = bundle.repo_path("workflows")
    on_disk = list(workflows_root.rglob("workflow.json")) if workflows_root.is_dir() else []
    planned = sum(1 for w in bundle.workflows if w.get("status") == "planned")
    active = sum(1 for w in bundle.workflows if w.get("status") == "active")
    return HealthCheck(
        "workflow_registry",
        HealthStatus.OK if bundle.workflows else HealthStatus.WARN,
        f"{len(bundle.workflows)} registered workflows; {len(on_disk)} on disk.",
        {
            "registered": len(bundle.workflows),
            "on_disk": len(on_disk),
            "planned": planned,
            "active": active,
        },
    )


def check_node_registry(bundle: RegistryBundle) -> HealthCheck:
    from .node_registry_utils import summarize_node_installation

    custom_nodes = bundle.path("comfyui_runtime") / "custom_nodes"
    summary = summarize_node_installation(bundle.nodes, custom_nodes)

    missing_required = summary["missing_required"]
    missing_optional = summary["missing_optional"]
    installed = summary["installed"]

    if not bundle.nodes:
        status = HealthStatus.WARN
        message = "No custom nodes registered."
    elif missing_required:
        status = HealthStatus.WARN
        message = (
            f"Required nodes: {len(missing_required)} missing; "
            f"optional nodes: {len(missing_optional)} missing."
        )
    elif missing_optional:
        status = HealthStatus.WARN
        message = (
            f"Required nodes: OK ({len(installed)} present); "
            f"optional nodes: {len(missing_optional)} missing."
        )
    else:
        status = HealthStatus.OK
        message = f"Required nodes: OK; optional nodes: OK ({len(installed)} present)."

    return HealthCheck(
        "node_registry",
        status,
        message,
        summary,
    )


def _model_present(path: Path) -> bool:
    if path.is_file():
        return True
    if path.is_dir():
        try:
            return any(path.iterdir())
        except OSError:
            return False
    return False


def check_model_registry(bundle: RegistryBundle) -> HealthCheck:
    present: list[str] = []
    missing: list[str] = []
    planned: list[str] = []
    for entry in bundle.models:
        name = entry["name"]
        registry_status = entry.get("status", "planned")
        paths_to_check = [bundle.repo_root / entry.get("intended_path", "")]
        runtime = entry.get("runtime_path")
        if runtime:
            paths_to_check.append(Path(runtime))
        if any(_model_present(p) for p in paths_to_check if str(p)):
            present.append(name)
        elif registry_status == "active":
            missing.append(name)
        else:
            planned.append(name)
    if missing:
        status = HealthStatus.FAIL
    elif not present and bundle.models:
        status = HealthStatus.PLANNED
    else:
        status = HealthStatus.OK
    return HealthCheck(
        "model_registry",
        status,
        f"{len(present)} present, {len(missing)} missing (active), {len(planned)} planned.",
        {"present": present, "missing": missing, "planned": planned},
    )


def check_gpu() -> HealthCheck:
    if shutil.which("nvidia-smi") is None:
        return HealthCheck(
            "gpu",
            HealthStatus.WARN,
            "nvidia-smi not available.",
            {"python": sys.version.split()[0], "platform": platform.platform()},
        )
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return HealthCheck("gpu", HealthStatus.WARN, str(exc), {})

    if result.returncode != 0 or not result.stdout.strip():
        return HealthCheck(
            "gpu",
            HealthStatus.WARN,
            "GPU query failed or returned no devices.",
            {"stderr": (result.stderr or "").strip()},
        )
    gpus = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return HealthCheck(
        "gpu",
        HealthStatus.OK,
        f"{len(gpus)} GPU(s) detected.",
        {"devices": gpus, "colab": is_colab()},
    )


def check_asset_registry(bundle: RegistryBundle) -> HealthCheck:
    from .asset_manager import AssetManager

    manager = AssetManager(bundle=bundle)
    summary = manager.summary()
    if summary.required_missing:
        status = HealthStatus.FAIL
        message = (
            f"{summary.present} present, {summary.missing} missing, "
            f"{summary.planned} planned; {len(summary.required_missing)} required missing."
        )
    elif summary.missing:
        status = HealthStatus.WARN
        message = (
            f"{summary.present} present, {summary.missing} missing, {summary.planned} planned."
        )
    elif summary.present:
        status = HealthStatus.OK
        message = (
            f"{summary.present} present, {summary.planned} planned of {summary.total} assets."
        )
    else:
        status = HealthStatus.PLANNED
        message = f"{summary.total} assets registered; none present on disk yet."

    return HealthCheck(
        "assets",
        status,
        message,
        {
            "summary": summary.to_dict(),
            "by_type": summary.by_type,
            "required_missing": summary.required_missing,
        },
    )


def check_capabilities(bundle: RegistryBundle) -> HealthCheck:
    from .capability_manager import CapabilityManager

    manager = CapabilityManager(bundle=bundle)
    summary = manager.summary()
    if summary.blocked:
        status = HealthStatus.FAIL
    elif summary.unavailable:
        status = HealthStatus.WARN
    elif summary.partial:
        status = HealthStatus.WARN
    elif summary.ready:
        status = HealthStatus.OK
    else:
        status = HealthStatus.PLANNED

    message = (
        f"{summary.ready} ready, {summary.partial} partial, "
        f"{summary.unavailable} unavailable, {summary.blocked} blocked."
    )
    return HealthCheck(
        "capabilities",
        status,
        message,
        {"summary": summary.to_dict(), "dependency_graph": manager.dependency_graph()},
    )


def build_health_report(bundle: RegistryBundle) -> HealthReport:
    checks = [
        check_notebook(bundle),
        check_repository(bundle),
        check_drive(bundle),
        check_engine_install("comfyui", bundle.path("comfyui_runtime")),
        check_engine_install("a1111", bundle.path("a1111_runtime")),
        check_workflow_registry(bundle),
        check_node_registry(bundle),
        check_model_registry(bundle),
        check_asset_registry(bundle),
        check_capabilities(bundle),
        check_gpu(),
    ]
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return HealthReport(
        generated_at=generated_at,
        checks=checks,
        overall_status=_overall_status(checks),
    )
