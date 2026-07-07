#!/usr/bin/env python3
"""Registry-driven runtime manager — status, health, and future orchestration hooks."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .registry_loader import RegistryBundle, RegistryLoader, find_repo_root
from .runtime_health import HealthReport, build_health_report
from .runtime_state import RuntimeState


class RuntimeManager:
    """Central orchestration entry point for AI Studio runtime platform."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = (repo_root or find_repo_root()).resolve()
        self._loader = RegistryLoader(self.repo_root)
        self._bundle: RegistryBundle | None = None
        self._state = RuntimeState()
        self._state.touch_runtime(environment=self._detect_environment())

    @staticmethod
    def _detect_environment() -> str:
        try:
            import google.colab  # noqa: F401, PLC0415

            return "colab"
        except ImportError:
            if Path("/content").is_dir():
                return "colab-like"
            return "local"

    def load_registries(self, reload: bool = False) -> RegistryBundle:
        if self._bundle is None or reload:
            self._bundle = self._loader.load_all()
        return self._bundle

    @property
    def state(self) -> RuntimeState:
        return self._state

    def get_runtime_status(self) -> dict[str, Any]:
        bundle = self.load_registries()
        health = self.health_report()
        return {
            "repo_root": str(self.repo_root),
            "environment": self._state.environment,
            "platform_version": self._state.platform_version,
            "overall_health": health.overall_status.value,
            "registry_summary": {
                "models": len(bundle.models),
                "nodes": len(bundle.nodes),
                "workflows": len(bundle.workflows),
                "presets": len(bundle.presets),
                "manifests": len(bundle.manifests),
            },
            "paths": {key: str(bundle.path(key)) for key in bundle.paths},
            "state": self._state.to_dict(),
        }

    def health_report(self, reload: bool = False) -> HealthReport:
        bundle = self.load_registries(reload=reload)
        report = build_health_report(bundle)
        self._sync_state_from_health(bundle, report)
        return report

    def _sync_state_from_health(self, bundle: RegistryBundle, report: HealthReport) -> None:
        node_check = next((c for c in report.checks if c.component == "node_registry"), None)
        if node_check:
            self._state.update_installed_nodes(node_check.details.get("installed", []))
        model_check = next((c for c in report.checks if c.component == "model_registry"), None)
        if model_check:
            self._state.update_installed_models(model_check.details.get("present", []))

    # --- Future orchestration hooks (no-op / plan-only in this package) ---

    def plan_comfyui_install(self) -> dict[str, Any]:
        """Hook for ComfyUI install orchestration."""
        from core.comfyui.install_nodes import build_node_install_plan
        from core.comfyui.install_models import build_model_install_plan

        bundle = self.load_registries()
        return {
            "engine": "comfyui",
            "runtime_path": str(bundle.path("comfyui_runtime")),
            "nodes": [asdict(step) for step in build_node_install_plan(bundle)],
            "models": [asdict(step) for step in build_model_install_plan(bundle)],
        }

    def plan_a1111_install(self) -> dict[str, Any]:
        """Hook for A1111 install orchestration."""
        from core.a1111.install import build_install_plan

        bundle = self.load_registries()
        return build_install_plan(bundle)

    def extension_points(self) -> dict[str, Any]:
        """Documented hooks for future engines and deployment targets."""
        return {
            "model_families": ["sd15", "sdxl", "flux"],
            "engines": ["comfyui", "a1111"],
            "future_engines": ["inference_server", "docker", "windows_local", "linux_server"],
            "registry_driven": True,
            "notes": "Add manifests under configs/; extend RegistryBundle fields as needed.",
        }
