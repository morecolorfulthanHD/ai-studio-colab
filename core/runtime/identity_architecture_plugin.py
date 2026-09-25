#!/usr/bin/env python3
"""Pluggable identity architecture registry (Package 4.12.3).

Identity investigation is no longer hard-coded solely to InstantID. Each
architecture declares assets, licenses, live nodes, structural readiness,
workflow identity, preflight, and durable-evidence tags.

Supported in this package:
  - instantid_sdxl (existing; remains BLOCKED_FOR_COMMERCIAL)
  - ipadapter_plus_face_sdxl (Bucket A CLIP NON-FaceID prototype)

PhotoMaker is intentionally not registered.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

PACKAGE_VERSION = "4.12.3"

ARCHITECTURE_INSTANTID = "instantid_sdxl"
ARCHITECTURE_IPADAPTER_PLUS_FACE = "ipadapter_plus_face_sdxl"

CANDIDATE_INSTANTID = "instantid_sdxl_benchmark"
CANDIDATE_IPADAPTER_PLUS_FACE = "ipadapter_plus_face_sdxl_benchmark"

STATUS_BLOCKED_FOR_COMMERCIAL = "BLOCKED_FOR_COMMERCIAL"
STATUS_PROTOTYPE = "PROTOTYPE"
STATUS_INVESTIGATION = "INVESTIGATION"
STATUS_REJECTED = "REJECTED_FOR_PRODUCTION_IDENTITY"

FORBIDDEN_IDENTITY_DEPS = frozenset(
    {
        "insightface",
        "insightface_antelopev2",
        "antelopev2",
        "buffalo_l",
        "buffalo",
        "faceid",
        "ipadapter_faceid",
        "ipadapter_faceid_plusv2_sd15",
        "ipadapter_faceid_plusv2_sd15_lora",
        "instantid_ip_adapter",
        "instantid_controlnet",
        "pulid",
        "photomaker_v2",
        "flux.dev",
        "flux_dev",
    }
)

FORBIDDEN_GRAPH_NODE_TYPES = frozenset(
    {
        "InstantIDModelLoader",
        "InstantIDFaceAnalysis",
        "ApplyInstantID",
        "ApplyInstantIDAdvanced",
        "IPAdapterFaceID",
        "IPAdapterUnifiedLoaderFaceID",
        "IPAdapterInsightFaceLoader",
        "InsightFaceLoader",
        "ReActorFaceSwap",
        "ReActorRestoreFace",
    }
)


@dataclass(frozen=True)
class IdentityArchitectureSpec:
    """Contract every identity architecture must satisfy."""

    architecture_id: str
    display_name: str
    candidate_id: str
    status: str
    package_version: str = PACKAGE_VERSION
    required_assets: tuple[str, ...] = ()
    license_requirements: tuple[str, ...] = ()
    live_node_requirements: tuple[str, ...] = ()
    required_custom_nodes: tuple[str, ...] = ()
    workflow_identifier: str = ""
    workflow_relpath: str = ""
    face_crop_policy: str = ""
    evidence_architecture_tag: str = ""
    promotion_allowed: bool = False
    production_menu_allowed: bool = False
    forbidden_dependencies: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    controlnet_pose_expression: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArchitectureReadiness:
    architecture_id: str
    ready: bool
    structural: dict[str, Any] = field(default_factory=dict)
    assets: dict[str, Any] = field(default_factory=dict)
    licenses: dict[str, Any] = field(default_factory=dict)
    forbidden: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PreflightFn = Callable[..., dict[str, Any]]
GraphAssertFn = Callable[[dict[str, Any]], list[str]]
StructuralFn = Callable[..., dict[str, Any]]
AssetFn = Callable[..., dict[str, Any]]
LicenseFn = Callable[[Path], dict[str, Any]]


@dataclass
class IdentityArchitecturePlugin:
    spec: IdentityArchitectureSpec
    assert_graph: GraphAssertFn | None = None
    assess_structural: StructuralFn | None = None
    assess_assets: AssetFn | None = None
    assess_licenses: LicenseFn | None = None
    run_preflight: PreflightFn | None = None

    @property
    def architecture_id(self) -> str:
        return self.spec.architecture_id


_REGISTRY: dict[str, IdentityArchitecturePlugin] = {}
_BOOTSTRAPPED = False


def _build_instantid_spec() -> IdentityArchitectureSpec:
    return IdentityArchitectureSpec(
        architecture_id=ARCHITECTURE_INSTANTID,
        display_name="InstantID SDXL",
        candidate_id=CANDIDATE_INSTANTID,
        status=STATUS_BLOCKED_FOR_COMMERCIAL,
        required_assets=(
            "sdxl_base",
            "instantid_ip_adapter",
            "instantid_controlnet",
            "insightface_antelopev2",
        ),
        license_requirements=(
            "ComfyUI_InstantID_node",
            "InstantID_model_weights",
            "insightface_antelopev2",
            "sdxl_base",
        ),
        live_node_requirements=(
            "InstantIDModelLoader",
            "InstantIDFaceAnalysis",
            "ApplyInstantIDAdvanced",
        ),
        required_custom_nodes=("ComfyUI_InstantID",),
        workflow_identifier="reference/identity_instantid_sdxl_benchmark",
        workflow_relpath="workflows/reference/identity_instantid_sdxl_benchmark/workflow.json",
        face_crop_policy="insightface_antelopev2_blocked_for_commercial",
        evidence_architecture_tag=ARCHITECTURE_INSTANTID,
        promotion_allowed=False,
        production_menu_allowed=False,
        forbidden_dependencies=(),
        notes=(
            "Existing InstantID path preserved; InsightFace antelopev2 keeps "
            "overall_status=BLOCKED_FOR_COMMERCIAL and promotion_allowed=false.",
            "Characters option 11 remains blocked while InstantID is commercially blocked.",
        ),
        controlnet_pose_expression={
            "status": "bundled_with_instantid",
            "notes": "InstantID ControlNet keypoints — not reusable for IP-Adapter Plus Face.",
        },
    )


def _build_ipadapter_plus_face_spec() -> IdentityArchitectureSpec:
    return IdentityArchitectureSpec(
        architecture_id=ARCHITECTURE_IPADAPTER_PLUS_FACE,
        display_name="IP-Adapter Plus Face SDXL (CLIP NON-FaceID)",
        candidate_id=CANDIDATE_IPADAPTER_PLUS_FACE,
        status=STATUS_PROTOTYPE,
        required_assets=(
            "sdxl_base",
            "ipadapter_plus_face_sdxl_vit_h",
            "clip_vision_vit_h_openclip",
        ),
        license_requirements=(
            "ComfyUI_IPAdapter_plus_node",
            "ipadapter_plus_face_sdxl_vit_h",
            "clip_vision_vit_h_openclip",
            "sdxl_base",
        ),
        live_node_requirements=(
            "IPAdapterModelLoader",
            "CLIPVisionLoader",
            "IPAdapterAdvanced",
            "PrepImageForClipVision",
        ),
        required_custom_nodes=("ComfyUI_IPAdapter_plus",),
        workflow_identifier="reference/identity_ipadapter_plus_face_sdxl_benchmark",
        workflow_relpath=(
            "workflows/reference/identity_ipadapter_plus_face_sdxl_benchmark/workflow.json"
        ),
        face_crop_policy="bucket_a_deterministic_opencv_or_prepimage",
        evidence_architecture_tag=ARCHITECTURE_IPADAPTER_PLUS_FACE,
        promotion_allowed=False,
        production_menu_allowed=False,
        forbidden_dependencies=tuple(sorted(FORBIDDEN_IDENTITY_DEPS)),
        notes=(
            "PATH C primary prototype: CLIP ViT-H Plus Face (NON-FaceID).",
            "Zero paid model/checkpoint licensing.",
            "PhotoMaker V1 deferred — not implemented in this checkpoint.",
            "ControlNet pose/expression is gated definition only (no download).",
            "No InstantID keypoint reuse.",
        ),
        controlnet_pose_expression={
            "status": "GATED_DEFINITION_ONLY",
            "required_for_scenarios": [
                "S2_head_angle_pose",
                "S3_expression_change",
            ],
            "download_allowed": False,
            "instantid_keypoint_reuse": False,
            "notes": (
                "Optional future ControlNet for pose/expression under Package 4.12.3. "
                "Not acquired in prototype foundation; fail closed if required without pin."
            ),
        },
    )


def _attach_implementations() -> None:
    """Lazy-bind assess/assert/preflight callables to avoid circular imports."""
    from . import identity_architecture_benchmark as iab
    from . import identity_architecture_ipadapter_plus_face as ipf

    instantid = _REGISTRY[ARCHITECTURE_INSTANTID]
    instantid.assert_graph = iab.assert_instantid_graph
    instantid.assess_structural = iab.assess_instantid_structural_readiness
    instantid.assess_assets = iab.assess_instantid_asset_readiness
    instantid.assess_licenses = iab.assess_instantid_license_gate
    instantid.run_preflight = None  # production InstantID preflight stays in production module

    ipadapter = _REGISTRY[ARCHITECTURE_IPADAPTER_PLUS_FACE]
    ipadapter.assert_graph = ipf.assert_ipadapter_plus_face_graph
    ipadapter.assess_structural = ipf.assess_ipadapter_plus_face_structural_readiness
    ipadapter.assess_assets = ipf.assess_ipadapter_plus_face_asset_readiness
    ipadapter.assess_licenses = ipf.assess_ipadapter_plus_face_license_gate
    ipadapter.run_preflight = ipf.run_ipadapter_plus_face_preflight


def bootstrap_architecture_registry() -> dict[str, IdentityArchitecturePlugin]:
    global _BOOTSTRAPPED
    if not _BOOTSTRAPPED:
        _REGISTRY[ARCHITECTURE_INSTANTID] = IdentityArchitecturePlugin(
            spec=_build_instantid_spec()
        )
        _REGISTRY[ARCHITECTURE_IPADAPTER_PLUS_FACE] = IdentityArchitecturePlugin(
            spec=_build_ipadapter_plus_face_spec()
        )
        _attach_implementations()
        _BOOTSTRAPPED = True
    return _REGISTRY


def list_architecture_ids() -> list[str]:
    bootstrap_architecture_registry()
    return sorted(_REGISTRY.keys())


def get_architecture(architecture_id: str) -> IdentityArchitecturePlugin:
    bootstrap_architecture_registry()
    key = str(architecture_id or "").strip()
    if key not in _REGISTRY:
        raise KeyError(
            f"Unknown identity architecture_id={key!r}. "
            f"Known: {', '.join(list_architecture_ids())}"
        )
    return _REGISTRY[key]


def get_architecture_spec(architecture_id: str) -> IdentityArchitectureSpec:
    return get_architecture(architecture_id).spec


def is_instantid_production_blocked(repo_root: Path | None = None) -> tuple[bool, dict[str, Any]]:
    """Fail-closed InstantID production / option 11 gate.

    Does not weaken license semantics — reads existing InstantID license gate.
    """
    from .identity_architecture_benchmark import assess_instantid_license_gate

    if repo_root is None:
        gate = {
            "overall_status": STATUS_BLOCKED_FOR_COMMERCIAL,
            "promotion_allowed": False,
            "source": "defaults_without_repo",
        }
    else:
        gate = assess_instantid_license_gate(Path(repo_root))
    blocked = (
        str(gate.get("overall_status") or "") == STATUS_BLOCKED_FOR_COMMERCIAL
        or not bool(gate.get("promotion_allowed"))
    )
    return blocked, gate


def reject_forbidden_dependencies(
    *,
    architecture_id: str,
    model_names: list[str] | tuple[str, ...] | None = None,
    node_types: list[str] | tuple[str, ...] | None = None,
    workflow_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed if InsightFace / FaceID / InstantID / antelope / buffalo leak into a clean path."""
    plugin = get_architecture(architecture_id)
    forbidden = set(plugin.spec.forbidden_dependencies) | set(FORBIDDEN_IDENTITY_DEPS)
    # InstantID architecture is allowed to declare its own InsightFace deps.
    if architecture_id == ARCHITECTURE_INSTANTID:
        forbidden = set()

    hits: list[str] = []
    for name in model_names or ():
        lowered = str(name or "").strip().lower()
        for token in forbidden:
            if token.lower() in lowered or lowered == token.lower():
                hits.append(f"model:{name}")
                break

    types: set[str] = set(str(t) for t in (node_types or ()))
    if isinstance(workflow_data, dict):
        for node in workflow_data.get("nodes") or []:
            if isinstance(node, dict):
                types.add(str(node.get("type") or ""))
    for t in types:
        if t in FORBIDDEN_GRAPH_NODE_TYPES and architecture_id != ARCHITECTURE_INSTANTID:
            hits.append(f"node:{t}")
        lowered = t.lower()
        if architecture_id != ARCHITECTURE_INSTANTID:
            for token in ("faceid", "insightface", "instantid", "antelope", "buffalo", "reactor"):
                if token in lowered:
                    hits.append(f"node:{t}")
                    break

    unique = sorted(set(hits))
    return {
        "ok": not unique,
        "architecture_id": architecture_id,
        "hits": unique,
        "errors": (
            [
                "ERROR: Forbidden identity dependency detected for "
                f"{architecture_id}: " + ", ".join(unique)
            ]
            if unique
            else []
        ),
    }


def evidence_metadata_for(architecture_id: str, **extra: Any) -> dict[str, Any]:
    """Architecture tag payload for durable evidence / ledger rows."""
    spec = get_architecture_spec(architecture_id)
    payload = {
        "architecture": spec.architecture_id,
        "architecture_id": spec.architecture_id,
        "evidence_architecture_tag": spec.evidence_architecture_tag,
        "candidate": spec.candidate_id,
        "package_version": spec.package_version,
        "display_name": spec.display_name,
        "status": spec.status,
        "promotion_allowed": spec.promotion_allowed,
        "face_crop_policy": spec.face_crop_policy,
    }
    payload.update(extra)
    return payload
