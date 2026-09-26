#!/usr/bin/env python3
"""IP-Adapter Plus Face SDXL (CLIP NON-FaceID) prototype — Package 4.12.3.

Bucket A crop. No InsightFace / FaceID / InstantID / antelope / buffalo.
No asset downloads in this module. Hash pin uses published upstream SHA256
where available; otherwise fail closed as UNVERIFIED / PENDING_FIRST_DOWNLOAD_PIN.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from .generation_evidence_ledger import file_sha256
from .identity_architecture_plugin import (
    ARCHITECTURE_IPADAPTER_PLUS_FACE,
    CANDIDATE_IPADAPTER_PLUS_FACE,
    FORBIDDEN_GRAPH_NODE_TYPES,
    evidence_metadata_for,
    reject_forbidden_dependencies,
)
from .identity_benchmark import (
    format_manual_asset_instructions,
    node_pin_status,
    normalize_scenario_id,
    verify_named_model_files,
    verify_named_nodes,
)
from .identity_face_crop_policy import (
    BUCKET_A_POLICY_ID,
    assert_no_insightface_crop_in_workflow,
    crop_face_bucket_a,
    validate_face_crop_policy,
)
from .prepared_workflow_index import (
    find_by_preparation_id,
    preparations_log_path,
)
from .seed_mode import generate_js_safe_seed, is_js_safe_seed

# Shared S1–S4 semantics with InstantID architecture benchmark (do not diverge).
from .identity_architecture_benchmark import (
    ARCHITECTURE_SCENARIO_PROMPTS,
    PREPARATION_KIND,
    BENCHMARK_CAPABILITY,
    SCENARIO_DIMENSIONS,
    IdentityArchitecturePrepResult,
    finalize_identity_architecture_benchmark_preparation,
    utc_now,
)

IPADAPTER_PLUS_NODE = "ComfyUI_IPAdapter_plus"
IPADAPTER_PLUS_PINNED_COMMIT = "a0f451a5113cf9becb0847b92884cb10cbdec0ef"

REQUIRED_MODEL_NAMES = (
    "sdxl_base",
    "ipadapter_plus_face_sdxl_vit_h",
    "clip_vision_vit_h_openclip",
)

REQUIRED_GRAPH_NODES = frozenset(
    {
        "LoadImage",
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "EmptyLatentImage",
        "CLIPVisionLoader",
        "IPAdapterModelLoader",
        "PrepImageForClipVision",
        "IPAdapterAdvanced",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    }
)

LIVE_NODE_TYPES = (
    "IPAdapterModelLoader",
    "CLIPVisionLoader",
    "IPAdapterAdvanced",
    "PrepImageForClipVision",
)

WORKFLOW_IDENTIFIER = "reference/identity_ipadapter_plus_face_sdxl_benchmark"
WORKFLOW_REL = Path(
    "workflows/reference/identity_ipadapter_plus_face_sdxl_benchmark/workflow.json"
)
MANIFEST_REL = Path(
    "workflows/reference/identity_ipadapter_plus_face_sdxl_benchmark/manifest.json"
)

LICENSE_REL = Path(
    "configs/benchmarks/identity_architecture_ipadapter_plus_face_licenses.json"
)

# LoadImage id used for face binding (mirrors InstantID face slot pattern).
FACE_LOAD_IMAGE_ID = "13"
LATENT_NODE_ID = "5"
SAVE_PREFIX = "ai_studio_idarch_ipadapter_plus_face"


def assert_ipadapter_plus_face_graph(workflow_data: dict[str, Any]) -> list[str]:
    """Structural graph checks for IP-Adapter Plus Face CLIP path."""
    errors: list[str] = []
    nodes = workflow_data.get("nodes") or []
    if not isinstance(nodes, list):
        return ["ERROR: Workflow nodes must be a list."]
    types = {str(node.get("type") or "") for node in nodes if isinstance(node, dict)}
    missing = sorted(REQUIRED_GRAPH_NODES - types)
    if missing:
        errors.append(
            "ERROR: IP-Adapter Plus Face workflow missing required nodes: "
            + ", ".join(missing)
        )

    forbidden_hits = sorted(types & FORBIDDEN_GRAPH_NODE_TYPES)
    if forbidden_hits:
        errors.append(
            "ERROR: Forbidden FaceID/InstantID/InsightFace nodes present: "
            + ", ".join(forbidden_hits)
        )
    errors.extend(assert_no_insightface_crop_in_workflow(workflow_data))

    # Reject FaceID-named widgets even on non-FaceID node types.
    for node in nodes:
        if not isinstance(node, dict):
            continue
        widgets = node.get("widgets_values") or []
        blob = " ".join(str(w) for w in widgets).lower()
        for token in ("faceid", "antelope", "buffalo", "insightface"):
            if token in blob:
                errors.append(
                    f"ERROR: Forbidden identity token {token!r} in node "
                    f"{node.get('type')} widgets."
                )

    load_image = next(
        (
            n
            for n in nodes
            if isinstance(n, dict)
            and n.get("type") == "LoadImage"
            and str(n.get("id")) == FACE_LOAD_IMAGE_ID
        ),
        None,
    )
    if load_image is None:
        errors.append(
            f"ERROR: LoadImage node id={FACE_LOAD_IMAGE_ID} is required for face reference."
        )
    else:
        widgets = load_image.get("widgets_values") or []
        if not widgets or not str(widgets[0]).strip():
            errors.append(
                f"ERROR: LoadImage id={FACE_LOAD_IMAGE_ID} face filename is not bound."
            )

    apply_node = next(
        (
            n
            for n in nodes
            if isinstance(n, dict) and n.get("type") == "IPAdapterAdvanced"
        ),
        None,
    )
    if apply_node is not None:
        inputs = {
            str(i.get("name") or ""): i
            for i in (apply_node.get("inputs") or [])
            if isinstance(i, dict)
        }
        for required_input in ("model", "ipadapter", "image", "clip_vision"):
            row = inputs.get(required_input)
            if row is None or row.get("link") is None:
                errors.append(
                    f"ERROR: IPAdapterAdvanced {required_input} is not bound."
                )

    latent = next(
        (
            n
            for n in nodes
            if isinstance(n, dict)
            and n.get("type") == "EmptyLatentImage"
            and str(n.get("id")) == LATENT_NODE_ID
        ),
        None,
    )
    if latent is None:
        errors.append(
            f"ERROR: EmptyLatentImage node id={LATENT_NODE_ID} is required for dimensions."
        )

    dep = reject_forbidden_dependencies(
        architecture_id=ARCHITECTURE_IPADAPTER_PLUS_FACE,
        workflow_data=workflow_data,
    )
    errors.extend(dep.get("errors") or [])
    return errors


def assess_ipadapter_plus_face_structural_readiness(
    *,
    bundle_models: list[dict[str, Any]],
    bundle_nodes: list[dict[str, Any]],
    comfyui_custom_nodes: Path | None,
) -> dict[str, Any]:
    _, missing_models = verify_named_model_files(
        bundle_models, list(REQUIRED_MODEL_NAMES)
    )
    _, missing_nodes = verify_named_nodes(
        bundle_nodes, [IPADAPTER_PLUS_NODE], comfyui_custom_nodes
    )
    node_row = node_pin_status(
        bundle_nodes,
        IPADAPTER_PLUS_NODE,
        comfyui_custom_nodes,
        required_node_types=tuple(LIVE_NODE_TYPES),
    )
    pin_ok = (
        bool(node_row.get("pin_match"))
        if node_row.get("pin_determinable")
        else bool(node_row.get("present"))
    )
    if node_row.get("pin_determinable") and not node_row.get("pin_match"):
        pin_ok = False

    forbidden = reject_forbidden_dependencies(
        architecture_id=ARCHITECTURE_IPADAPTER_PLUS_FACE,
        model_names=[str(m.get("name") or "") for m in bundle_models if isinstance(m, dict)],
    )
    # Structural readiness for *required* clean assets only — do not fail solely
    # because InstantID/FaceID models also exist in the shared registry.
    ready = (
        bool(node_row.get("present"))
        and pin_ok
        and not missing_models
        and not missing_nodes
    )
    return {
        "candidate": CANDIDATE_IPADAPTER_PLUS_FACE,
        "architecture": ARCHITECTURE_IPADAPTER_PLUS_FACE,
        "models_missing": missing_models,
        "nodes_missing": missing_nodes,
        "node_pin": node_row,
        "ready": ready,
        "forbidden_scan": forbidden,
        "face_crop_policy": BUCKET_A_POLICY_ID,
        "quality_claim": "none — structural registry/filesystem readiness only",
        "manual_instructions": format_manual_asset_instructions(
            bundle_models, missing_models
        ),
    }


def assess_ipadapter_plus_face_asset_readiness(
    *,
    drive_root: Path,
    bundle_models: list[dict[str, Any]],
    comfyui_runtime: Path | None = None,
) -> dict[str, Any]:
    """Fail closed unless each required asset has published/pinned SHA+size and verifies."""
    from .identity_benchmark import INTEGRITY_VERIFIED, verify_model_asset_integrity

    del drive_root, comfyui_runtime
    errors: list[str] = []
    assets: list[dict[str, Any]] = []
    by_name = {str(m.get("name") or ""): m for m in bundle_models if isinstance(m, dict)}

    for name in REQUIRED_MODEL_NAMES:
        row = dict(by_name.get(name) or {})
        row.setdefault("name", name)
        expected_sha = str(row.get("expected_sha256") or "").strip()
        expected_size = row.get("expected_size_bytes")
        runtime_path = str(row.get("runtime_path") or "").strip()
        verification_state = str(row.get("verification_state") or "").strip()
        pin_state = str(row.get("pin_state") or "").strip()
        entry: dict[str, Any] = {
            "name": name,
            "runtime_path": runtime_path,
            "filename": row.get("filename"),
            "source_url": row.get("source_url"),
            "revision": row.get("revision") or row.get("source_revision"),
            "license_notes": row.get("license_notes"),
            "verification_state": verification_state
            or (
                "HASH_DEFINED"
                if expected_sha and expected_size is not None
                else "PENDING_FIRST_DOWNLOAD_PIN"
            ),
            "pin_state": pin_state
            or (
                "PUBLISHED_UPSTREAM_SHA"
                if expected_sha
                else "PENDING_FIRST_DOWNLOAD_PIN"
            ),
            "integrity": None,
        }
        if (
            verification_state
            in {"UNVERIFIED_MANUAL_ASSET", "PENDING_FIRST_DOWNLOAD_PIN"}
            or not expected_sha
            or expected_size is None
        ):
            entry["verification_state"] = (
                verification_state
                if verification_state
                in {"UNVERIFIED_MANUAL_ASSET", "PENDING_FIRST_DOWNLOAD_PIN"}
                else "PENDING_FIRST_DOWNLOAD_PIN"
            )
            errors.append(
                f"ERROR: Asset {name} lacks expected_sha256/expected_size_bytes "
                f"({entry['verification_state']}) — live readiness fail closed "
                "(controlled first-download→hash→pin; no download in this checkpoint)."
            )
            assets.append(entry)
            continue

        # Reject FaceID / InsightFace filenames even if somehow aliased.
        fname = str(row.get("filename") or runtime_path).lower()
        for token in ("faceid", "insightface", "antelope", "buffalo", "instantid"):
            if token in fname:
                errors.append(
                    f"ERROR: Asset {name} filename/path contains forbidden token {token!r}."
                )
                assets.append(entry)
                break
        else:
            integrity = verify_model_asset_integrity(row)
            entry["integrity"] = integrity
            if integrity.get("status") != INTEGRITY_VERIFIED:
                # Missing file with defined hash → still fail closed (not ready).
                errors.append(
                    f"ERROR: IP-Adapter Plus Face asset integrity "
                    f"{integrity.get('status')} for {name}"
                )
            else:
                entry["verification_state"] = "VERIFIED"
            assets.append(entry)

    ready = not errors
    return {
        "ready": ready,
        "architecture": ARCHITECTURE_IPADAPTER_PLUS_FACE,
        "assets": assets,
        "errors": errors,
        "quality_claim": "none — hash/size verification only; no download performed",
    }


def assess_ipadapter_plus_face_license_gate(repo_root: Path) -> dict[str, Any]:
    """License gate for CLIP Plus Face path. SDXL base treated commercially OK for PATH C.

    promotion_allowed is always False for this architecture even when every
    non-FORBIDDEN component is ACCEPTABLE (no automatic production promote).
    """
    path = Path(repo_root) / LICENSE_REL
    default = {
        "architecture": ARCHITECTURE_IPADAPTER_PLUS_FACE,
        "components": {
            "ComfyUI_IPAdapter_plus_node": {
                "status": "REVIEW_REQUIRED",
                "notes": "cubiq/ComfyUI_IPAdapter_plus — confirm LICENSE at pinned commit.",
            },
            "ipadapter_plus_face_sdxl_vit_h": {
                "status": "REVIEW_REQUIRED",
                "notes": "h94/IP-Adapter Apache-2.0 weights — confirm terms before ACCEPTABLE.",
            },
            "clip_vision_vit_h_openclip": {
                "status": "REVIEW_REQUIRED",
                "notes": "OpenCLIP ViT-H encoder — confirm permissive terms before ACCEPTABLE.",
            },
            "sdxl_base": {
                "status": "ACCEPTABLE",
                "notes": (
                    "PATH C: SDXL base commercial use treated OK for this prototype path "
                    "(CreativeML Open RAIL++-M acknowledged; not InsightFace-blocked)."
                ),
            },
        },
        "overall_status": "REVIEW_REQUIRED",
        "promotion_allowed": False,
        "forbidden_components_absent": True,
        "license_ready": False,
    }
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("components"):
                components = data["components"]
                # Hard fail if InsightFace/FaceID/etc. appear as active dependencies
                # (FORBIDDEN entries are allowed to name the banned packages).
                # Strip "non-faceid" / "not-faceid" so explanatory exclusions do not trip.
                for cname, crow in components.items():
                    status = str((crow or {}).get("status") or "")
                    if status == "FORBIDDEN":
                        continue
                    fields = [
                        cname,
                        str((crow or {}).get("component") or ""),
                        str((crow or {}).get("source") or ""),
                        str((crow or {}).get("source_path") or ""),
                        str((crow or {}).get("source_repo") or ""),
                        str((crow or {}).get("filename") or ""),
                        str((crow or {}).get("upstream_origin") or ""),
                    ]
                    blob = " ".join(fields).lower()
                    for excl in (
                        "non-faceid",
                        "non_faceid",
                        "not-faceid",
                        "not_faceid",
                        "not faceid",
                    ):
                        blob = blob.replace(excl, " ")
                    for token in (
                        "insightface",
                        "antelope",
                        "buffalo",
                        "faceid",
                        "instantid",
                        "pulid",
                        "photomaker",
                        "flux.dev",
                        "flux_dev",
                    ):
                        if token in blob:
                            return {
                                "components": components,
                                "overall_status": "BLOCKED_FOR_COMMERCIAL",
                                "promotion_allowed": False,
                                "license_ready": False,
                                "architecture": ARCHITECTURE_IPADAPTER_PLUS_FACE,
                                "source": str(path),
                                "errors": [
                                    f"ERROR: Forbidden component token {token!r} in "
                                    f"IP-Adapter Plus Face license gate ({cname})."
                                ],
                            }
                statuses = [
                    str((v or {}).get("status") or "REVIEW_REQUIRED")
                    for v in components.values()
                    if isinstance(v, dict)
                    and str((v or {}).get("status")) != "FORBIDDEN"
                ]
                if any(s == "BLOCKED_FOR_COMMERCIAL" for s in statuses):
                    overall = "BLOCKED_FOR_COMMERCIAL"
                elif any(s in {"REVIEW_REQUIRED", "RESTRICTED"} for s in statuses):
                    overall = "REVIEW_REQUIRED"
                elif statuses and all(s == "ACCEPTABLE" for s in statuses):
                    overall = "ACCEPTABLE"
                else:
                    overall = "REVIEW_REQUIRED"
                # File may claim promotion_allowed; architecture policy overrides.
                file_promo = data.get("promotion_allowed")
                return {
                    "components": components,
                    "overall_status": overall,
                    "promotion_allowed": False,
                    "license_ready": overall == "ACCEPTABLE",
                    "architecture": ARCHITECTURE_IPADAPTER_PLUS_FACE,
                    "source": str(path),
                    "forbidden_components_absent": True,
                    "zero_paid_licensing": bool(data.get("zero_paid_licensing", True)),
                    "file_promotion_allowed_claim": file_promo,
                }
        except (OSError, json.JSONDecodeError):
            pass
    return {**default, "source": "defaults"}


def run_ipadapter_plus_face_preflight(
    repo_root: Path,
    bundle: Any,
    *,
    allow_missing_models: bool = False,
    allow_missing_nodes: bool = False,
    allow_unverified_assets: bool = False,
    base_url: str | None = None,
    require_live_comfy: bool = False,
    comfy_reachable_fn: Any = None,
    object_info_fn: Any = None,
    watcher_check_fn: Any = None,
    workflow_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Authoritative preflight for ipadapter_plus_face_sdxl.

    Sequence: architecture → nodes → structural → assets/hashes → licenses →
    no forbidden deps → (optional live) OutputWatcher → SDXL commercial OK.
    """
    from .comfyui_userdata import DEFAULT_COMFY_BASE_URL, comfyui_reachable
    from .identity_benchmark import _fetch_comfy_object_info
    from .runtime_health import HealthStatus, check_output_watcher

    steps: list[dict[str, Any]] = []
    errors: list[str] = []
    messages: list[str] = []
    warnings: list[str] = []

    steps.append(
        {
            "step": "architecture",
            "ok": True,
            "architecture_id": ARCHITECTURE_IPADAPTER_PLUS_FACE,
            "face_crop_policy": BUCKET_A_POLICY_ID,
        }
    )

    crop = validate_face_crop_policy(
        method="prep_image_for_clip_vision", backend="comfyui_ipadapter_plus"
    )
    steps.append({"step": "face_crop_policy", "ok": crop.ok, "detail": crop.to_dict()})
    if not crop.ok:
        errors.extend(crop.errors)

    drive_root = bundle.path("drive_root")
    comfy_runtime = bundle.path("comfyui_runtime")

    # Workflow structural (reference or provided)
    wf = workflow_data
    if wf is None:
        wf_path = Path(repo_root) / WORKFLOW_REL
        if wf_path.is_file():
            try:
                wf = json.loads(wf_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"ERROR: Unable to load IP-Adapter Plus Face workflow: {exc}")
                wf = None
        else:
            errors.append(f"ERROR: Reference workflow missing: {WORKFLOW_REL}")
    if wf is not None:
        graph_errors = assert_ipadapter_plus_face_graph(wf)
        steps.append(
            {
                "step": "workflow_structural",
                "ok": not graph_errors,
                "errors": graph_errors,
            }
        )
        errors.extend(graph_errors)
    else:
        steps.append({"step": "workflow_structural", "ok": False})

    structural = assess_ipadapter_plus_face_structural_readiness(
        bundle_models=list(bundle.models),
        bundle_nodes=list(bundle.nodes),
        comfyui_custom_nodes=Path(comfy_runtime) / "custom_nodes",
    )
    models_ok = (not structural.get("models_missing")) or allow_missing_models
    nodes_ok = (not structural.get("nodes_missing")) or allow_missing_nodes
    pin = structural.get("node_pin") or {}
    if structural.get("ready"):
        structural_ok = True
    else:
        structural_ok = models_ok and nodes_ok and (
            bool(pin.get("present")) or allow_missing_nodes
        )
        if allow_missing_models:
            warnings.append("WARN: allow_missing_models — investigation only.")
        if allow_missing_nodes:
            warnings.append("WARN: allow_missing_nodes — investigation only.")
    steps.append({"step": "structural", "ok": structural_ok, "detail": structural})
    if not structural_ok:
        errors.append(
            "ERROR: IP-Adapter Plus Face structural readiness failed "
            f"(models_missing={structural.get('models_missing')}; "
            f"nodes_missing={structural.get('nodes_missing')})."
        )

    assets = assess_ipadapter_plus_face_asset_readiness(
        drive_root=drive_root,
        bundle_models=list(bundle.models),
        comfyui_runtime=comfy_runtime,
    )
    assets_ok = bool(assets.get("ready")) or allow_unverified_assets
    if allow_unverified_assets and not assets.get("ready"):
        warnings.append(
            "WARN: allow_unverified_assets — hash gate overridden for investigation only."
        )
    steps.append({"step": "assets_hashes", "ok": assets_ok, "detail": assets})
    if not assets_ok:
        for err in assets.get("errors") or ["ERROR: Assets not verified."]:
            errors.append(str(err))

    license_gate = assess_ipadapter_plus_face_license_gate(repo_root)
    sdxl_ok = False
    sdxl_comp = (license_gate.get("components") or {}).get("sdxl_base") or {}
    sdxl_ok = str(sdxl_comp.get("status") or "") in {"ACCEPTABLE", "RESTRICTED"}
    # PATH C: SDXL commercial OK means ACCEPTABLE (or explicit commercially_ok flag).
    sdxl_commercial_ok = str(sdxl_comp.get("status") or "") == "ACCEPTABLE" or bool(
        sdxl_comp.get("commercially_ok")
    )
    license_ok = (
        str(license_gate.get("overall_status")) != "BLOCKED_FOR_COMMERCIAL"
        and sdxl_commercial_ok
        and not (license_gate.get("errors") or [])
    )
    # Unresolved REVIEW_REQUIRED still fails closed for authoritative preflight.
    if str(license_gate.get("overall_status")) == "REVIEW_REQUIRED":
        license_ok = False
        errors.append(
            "ERROR: IP-Adapter Plus Face license gate unresolved "
            f"(status={license_gate.get('overall_status')}); fail closed."
        )
    if not sdxl_commercial_ok:
        errors.append("ERROR: SDXL base commercial OK requirement not met for PATH C.")
    if license_gate.get("errors"):
        errors.extend(str(e) for e in license_gate["errors"])
    steps.append(
        {
            "step": "licenses",
            "ok": license_ok,
            "detail": license_gate,
            "sdxl_commercial_ok": sdxl_commercial_ok,
            "promotion_allowed": bool(license_gate.get("promotion_allowed")),
        }
    )

    # Forbidden deps: scan required asset names + workflow (not entire registry).
    forbidden = reject_forbidden_dependencies(
        architecture_id=ARCHITECTURE_IPADAPTER_PLUS_FACE,
        model_names=list(REQUIRED_MODEL_NAMES),
        workflow_data=wf,
    )
    steps.append({"step": "no_forbidden_deps", "ok": forbidden["ok"], "detail": forbidden})
    if not forbidden["ok"]:
        errors.extend(forbidden.get("errors") or [])

    base = base_url or DEFAULT_COMFY_BASE_URL
    if require_live_comfy:
        reachable_fn = comfy_reachable_fn or comfyui_reachable
        reachable = bool(reachable_fn(base))
        steps.append({"step": "comfyui_reachable", "ok": reachable, "base_url": base})
        if not reachable:
            errors.append(f"ERROR: ComfyUI is not reachable at {base}.")
        else:
            fetch = object_info_fn or _fetch_comfy_object_info
            oi_status, oi_payload, oi_notes, _ = fetch(base)
            keys = set(oi_payload.keys()) if isinstance(oi_payload, dict) else set()
            missing_live = [t for t in LIVE_NODE_TYPES if t not in keys]
            live_ok = oi_status == "ok" and not missing_live
            steps.append(
                {
                    "step": "live_nodes",
                    "ok": live_ok,
                    "object_info_status": oi_status,
                    "notes": oi_notes,
                    "missing": missing_live,
                }
            )
            if not live_ok:
                errors.append(
                    "ERROR: Required IP-Adapter Plus Face node types not live: "
                    + ", ".join(missing_live or [oi_status])
                )

        watcher_fn = watcher_check_fn or check_output_watcher
        watcher = watcher_fn(bundle)
        watcher_status = getattr(watcher, "status", None)
        ownership = str((getattr(watcher, "details", {}) or {}).get("ownership_state") or "")
        watcher_ok = watcher_status == HealthStatus.OK or (
            watcher_status == HealthStatus.WARN and ownership == "current_runtime"
        )
        steps.append(
            {
                "step": "output_watcher",
                "ok": watcher_ok,
                "status": str(
                    watcher_status.value if hasattr(watcher_status, "value") else watcher_status
                ),
                "ownership_state": ownership,
            }
        )
        if not watcher_ok:
            errors.append("ERROR: OutputWatcher is not healthy for the current runtime.")
    else:
        steps.append(
            {
                "step": "comfyui_reachable",
                "ok": True,
                "skipped": True,
                "notes": "offline/code preflight — live ComfyUI not required",
            }
        )
        steps.append(
            {
                "step": "output_watcher",
                "ok": True,
                "skipped": True,
                "notes": "offline/code preflight — OutputWatcher checked when live",
            }
        )
        messages.append(
            "Live ComfyUI/OutputWatcher checks deferred (require_live_comfy=false)."
        )

    ok = not errors
    return {
        "ok": ok,
        "architecture_id": ARCHITECTURE_IPADAPTER_PLUS_FACE,
        "steps": steps,
        "errors": errors,
        "messages": messages,
        "warnings": warnings,
        "license_gate": license_gate,
        "sdxl_commercial_ok": sdxl_commercial_ok,
        "preflight_sequence": [
            "architecture",
            "face_crop_policy",
            "workflow_structural",
            "structural",
            "assets_hashes",
            "licenses",
            "no_forbidden_deps",
            "comfyui_reachable",
            "output_watcher",
        ],
    }


def prepare_ipadapter_plus_face_benchmark(
    repo_root: Path,
    *,
    drive_root: Path,
    scenario: str,
    character_id: str,
    runtime_prepared_root: Path,
    comfyui_input_dir: Path,
    bundle_models: list[dict[str, Any]],
    bundle_nodes: list[dict[str, Any]],
    comfyui_custom_nodes: Path | None = None,
    drive_prepared_root: Path | None = None,
    seed: int | None = None,
    require_models: bool = True,
    require_nodes: bool = True,
    dry_run: bool = False,
    allow_benchmark: bool = False,
    face_crop_method: str = "prep_image_for_clip_vision",
) -> IdentityArchitecturePrepResult:
    """Prepare IP-Adapter Plus Face benchmark workflow (plumbing only)."""
    from .character_identity import (
        load_character,
        resolve_primary_face_path,
        verify_character_face,
    )
    from .workflow_parameters import apply_parameter_bindings
    from .workflow_provenance import hash_ui_workflow

    result = IdentityArchitecturePrepResult(
        ok=False,
        candidate=CANDIDATE_IPADAPTER_PLUS_FACE,
        scenario=scenario,
        character_id=character_id,
        dry_run=dry_run,
    )
    if not allow_benchmark:
        result.errors.append(
            "ERROR: IP-Adapter Plus Face preparation requires --allow-benchmark."
        )
        return result

    crop_policy = validate_face_crop_policy(
        method=face_crop_method, backend="comfyui_ipadapter_plus"
    )
    if not crop_policy.ok:
        result.errors.extend(crop_policy.errors)
        return result

    canonical_scenario = normalize_scenario_id(scenario)
    if canonical_scenario is None:
        from .identity_benchmark import SCENARIO_IDS

        result.errors.append(
            f"ERROR: Unknown scenario: {scenario}. Use one of: {', '.join(SCENARIO_IDS)}"
        )
        return result
    scenario = canonical_scenario
    result.scenario = scenario

    record = load_character(drive_root, character_id)
    if record is None:
        result.errors.append(f"ERROR: Character not found: {character_id}")
        return result
    ok, err = verify_character_face(drive_root, record)
    if not ok:
        result.errors.append(err)
        return result
    face_path = resolve_primary_face_path(drive_root, record)
    assert face_path is not None

    _, missing_models = verify_named_model_files(
        bundle_models, list(REQUIRED_MODEL_NAMES)
    )
    _, missing_nodes = verify_named_nodes(
        bundle_nodes, [IPADAPTER_PLUS_NODE], comfyui_custom_nodes
    )
    result.missing_models = missing_models
    result.missing_nodes = missing_nodes
    if require_models and missing_models:
        result.errors.append(
            "ERROR: Required IP-Adapter Plus Face model files missing (no auto-download): "
            + ", ".join(missing_models)
        )
        result.errors.extend(
            format_manual_asset_instructions(bundle_models, missing_models)
        )
    if require_nodes and missing_nodes:
        result.errors.append(
            "ERROR: Required custom node missing: " + ", ".join(missing_nodes)
        )
        result.errors.append(
            f"Install via Full Launch; pin {IPADAPTER_PLUS_NODE} @ "
            f"{IPADAPTER_PLUS_PINNED_COMMIT}."
        )
    if result.errors:
        return result

    workflow_src = Path(repo_root) / WORKFLOW_REL
    if not workflow_src.is_file():
        result.errors.append(f"ERROR: Benchmark workflow missing: {WORKFLOW_REL}")
        return result
    try:
        workflow_data = json.loads(workflow_src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.errors.append(f"ERROR: Invalid workflow JSON: {exc}")
        return result
    graph_errors = assert_ipadapter_plus_face_graph(workflow_data)
    if graph_errors:
        result.errors.extend(graph_errors)
        return result

    manifest_path = Path(repo_root) / MANIFEST_REL
    if not manifest_path.is_file():
        result.errors.append("ERROR: Benchmark manifest missing.")
        return result
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = manifest.get("parameter_schema") or {}

    if seed is None:
        seed = generate_js_safe_seed()
    if not is_js_safe_seed(seed):
        result.errors.append(
            "ERROR: Seed must be between 0 and 9007199254740991."
        )
        return result

    width, height = SCENARIO_DIMENSIONS[scenario]
    result.width = width
    result.height = height
    preparation_id = f"prep_{uuid.uuid4()}"
    result.preparation_id = preparation_id
    result.workflow_identifier = WORKFLOW_IDENTIFIER
    result.seed = int(seed)
    result.positive_prompt = ARCHITECTURE_SCENARIO_PROMPTS[scenario]
    result.staged_face_filename = f"ai_studio_idarch_{record.character_id[-8:]}_face.png"

    if dry_run:
        result.ok = True
        result.messages.append(
            "Dry run: IP-Adapter Plus Face benchmark preparation would be created."
        )
        result.warnings.append(
            "Prepare/open alone does not quality-benchmark IP-Adapter Plus Face."
        )
        return result

    prepared_dir = Path(runtime_prepared_root) / preparation_id
    prepared_dir.mkdir(parents=True, exist_ok=False)
    archive_dir = prepared_dir / "benchmark_source"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_face = archive_dir / "primary_face.png"
    crop_result = crop_face_bucket_a(
        face_path,
        archived_face,
        method=face_crop_method,
        backend="comfyui_ipadapter_plus",
    )
    if not crop_result.ok:
        shutil.rmtree(prepared_dir, ignore_errors=True)
        result.errors.extend(crop_result.errors)
        return result
    result.messages.extend(crop_result.messages)

    comfyui_input_dir = Path(comfyui_input_dir)
    comfyui_input_dir.mkdir(parents=True, exist_ok=True)
    staged = comfyui_input_dir / result.staged_face_filename
    shutil.copy2(archived_face, staged)

    params = {
        "input_image": result.staged_face_filename,
        "positive_prompt": result.positive_prompt,
        "seed": int(seed),
        "seed_mode": "fixed",
        "width": width,
        "height": height,
        "save_prefix": SAVE_PREFIX,
    }
    bound = apply_parameter_bindings(workflow_data, schema, params)
    for node in bound.get("nodes") or []:
        if (
            isinstance(node, dict)
            and node.get("type") == "LoadImage"
            and str(node.get("id")) == FACE_LOAD_IMAGE_ID
        ):
            widgets = list(node.get("widgets_values") or ["", "image"])
            widgets[0] = result.staged_face_filename
            if len(widgets) < 2:
                widgets.append("image")
            node["widgets_values"] = widgets
    bind_errors = assert_ipadapter_plus_face_graph(bound)
    if bind_errors:
        shutil.rmtree(prepared_dir, ignore_errors=True)
        result.errors.extend(bind_errors)
        return result

    arch_meta = evidence_metadata_for(
        ARCHITECTURE_IPADAPTER_PLUS_FACE,
        preparation_id=preparation_id,
        preparation_kind=PREPARATION_KIND,
        benchmark_run=True,
        benchmark_acknowledged=True,
        capability=BENCHMARK_CAPABILITY,
        scenario=scenario,
        character_id=record.character_id,
        workflow_identifier=result.workflow_identifier,
        promotion_status="pending",
        seed=int(seed),
        seed_mode="fixed",
        character_face_sha256=file_sha256(archived_face),
        character_reference_path="benchmark_source/primary_face.png",
        face_crop_policy=BUCKET_A_POLICY_ID,
        face_crop_method=face_crop_method,
    )
    bound.setdefault("extra", {})
    if not isinstance(bound.get("extra"), dict):
        bound["extra"] = {}
    bound["extra"]["ai_studio"] = {
        **arch_meta,
        "prepared_workflow_hash": "",
        "canonical_workflow_hash": "",
    }

    workflow_dest = prepared_dir / f"{preparation_id}.workflow.json"
    prepared_hash = hash_ui_workflow(bound)
    canonical_hash = hash_ui_workflow(workflow_data)
    bound["extra"]["ai_studio"]["prepared_workflow_hash"] = prepared_hash
    bound["extra"]["ai_studio"]["canonical_workflow_hash"] = canonical_hash
    workflow_dest.write_text(
        json.dumps(bound, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    created_ts = utc_now()
    from .identity_architecture_benchmark import _drive_prepared_root

    drive_root_prepared = drive_prepared_root or _drive_prepared_root(drive_root)
    drive_dir = drive_root_prepared / preparation_id
    metadata = {
        "schema_version": 1,
        "preparation_id": preparation_id,
        "preparation_kind": PREPARATION_KIND,
        "created_timestamp": created_ts,
        "created_at": created_ts,
        "benchmark_run": True,
        "benchmark_acknowledged": True,
        "capability": BENCHMARK_CAPABILITY,
        **evidence_metadata_for(
            ARCHITECTURE_IPADAPTER_PLUS_FACE,
            scenario=scenario,
            character_id=record.character_id,
            workflow_identifier=result.workflow_identifier,
            prepared_workflow_hash=prepared_hash,
            canonical_workflow_hash=canonical_hash,
            face_crop_policy=BUCKET_A_POLICY_ID,
            face_crop_method=face_crop_method,
        ),
        "prepared_runtime_path": str(prepared_dir),
        "prepared_drive_path": str(drive_dir),
        "parameters": params,
        "character_face_sha256": file_sha256(archived_face),
        "character_face_archived_path": "benchmark_source/primary_face.png",
        "license_notes": [
            "IP-Adapter Plus Face CLIP path — no InsightFace/FaceID.",
            "No auto-download of weights in this checkpoint.",
        ],
        "quality_claim": "none — prepare/open is plumbing only",
        "graph_readiness": "structural_only",
    }
    (prepared_dir / f"{preparation_id}.metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result.prepared_dir = str(prepared_dir)
    result.runtime_prepared_dir = str(prepared_dir)
    result.prepared_workflow_hash = prepared_hash
    result.canonical_workflow_hash = canonical_hash

    finalize_messages, finalize_errors = finalize_identity_architecture_benchmark_preparation(
        drive_root=drive_root,
        preparation_id=preparation_id,
        runtime_prepared_dir=prepared_dir,
        drive_prepared_root=drive_root_prepared,
        metadata=metadata,
        workflow_identifier=result.workflow_identifier,
        scenario=scenario,
        character_id=record.character_id,
        prepared_workflow_hash=prepared_hash,
        canonical_workflow_hash=canonical_hash,
        seed=int(seed),
        positive_prompt=result.positive_prompt,
        width=width,
        height=height,
    )
    result.messages.extend(finalize_messages)
    if finalize_errors:
        shutil.rmtree(prepared_dir, ignore_errors=True)
        if drive_dir.is_dir():
            shutil.rmtree(drive_dir, ignore_errors=True)
        result.errors.extend(finalize_errors)
        return result

    result.drive_prepared_dir = str(drive_dir)
    result.index_appended = (
        find_by_preparation_id(preparations_log_path(drive_root), preparation_id)
        is not None
    )
    result.ok = True
    result.messages.append(
        f"IP-Adapter Plus Face preparation created: {preparation_id}"
    )
    result.warnings.append(
        "CODE/SIM prepare/open does NOT mean IP-Adapter Plus Face passed visual QA."
    )
    return result
