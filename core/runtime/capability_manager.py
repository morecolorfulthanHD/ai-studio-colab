#!/usr/bin/env python3
"""Capability platform manager for AI Studio."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .asset_manager import AssetManager
from .node_registry_utils import evaluate_required_nodes
from .input_utils import list_eligible_inputs
from .output_evidence import inspect_generation_evidence
from .registry_loader import RegistryBundle, RegistryLoader, find_repo_root
from .workflow_validation import WORKFLOW_OUTPUT_PREFIXES, validate_workflow

CAPABILITY_REGISTRY_PATH = "configs/capabilities/capability_registry.json"

COMFYUI_RUNTIME_CAPABILITIES = frozenset({"txt2img", "img2img", "inpainting", "outpainting"})
EDITING_CAPABILITIES = frozenset({"img2img", "inpainting", "outpainting"})

CAPABILITY_WORKFLOW_ASSETS: dict[str, tuple[str, ...]] = {
    "txt2img": ("sd15_checkpoint", "workflow_base_txt2img"),
    "img2img": ("sd15_checkpoint", "workflow_base_img2img"),
    "inpainting": ("sd15_inpainting_checkpoint", "workflow_base_inpainting"),
    "outpainting": ("sd15_checkpoint", "workflow_base_outpainting"),
}

CAPABILITY_OUTPUT_PREFIXES: dict[str, str] = {
    "txt2img": WORKFLOW_OUTPUT_PREFIXES["base_txt2img"],
    "img2img": WORKFLOW_OUTPUT_PREFIXES["base_img2img"],
    "inpainting": WORKFLOW_OUTPUT_PREFIXES["base_inpainting"],
    "outpainting": WORKFLOW_OUTPUT_PREFIXES["base_outpainting"],
}

STATUS_RANK = {
    "ready": 0,
    "partial": 1,
    "unavailable": 2,
    "blocked": 3,
}


@dataclass
class CapabilityEvaluation:
    id: str
    name: str
    category: str
    maturity: str
    registry_status: str
    computed_status: str
    blocked: bool
    reasons: list[str] = field(default_factory=list)
    missing_models: list[str] = field(default_factory=list)
    missing_nodes: list[str] = field(default_factory=list)
    uninstalled_nodes: list[str] = field(default_factory=list)
    missing_assets: list[str] = field(default_factory=list)
    missing_workflows: list[str] = field(default_factory=list)
    missing_dependencies: list[str] = field(default_factory=list)
    supported_engines: list[str] = field(default_factory=list)
    evidence_status: str = "not_evaluated"
    evidence_details: dict[str, Any] = field(default_factory=dict)
    execution_input_status: str = "not_applicable"
    execution_input_details: dict[str, Any] = field(default_factory=dict)
    runtime_checks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilitySummary:
    total: int = 0
    ready: int = 0
    partial: int = 0
    unavailable: int = 0
    blocked: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_maturity: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapabilityManager:
    """Evaluate capability readiness from registry dependencies."""

    def __init__(self, bundle: RegistryBundle | None = None, repo_root: Path | None = None) -> None:
        if bundle is not None:
            self.bundle = bundle
            self.repo_root = bundle.repo_root
        else:
            self.repo_root = (repo_root or find_repo_root()).resolve()
            self.bundle = RegistryLoader(self.repo_root).load_all()

        manifest = self.bundle.get_manifest(CAPABILITY_REGISTRY_PATH)
        capabilities = manifest.get("capabilities", [])
        if not isinstance(capabilities, list):
            raise ValueError(f"{CAPABILITY_REGISTRY_PATH}: 'capabilities' must be a list")
        self.capabilities: list[dict[str, Any]] = capabilities
        self._capability_ids = {c["id"] for c in self.capabilities}
        self.asset_manager = AssetManager(bundle=self.bundle)
        self._asset_map = {a.id: a for a in self.asset_manager.assets}
        self._model_ids = {m["name"] for m in self.bundle.models}
        self._node_ids = {n["name"] for n in self.bundle.nodes}
        self._workflow_ids = {w["id"] for w in self.bundle.workflows}
        self._eval_cache: dict[str, CapabilityEvaluation] = {}
        self._custom_nodes_dir = self.bundle.path("comfyui_runtime") / "custom_nodes"

    def _implementation_status(self, cap: dict[str, Any]) -> str:
        return cap.get("implementation_status", "planned")

    def _is_implemented(self, cap: dict[str, Any]) -> bool:
        return self._implementation_status(cap) == "implemented"

    def _evaluate_required_nodes(self, cap: dict[str, Any]) -> tuple[list[str], list[str]]:
        node_status = evaluate_required_nodes(
            list(cap.get("required_nodes", [])),
            self.bundle.nodes,
            self._custom_nodes_dir,
        )
        return node_status["missing_registration"], node_status["uninstalled"]

    def _asset_is_satisfied(self, asset_id: str) -> bool:
        """Registration-level asset check (planned assets count as registered)."""
        asset = self._asset_map.get(asset_id)
        if not asset:
            return False
        if asset.present:
            return True
        return asset.registry_status in {"planned", "external"}

    def _asset_ready(self, asset_id: str) -> bool:
        asset = self._asset_map.get(asset_id)
        if not asset:
            return False
        if asset.present:
            return True
        if asset.asset_type == "workflow" and asset.intended_path:
            repo_workflow = self.repo_root / asset.intended_path
            if repo_workflow.is_file():
                return True
        return asset.registry_status == "external"

    def _workflow_ready(self, workflow_id: str) -> tuple[bool, str | None]:
        workflow = next((w for w in self.bundle.workflows if w.get("id") == workflow_id), None)
        if not workflow:
            return False, f"Workflow registration missing: {workflow_id}"
        workflow_path = self.repo_root / workflow.get("path", "")
        validation = validate_workflow(workflow_id, workflow_path)
        if not validation.valid:
            reason = validation.reasons[0] if validation.reasons else f"Workflow validation failed: {workflow_id}"
            return False, reason
        return True, None

    def _comfyui_runtime_ready(self) -> tuple[bool, str | None]:
        runtime_path = self.bundle.path("comfyui_runtime")
        if not (runtime_path / ".git").is_dir():
            return False, "ComfyUI runtime is not a valid git repository."
        if not (runtime_path / "main.py").is_file():
            return False, "ComfyUI runtime is missing main.py."
        return True, None

    def _capability_runtime_checks(self, cap: dict[str, Any]) -> list[str]:
        issues: list[str] = []
        capability_id = cap.get("id", "")

        if capability_id in COMFYUI_RUNTIME_CAPABILITIES:
            comfy_ok, comfy_reason = self._comfyui_runtime_ready()
            if not comfy_ok and comfy_reason:
                issues.append(comfy_reason)

        for workflow_id in cap.get("required_workflows", []):
            ready, reason = self._workflow_ready(workflow_id)
            if not ready and reason:
                issues.append(reason)

        asset_ids = CAPABILITY_WORKFLOW_ASSETS.get(capability_id, ())
        for asset_id in asset_ids:
            if not self._asset_ready(asset_id):
                if capability_id == "inpainting" and asset_id == "sd15_inpainting_checkpoint":
                    issues.append("Dedicated SD1.5 inpainting checkpoint not found.")
                else:
                    issues.append(f"Required asset not ready: {asset_id}")

        return issues

    def _input_directories(self) -> tuple[Path, Path]:
        inputs_root = self.bundle.path("drive_inputs")
        return inputs_root / "images", inputs_root / "masks"

    def _evaluate_execution_input(self, cap: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        capability_id = cap.get("id", "")
        if capability_id not in EDITING_CAPABILITIES:
            return "not_applicable", {}

        images_dir, masks_dir = self._input_directories()
        images = list_eligible_inputs(images_dir)
        masks = list_eligible_inputs(masks_dir)
        details = {
            "images_dir": str(images_dir),
            "masks_dir": str(masks_dir),
            "available_images": [str(path) for path in images],
            "available_masks": [str(path) for path in masks],
        }

        if capability_id == "img2img":
            if images:
                return "available", details
            return "not_selected", details

        if capability_id == "inpainting":
            if images and masks:
                return "available", details
            if images and not masks:
                details["message"] = "Source image available; mask not selected."
                return "mask_not_selected", details
            return "not_selected", details

        if capability_id == "outpainting":
            if images:
                return "available", details
            return "not_selected", details

        return "not_applicable", details

    def _evaluate_generation_evidence(self, capability_id: str) -> tuple[str, dict[str, Any]]:
        output_prefix = CAPABILITY_OUTPUT_PREFIXES.get(capability_id)
        if output_prefix is None:
            return "not_evaluated", {}

        evidence = inspect_generation_evidence(
            self.bundle.path("comfyui_output"),
            self.bundle.path("drive_outputs"),
            output_prefix=output_prefix,
        )
        return evidence.evidence_status, evidence.to_dict()

    def _dependency_reason(self, dep_id: str, dep_status: str) -> str:
        if dep_status == "blocked":
            return f"Dependency blocked: {dep_id} is blocked"
        if dep_status == "unavailable":
            return f"Dependency blocked: {dep_id} is unavailable"
        if dep_status == "partial":
            return f"Dependency not ready: {dep_id} is partial"
        return ""

    def _merge_status(self, current: str, incoming: str) -> str:
        return current if STATUS_RANK[current] >= STATUS_RANK[incoming] else incoming

    def evaluate_capability(
        self,
        capability_id: str,
        visiting: frozenset[str] | None = None,
    ) -> CapabilityEvaluation:
        if capability_id in self._eval_cache:
            return self._eval_cache[capability_id]

        cap = next((c for c in self.capabilities if c["id"] == capability_id), None)
        if not cap:
            raise KeyError(f"Unknown capability: {capability_id}")

        active_visiting = visiting or frozenset()
        if capability_id in active_visiting:
            return CapabilityEvaluation(
                id=cap["id"],
                name=cap["name"],
                category=cap.get("category", "utility"),
                maturity=cap.get("maturity", "experimental"),
                registry_status=cap.get("status", "planned"),
                computed_status="blocked",
                blocked=True,
                reasons=[f"Circular dependency detected involving {capability_id}."],
                supported_engines=list(cap.get("supported_engines", [])),
            )

        next_visiting = active_visiting | {capability_id}

        missing_models = [m for m in cap.get("required_models", []) if m not in self._model_ids]
        missing_nodes, uninstalled_nodes = self._evaluate_required_nodes(cap)
        missing_assets = [a for a in cap.get("required_assets", []) if not self._asset_ready(a)]
        runtime_checks = self._capability_runtime_checks(cap)
        missing_workflows = [w for w in cap.get("required_workflows", []) if w not in self._workflow_ids]
        missing_dependencies = [
            d for d in cap.get("dependencies", []) if d not in self._capability_ids
        ]

        dependency_evaluations: list[CapabilityEvaluation] = []
        for dep_id in cap.get("dependencies", []):
            if dep_id in missing_dependencies:
                continue
            dependency_evaluations.append(self.evaluate_capability(dep_id, next_visiting))

        reasons: list[str] = []
        if cap.get("status") == "disabled":
            reasons.append("Capability disabled in registry.")
        if missing_models:
            reasons.append(f"Missing model registrations: {', '.join(missing_models)}")
        if missing_nodes:
            reasons.append(f"Missing node registrations: {', '.join(missing_nodes)}")
        for node_name in uninstalled_nodes:
            reasons.append(f"Required node not installed: {node_name}")
        if missing_assets:
            reasons.append(f"Missing required assets: {', '.join(missing_assets)}")
        if missing_workflows:
            reasons.append(f"Missing workflow registrations: {', '.join(missing_workflows)}")
        if missing_dependencies:
            reasons.append(f"Unknown dependencies: {', '.join(missing_dependencies)}")
        if runtime_checks:
            reasons.extend(runtime_checks)

        for dep_eval in dependency_evaluations:
            dep_reason = self._dependency_reason(dep_eval.id, dep_eval.computed_status)
            if dep_reason:
                reasons.append(dep_reason)

        dependency_blocked = any(
            dep.computed_status in {"blocked", "unavailable"} for dep in dependency_evaluations
        )
        dependency_partial = any(dep.computed_status == "partial" for dep in dependency_evaluations)

        blocked = bool(
            cap.get("status") == "disabled"
            or missing_dependencies
            or dependency_blocked
        )
        hard_missing = bool(missing_models or missing_nodes or missing_workflows)
        runtime_blocked = bool(runtime_checks or uninstalled_nodes)

        registry_status = cap.get("status", "planned")
        computed_status = "ready"
        if blocked:
            computed_status = "blocked"
        elif hard_missing:
            computed_status = "unavailable"
        elif missing_assets or dependency_partial or runtime_blocked:
            computed_status = "partial"
        elif registry_status == "disabled":
            computed_status = "blocked"
        else:
            computed_status = "ready"

        if computed_status == "ready" and not self._is_implemented(cap):
            computed_status = "partial"
            reasons.append(
                "Capability implementation_status is planned; runtime implementation is deferred."
            )

        execution_input_status, execution_input_details = self._evaluate_execution_input(cap)

        evidence_status, evidence_details = self._evaluate_generation_evidence(cap["id"])

        evaluation = CapabilityEvaluation(
            id=cap["id"],
            name=cap["name"],
            category=cap.get("category", "utility"),
            maturity=cap.get("maturity", "experimental"),
            registry_status=cap.get("status", "planned"),
            computed_status=computed_status,
            blocked=blocked,
            reasons=reasons,
            missing_models=missing_models,
            missing_nodes=missing_nodes,
            uninstalled_nodes=uninstalled_nodes,
            missing_assets=missing_assets,
            missing_workflows=missing_workflows,
            missing_dependencies=missing_dependencies,
            supported_engines=list(cap.get("supported_engines", [])),
            evidence_status=evidence_status,
            evidence_details=evidence_details,
            execution_input_status=execution_input_status,
            execution_input_details=execution_input_details,
            runtime_checks=runtime_checks,
        )
        self._eval_cache[capability_id] = evaluation
        return evaluation

    def evaluate_all(self) -> list[CapabilityEvaluation]:
        self._eval_cache.clear()
        return [self.evaluate_capability(c["id"]) for c in self.capabilities]

    def ready_capabilities(self) -> list[CapabilityEvaluation]:
        return [c for c in self.evaluate_all() if c.computed_status == "ready"]

    def unavailable_capabilities(self) -> list[CapabilityEvaluation]:
        return [c for c in self.evaluate_all() if c.computed_status in {"unavailable", "blocked"}]

    def dependency_graph(self) -> dict[str, list[str]]:
        return {c["id"]: list(c.get("dependencies", [])) for c in self.capabilities}

    def summary(self) -> CapabilitySummary:
        results = self.evaluate_all()
        summary = CapabilitySummary(total=len(results))
        for item in results:
            summary.by_category[item.category] = summary.by_category.get(item.category, 0) + 1
            summary.by_maturity[item.maturity] = summary.by_maturity.get(item.maturity, 0) + 1
            summary.by_status[item.computed_status] = summary.by_status.get(item.computed_status, 0) + 1
            if item.computed_status == "ready":
                summary.ready += 1
            elif item.computed_status == "partial":
                summary.partial += 1
            elif item.computed_status == "blocked":
                summary.blocked += 1
            else:
                summary.unavailable += 1
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary().to_dict(),
            "capabilities": [c.to_dict() for c in self.evaluate_all()],
            "dependency_graph": self.dependency_graph(),
        }

    def print_summary(self) -> None:
        summary = self.summary()
        print("AI Studio — Capability Summary")
        print("=" * 40)
        print(f"Total:        {summary.total}")
        print(f"Ready:        {summary.ready}")
        print(f"Partial:      {summary.partial}")
        print(f"Unavailable:  {summary.unavailable}")
        print(f"Blocked:      {summary.blocked}")
        print("\nBy category:")
        for key in sorted(summary.by_category):
            print(f"  {key}: {summary.by_category[key]}")


def main() -> int:
    manager = CapabilityManager()
    manager.print_summary()
    print("\nRESULT: OK — capability manager loaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
