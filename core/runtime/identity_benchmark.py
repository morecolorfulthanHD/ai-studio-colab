#!/usr/bin/env python3
"""Identity-method benchmark ledger and preparation (Package 4.12).

Benchmark artifacts are separated from ordinary creative generation semantics.
No automatic method promotion. Human rubric only — no invented perceptual scores.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .character_identity import (
    CharacterRecord,
    load_character,
    resolve_primary_face_path,
    verify_character_face,
)
from .generation_evidence_ledger import file_sha256
from .seed_mode import generate_js_safe_seed, is_js_safe_seed

PACKAGE_VERSION = "4.12"
PREPARATION_KIND_IDENTITY_BENCHMARK = "identity_benchmark"
BENCHMARK_CAPABILITY = "identity_benchmark"

CANDIDATE_REACTOR = "reactor_faceswap_benchmark"
CANDIDATE_FACEID = "ipadapter_faceid_sd15_benchmark"
LIVE_CANDIDATES = (CANDIDATE_REACTOR, CANDIDATE_FACEID)
DEFERRED_CANDIDATES = ("instantid_sdxl_deferred",)

SCENARIO_IDS = (
    "S1_near_front_portrait",
    "S2_head_angle_pose",
    "S3_expression_change",
    "S4_wardrobe_environment",
)

HUMAN_REVIEW_RUBRIC = [
    "identity_recognizability",
    "pose_head_angle_tolerance",
    "expression_tolerance",
    "scene_composition_preservation",
    "visual_artifacts",
    "usability_repeatability",
    "runtime_resource_cost",
    "operational_complexity",
]

# Fail-closed markers that refuse ordinary variation/reproduction parenting.
BENCHMARK_WORKFLOW_IDENTIFIERS = frozenset(
    {
        "benchmark/identity_reactor",
        "benchmark/identity_faceid",
        "reference/identity_reactor_benchmark",
        "reference/identity_faceid_benchmark",
    }
)

# Exact FaceID SD1.5 asset choices (conservative, documented).
FACEID_REQUIRED_MODEL_NAMES = (
    "ipadapter_faceid_plusv2_sd15",
    "ipadapter_faceid_plusv2_sd15_lora",
    "clip_vision_sd15",
    "insightface",
)
REACTOR_REQUIRED_MODEL_NAMES = ("insightface", "reactor_inswapper_128")
FACEID_REQUIRED_NODE = "ComfyUI_IPAdapter_plus"
REACTOR_REQUIRED_NODE = "ComfyUI-ReActor"

REACTOR_REQUIRED_GRAPH_NODES = frozenset(
    {
        "LoadImage",
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "EmptyLatentImage",
        "KSampler",
        "VAEDecode",
        "ReActorFaceSwap",
        "SaveImage",
    }
)
FACEID_REQUIRED_GRAPH_NODES = frozenset(
    {
        "LoadImage",
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "EmptyLatentImage",
        "IPAdapterUnifiedLoaderFaceID",
        "IPAdapterFaceID",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    }
)

IPADAPTER_PINNED_COMMIT = "a0f451a5113cf9becb0847b92884cb10cbdec0ef"
REACTOR_PINNED_COMMIT = "6ad6b35a4df250d14cb2abf0808c9ffedf59f747"

SCENARIO_PROMPTS = {
    "S1_near_front_portrait": (
        "portrait photo of the same person, near-front facing, neutral expression, "
        "soft studio lighting, head and shoulders"
    ),
    "S2_head_angle_pose": (
        "portrait photo of the same person, head turned about 40 degrees to the right, "
        "three-quarter view, clear jawline, studio lighting"
    ),
    "S3_expression_change": (
        "portrait photo of the same person, genuine smile with visible teeth, "
        "near-front facing, soft daylight"
    ),
    "S4_wardrobe_environment": (
        "full scene photo of the same person wearing a red jacket outdoors in a city street, "
        "different framing from a studio portrait, natural daylight"
    ),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class IdentityBenchmarkRecord:
    candidate: str
    scenario: str
    character_id: str
    seed: Any = None
    preparation_id: str = ""
    output_path: str = ""
    output_sha256: str = ""
    success: bool | None = None
    execution_time_seconds: float | None = None
    peak_vram_mb: float | None = None
    human_review: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    promotion_status: str = "pending"
    package_version: str = PACKAGE_VERSION
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["human_review_rubric_keys"] = list(HUMAN_REVIEW_RUBRIC)
        return payload


def append_identity_benchmark_record(ledger_path: Path, record: IdentityBenchmarkRecord) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if not record.created_at:
        record.created_at = utc_now()
    line = json.dumps(record.to_dict(), ensure_ascii=False)
    tmp = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    existing = ledger_path.read_text(encoding="utf-8") if ledger_path.is_file() else ""
    tmp.write_text(existing + line + "\n", encoding="utf-8")
    tmp.replace(ledger_path)


def load_identity_benchmark_records(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def format_identity_benchmark_report(records: list[dict[str, Any]]) -> str:
    lines = [
        "AI Studio — Identity Method Benchmark Report",
        "=" * 40,
        f"Records: {len(records)}",
        "Note: human-review fields are qualitative; no automated perceptual scores.",
        "Note: CODE/SIM prepare/open does NOT mean a method was quality-benchmarked.",
        "Promotion requires explicit human selection (not automatic).",
        "",
    ]
    if not records:
        lines.append("No identity benchmark records found.")
        return "\n".join(lines)
    for row in records:
        lines.append(
            f"- {row.get('candidate')} / {row.get('scenario')} / "
            f"char={row.get('character_id')} / promotion={row.get('promotion_status')} / "
            f"success={row.get('success')}"
        )
    return "\n".join(lines)


def is_benchmark_generation_metadata(metadata: dict[str, Any] | None) -> bool:
    """True when a generation must not be an ordinary variation/reproduction parent."""
    if not isinstance(metadata, dict):
        return False
    if metadata.get("benchmark_run") is True:
        return True
    kind = str(metadata.get("preparation_kind") or "").strip()
    if kind == PREPARATION_KIND_IDENTITY_BENCHMARK:
        return True
    capability = str(metadata.get("capability") or "").strip()
    if capability in {BENCHMARK_CAPABILITY, CANDIDATE_REACTOR, CANDIDATE_FACEID}:
        return True
    if capability.endswith("_benchmark") and "identity" in capability:
        return True
    identifier = str(
        metadata.get("workflow_identifier")
        or metadata.get("canonical_workflow_identifier")
        or ""
    ).strip()
    if identifier in BENCHMARK_WORKFLOW_IDENTIFIERS:
        return True
    if "identity_" in identifier and "benchmark" in identifier:
        return True
    return False


BENCHMARK_PARENT_REFUSAL = (
    "ERROR: Identity-benchmark generations are not eligible as ordinary "
    "variation or reproduction parents."
)


@dataclass
class IdentityBenchmarkPrepResult:
    ok: bool
    candidate: str = ""
    scenario: str = ""
    character_id: str = ""
    preparation_id: str = ""
    prepared_dir: str = ""
    workflow_identifier: str = ""
    seed: int | None = None
    staged_face_filename: str = ""
    positive_prompt: str = ""
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_models: list[str] = field(default_factory=list)
    missing_nodes: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _candidate_workflow_relpath(candidate: str) -> str:
    if candidate == CANDIDATE_REACTOR:
        return "workflows/reference/identity_reactor_benchmark/workflow.json"
    if candidate == CANDIDATE_FACEID:
        return "workflows/reference/identity_faceid_benchmark/workflow.json"
    raise ValueError(f"Unknown identity benchmark candidate: {candidate}")


def _candidate_manifest_relpath(candidate: str) -> str:
    if candidate == CANDIDATE_REACTOR:
        return "workflows/reference/identity_reactor_benchmark/manifest.json"
    if candidate == CANDIDATE_FACEID:
        return "workflows/reference/identity_faceid_benchmark/manifest.json"
    raise ValueError(f"Unknown identity benchmark candidate: {candidate}")


def _candidate_workflow_identifier(candidate: str) -> str:
    if candidate == CANDIDATE_REACTOR:
        return "reference/identity_reactor_benchmark"
    if candidate == CANDIDATE_FACEID:
        return "reference/identity_faceid_benchmark"
    raise ValueError(f"Unknown identity benchmark candidate: {candidate}")


def _required_models_for_candidate(candidate: str) -> tuple[str, ...]:
    if candidate == CANDIDATE_REACTOR:
        return REACTOR_REQUIRED_MODEL_NAMES
    if candidate == CANDIDATE_FACEID:
        return FACEID_REQUIRED_MODEL_NAMES
    return ()


def _required_nodes_for_candidate(candidate: str) -> tuple[str, ...]:
    if candidate == CANDIDATE_REACTOR:
        return (REACTOR_REQUIRED_NODE,)
    if candidate == CANDIDATE_FACEID:
        return (FACEID_REQUIRED_NODE,)
    return ()


def _required_graph_nodes_for_candidate(candidate: str) -> frozenset[str]:
    if candidate == CANDIDATE_REACTOR:
        return REACTOR_REQUIRED_GRAPH_NODES
    if candidate == CANDIDATE_FACEID:
        return FACEID_REQUIRED_GRAPH_NODES
    return frozenset()


def assert_identity_benchmark_graph(workflow_data: dict[str, Any], candidate: str) -> list[str]:
    """Structural readiness checks only — never a visual/quality PASS."""
    errors: list[str] = []
    nodes = workflow_data.get("nodes") or []
    types = {str(node.get("type") or "") for node in nodes if isinstance(node, dict)}
    required = _required_graph_nodes_for_candidate(candidate)
    missing = sorted(required - types)
    if missing:
        errors.append(
            "ERROR: Benchmark workflow missing required candidate nodes: " + ", ".join(missing)
        )
    if candidate == CANDIDATE_REACTOR:
        reactor = next((n for n in nodes if isinstance(n, dict) and n.get("type") == "ReActorFaceSwap"), None)
        if reactor is not None:
            inputs = {str(i.get("name") or ""): i for i in (reactor.get("inputs") or []) if isinstance(i, dict)}
            if not inputs.get("source_image") or inputs["source_image"].get("link") is None:
                errors.append("ERROR: ReActorFaceSwap source_image is not bound.")
            if not inputs.get("input_image") or inputs["input_image"].get("link") is None:
                errors.append("ERROR: ReActorFaceSwap input_image is not bound.")
            widgets = reactor.get("widgets_values") or []
            if len(widgets) < 2 or str(widgets[1]) != "inswapper_128.onnx":
                errors.append("ERROR: ReActorFaceSwap must select inswapper_128.onnx.")
    if candidate == CANDIDATE_FACEID:
        loader = next(
            (n for n in nodes if isinstance(n, dict) and n.get("type") == "IPAdapterUnifiedLoaderFaceID"),
            None,
        )
        faceid = next(
            (n for n in nodes if isinstance(n, dict) and n.get("type") == "IPAdapterFaceID"),
            None,
        )
        if loader is not None:
            widgets = loader.get("widgets_values") or []
            if not widgets or str(widgets[0]) != "FACEID PLUS V2":
                errors.append("ERROR: IPAdapterUnifiedLoaderFaceID must use FACEID PLUS V2.")
        if faceid is not None:
            inputs = {str(i.get("name") or ""): i for i in (faceid.get("inputs") or []) if isinstance(i, dict)}
            if not inputs.get("image") or inputs["image"].get("link") is None:
                errors.append("ERROR: IPAdapterFaceID image input is not bound.")
            if not inputs.get("model") or inputs["model"].get("link") is None:
                errors.append("ERROR: IPAdapterFaceID model input is not bound.")
            if not inputs.get("ipadapter") or inputs["ipadapter"].get("link") is None:
                errors.append("ERROR: IPAdapterFaceID ipadapter input is not bound.")
    return errors


def verify_named_model_files(bundle_models: list[dict[str, Any]], names: list[str]) -> tuple[list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    by_name = {str(entry.get("name") or ""): entry for entry in bundle_models}
    for name in names:
        entry = by_name.get(name)
        if entry is None:
            missing.append(name)
            continue
        runtime = entry.get("runtime_path")
        if runtime and Path(str(runtime)).is_file():
            present.append(name)
        else:
            missing.append(name)
    return present, missing


def verify_named_nodes(
    bundle_nodes: list[dict[str, Any]],
    names: list[str],
    comfyui_custom_nodes: Path | None,
) -> tuple[list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    by_name = {str(entry.get("name") or ""): entry for entry in bundle_nodes}
    for name in names:
        entry = by_name.get(name)
        if entry is None:
            missing.append(name)
            continue
        folder = str(entry.get("folder_name") or name)
        if comfyui_custom_nodes is not None:
            node_dir = Path(comfyui_custom_nodes) / folder
            if not node_dir.is_dir():
                missing.append(name)
                continue
        present.append(name)
    return present, missing


def format_manual_asset_instructions(bundle_models: list[dict[str, Any]], missing_names: list[str]) -> list[str]:
    """Exact fail-closed instructions for restricted assets (no auto-download)."""
    by_name = {str(entry.get("name") or ""): entry for entry in bundle_models}
    lines: list[str] = []
    for name in missing_names:
        entry = by_name.get(name) or {}
        filename = str(entry.get("filename") or Path(str(entry.get("runtime_path") or "")).name or name)
        dest = str(entry.get("runtime_path") or "(unknown Drive destination)")
        source = str(entry.get("source_url") or entry.get("notes") or "Operator-obtained; review license")
        lines.append(
            f"MISSING {name}: obtain '{filename}' from {source}; place at {dest}; "
            "then re-run check_identity_benchmark_deps.py / prepare (AI Studio verifies "
            "presence via model_registry runtime_path)."
        )
    return lines


def _model_presence_map(
    bundle_models: list[dict[str, Any]], names: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    by_name = {str(entry.get("name") or ""): entry for entry in bundle_models}
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        entry = by_name.get(name) or {}
        runtime = str(entry.get("runtime_path") or "")
        present = bool(runtime and Path(runtime).is_file())
        out[name] = {
            "present": present,
            "runtime_path": runtime or None,
            "filename": str(entry.get("filename") or Path(runtime).name if runtime else name),
        }
    return out


def _scan_node_class_mappings(node_dir: Path) -> set[str]:
    """Best-effort scan for NODE_CLASS_MAPPINGS keys declared in custom-node sources."""
    found: set[str] = set()
    if not node_dir.is_dir():
        return found
    for path in node_dir.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "NODE_CLASS_MAPPINGS" not in text:
            continue
        # Lightweight extraction: quoted keys near mappings assignments.
        for match in re.finditer(r'["\']([A-Za-z0-9_]+)["\']\s*:', text):
            key = match.group(1)
            if key.startswith(("ReActor", "IPAdapter")):
                found.add(key)
    return found


def _fetch_comfy_object_info_keys(base_url: str | None = None) -> tuple[str, set[str] | None, str]:
    """Return (status, keys|None, notes). status: ok|unreachable|error."""
    try:
        from .comfyui_userdata import DEFAULT_COMFY_BASE_URL, comfyui_reachable, normalize_comfy_base_url
    except Exception:  # noqa: BLE001
        return "error", None, "comfyui helper import failed"
    base = normalize_comfy_base_url(base_url or DEFAULT_COMFY_BASE_URL)
    if not comfyui_reachable(base):
        return "unreachable", None, f"ComfyUI not reachable at {base}; registration not live-verified"
    try:
        import urllib.request

        with urllib.request.urlopen(f"{base.rstrip('/')}/object_info", timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if not isinstance(payload, dict):
            return "error", None, "object_info returned non-object"
        return "ok", set(payload.keys()), "object_info loaded"
    except Exception as exc:  # noqa: BLE001
        return "error", None, f"object_info fetch failed: {exc}"


def node_pin_status(
    bundle_nodes: list[dict[str, Any]],
    name: str,
    comfyui_custom_nodes: Path | None,
    *,
    required_node_types: tuple[str, ...] = (),
    object_info_keys: set[str] | None = None,
    object_info_status: str = "unchecked",
) -> dict[str, Any]:
    entry = next((n for n in bundle_nodes if str(n.get("name") or "") == name), None)
    payload: dict[str, Any] = {
        "name": name,
        "registered": entry is not None,
        "pinned_commit": (entry or {}).get("pinned_commit") or "",
        "repo_url": (entry or {}).get("repo_url") or "",
        "present": False,
        "current_commit": "",
        "pin_match": False,
        "pin_determinable": False,
        "source_declares_required_types": False,
        "declared_types_found": [],
        "registration_status": "unchecked",
        "registration_notes": "",
        "notes": "",
    }
    if entry is None or comfyui_custom_nodes is None:
        payload["registration_status"] = "missing"
        payload["registration_notes"] = "Node not registered or custom_nodes path unavailable."
        return payload
    folder = str(entry.get("folder_name") or name)
    node_dir = Path(comfyui_custom_nodes) / folder
    payload["present"] = node_dir.is_dir()
    if not payload["present"]:
        payload["notes"] = "Custom node folder missing after Full Reset until install_nodes runs."
        payload["registration_status"] = "missing"
        payload["registration_notes"] = "Filesystem folder absent."
        return payload

    declared = _scan_node_class_mappings(node_dir)
    if required_node_types:
        found_types = [t for t in required_node_types if t in declared]
        payload["declared_types_found"] = found_types
        payload["source_declares_required_types"] = len(found_types) == len(required_node_types)
        if not payload["source_declares_required_types"]:
            missing_decl = [t for t in required_node_types if t not in declared]
            payload["notes"] = (
                "Folder present but source scan did not find required NODE_CLASS_MAPPINGS keys: "
                + ", ".join(missing_decl)
            )

    git_dir = node_dir / ".git"
    if git_dir.exists():
        import subprocess

        completed = subprocess.run(
            ["git", "-C", str(node_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            head = (completed.stdout or "").strip()
            payload["current_commit"] = head
            payload["pin_determinable"] = True
            pinned = str(entry.get("pinned_commit") or "").strip()
            if pinned and (head.startswith(pinned) or pinned.startswith(head)):
                payload["pin_match"] = True
                payload["notes"] = (payload["notes"] + " " if payload["notes"] else "") + "Pinned commit matched."
            elif pinned:
                payload["pin_match"] = False
                payload["notes"] = (
                    (payload["notes"] + " " if payload["notes"] else "")
                    + f"Checkout present but not at pinned commit {pinned}."
                ).strip()
            else:
                payload["pin_match"] = True
                payload["notes"] = (payload["notes"] + " " if payload["notes"] else "") + "No pinned_commit in registry."
        else:
            payload["notes"] = (payload["notes"] + " " if payload["notes"] else "") + "Failed to read HEAD commit."
    else:
        payload["notes"] = (
            (payload["notes"] + " " if payload["notes"] else "")
            + "Present but not a git checkout; cannot verify pin."
        ).strip()

    # Live ComfyUI registration (preferred): folder present but missing object_info types = import/reg failure.
    if object_info_status == "ok" and object_info_keys is not None and required_node_types:
        missing_live = [t for t in required_node_types if t not in object_info_keys]
        if missing_live:
            payload["registration_status"] = "failed"
            payload["registration_notes"] = (
                "Custom node folder is present but ComfyUI object_info is missing required types "
                f"(import/registration failure): {', '.join(missing_live)}"
            )
        else:
            payload["registration_status"] = "ok"
            payload["registration_notes"] = "Required node types present in live ComfyUI object_info."
    elif object_info_status in {"unreachable", "error", "unchecked"}:
        if required_node_types and not payload["source_declares_required_types"]:
            payload["registration_status"] = "failed"
            payload["registration_notes"] = (
                "ComfyUI object_info unavailable; source scan did not declare required node types."
            )
        else:
            payload["registration_status"] = "unchecked"
            payload["registration_notes"] = (
                "ComfyUI object_info unavailable; filesystem/source checks only. "
                "Re-run after ComfyUI is up to verify import/registration."
            )
    return payload


def assess_identity_benchmark_dependencies(
    *,
    bundle_models: list[dict[str, Any]],
    bundle_nodes: list[dict[str, Any]],
    comfyui_custom_nodes: Path | None,
    candidate: str | None = None,
    comfyui_base_url: str | None = None,
) -> dict[str, Any]:
    candidates = [candidate] if candidate else list(LIVE_CANDIDATES)
    object_info_status, object_info_keys, object_info_notes = _fetch_comfy_object_info_keys(comfyui_base_url)

    reactor_node = node_pin_status(
        bundle_nodes,
        REACTOR_REQUIRED_NODE,
        comfyui_custom_nodes,
        required_node_types=("ReActorFaceSwap",),
        object_info_keys=object_info_keys,
        object_info_status=object_info_status,
    )
    faceid_node = node_pin_status(
        bundle_nodes,
        FACEID_REQUIRED_NODE,
        comfyui_custom_nodes,
        required_node_types=("IPAdapterUnifiedLoaderFaceID", "IPAdapterFaceID"),
        object_info_keys=object_info_keys,
        object_info_status=object_info_status,
    )

    report: dict[str, Any] = {
        "package_version": PACKAGE_VERSION,
        "quality_claim": "none — dependency readiness only; not a visual identity PASS",
        "comfyui_object_info": {
            "status": object_info_status,
            "notes": object_info_notes,
        },
        "nodes": {
            REACTOR_REQUIRED_NODE: reactor_node,
            FACEID_REQUIRED_NODE: faceid_node,
        },
        "candidates": {},
        "manual_instructions": [],
        "download_instructions_deferred": True,
        "download_instructions_note": (
            "Do not obtain manual assets until this live checker reports which items are missing."
        ),
    }

    all_missing: list[str] = []
    for cand in candidates:
        models = list(_required_models_for_candidate(cand))
        present_m, missing_m = verify_named_model_files(bundle_models, models)
        model_map = _model_presence_map(bundle_models, tuple(models))
        if cand == CANDIDATE_REACTOR:
            node_row = reactor_node
            detail = {
                "custom_node": REACTOR_REQUIRED_NODE,
                "custom_node_present": bool(node_row.get("present")),
                "pinned_revision_match": bool(node_row.get("pin_match")),
                "pinned_revision_determinable": bool(node_row.get("pin_determinable")),
                "pinned_commit": node_row.get("pinned_commit") or "",
                "current_commit": node_row.get("current_commit") or "",
                "registration_status": node_row.get("registration_status"),
                "registration_notes": node_row.get("registration_notes"),
                "w600k_r50_onnx": model_map.get("insightface", {}).get("present", False),
                "inswapper_128_onnx": model_map.get("reactor_inswapper_128", {}).get("present", False),
                "assets": {
                    "insightface_w600k_r50": model_map.get("insightface"),
                    "reactor_inswapper_128": model_map.get("reactor_inswapper_128"),
                },
            }
        else:
            node_row = faceid_node
            detail = {
                "custom_node": FACEID_REQUIRED_NODE,
                "custom_node_present": bool(node_row.get("present")),
                "pinned_revision_match": bool(node_row.get("pin_match")),
                "pinned_revision_determinable": bool(node_row.get("pin_determinable")),
                "pinned_commit": node_row.get("pinned_commit") or "",
                "current_commit": node_row.get("current_commit") or "",
                "registration_status": node_row.get("registration_status"),
                "registration_notes": node_row.get("registration_notes"),
                "faceid_plusv2_bin": model_map.get("ipadapter_faceid_plusv2_sd15", {}).get("present", False),
                "faceid_plusv2_lora": model_map.get("ipadapter_faceid_plusv2_sd15_lora", {}).get(
                    "present", False
                ),
                "clip_vit_h": model_map.get("clip_vision_sd15", {}).get("present", False),
                "w600k_r50_onnx": model_map.get("insightface", {}).get("present", False),
                "assets": {
                    "ipadapter_faceid_plusv2_sd15": model_map.get("ipadapter_faceid_plusv2_sd15"),
                    "ipadapter_faceid_plusv2_sd15_lora": model_map.get(
                        "ipadapter_faceid_plusv2_sd15_lora"
                    ),
                    "clip_vision_sd15": model_map.get("clip_vision_sd15"),
                    "insightface_w600k_r50": model_map.get("insightface"),
                },
            }

        registration_ok = node_row.get("registration_status") in {"ok", "unchecked"}
        pin_ok = bool(node_row.get("pin_match")) if node_row.get("pin_determinable") else bool(
            node_row.get("present")
        )
        # If pin is determinable and mismatched, fail closed.
        if node_row.get("pin_determinable") and not node_row.get("pin_match"):
            pin_ok = False
        ready = (
            bool(node_row.get("present"))
            and pin_ok
            and registration_ok
            and not missing_m
            and node_row.get("registration_status") != "failed"
        )
        report["candidates"][cand] = {
            "models_present": present_m,
            "models_missing": missing_m,
            "nodes_present": [node_row["name"]] if node_row.get("present") else [],
            "nodes_missing": [] if node_row.get("present") else [node_row["name"]],
            "ready": ready,
            "detail": detail,
        }
        all_missing.extend(missing_m)

    seen: set[str] = set()
    unique_missing: list[str] = []
    for name in all_missing:
        if name not in seen:
            seen.add(name)
            unique_missing.append(name)
    # Keep instructions available in JSON, but human printer should defer until after probe.
    report["manual_instructions"] = format_manual_asset_instructions(bundle_models, unique_missing)
    report["missing_model_names"] = unique_missing
    report["ready_for_case_c"] = all(row.get("ready") for row in report["candidates"].values())
    return report


def prepare_identity_benchmark(
    repo_root: Path,
    *,
    drive_root: Path,
    candidate: str,
    scenario: str,
    character_id: str,
    runtime_prepared_root: Path,
    comfyui_input_dir: Path,
    bundle_models: list[dict[str, Any]],
    bundle_nodes: list[dict[str, Any]],
    comfyui_custom_nodes: Path | None = None,
    seed: int | None = None,
    require_models: bool = True,
    require_nodes: bool = True,
    dry_run: bool = False,
    allow_benchmark: bool = False,
) -> IdentityBenchmarkPrepResult:
    from .workflow_parameters import apply_parameter_bindings
    from .workflow_provenance import hash_ui_workflow

    result = IdentityBenchmarkPrepResult(
        ok=False,
        candidate=candidate,
        scenario=scenario,
        character_id=character_id,
        dry_run=dry_run,
    )
    if not allow_benchmark:
        result.errors.append(
            "ERROR: Identity benchmark preparation requires explicit --allow-benchmark "
            "(benchmark_only; not a production identity method)."
        )
        return result
    if candidate not in LIVE_CANDIDATES:
        result.errors.append(
            f"ERROR: Candidate not in live Package 4.12 set: {candidate}. "
            f"Deferred: {', '.join(DEFERRED_CANDIDATES)}"
        )
        return result
    if scenario not in SCENARIO_IDS:
        result.errors.append(f"ERROR: Unknown scenario: {scenario}")
        return result

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

    required_models = list(_required_models_for_candidate(candidate))
    required_nodes = list(_required_nodes_for_candidate(candidate))
    _, missing_models = verify_named_model_files(bundle_models, required_models)
    _, missing_nodes = verify_named_nodes(bundle_nodes, required_nodes, comfyui_custom_nodes)
    result.missing_models = missing_models
    result.missing_nodes = missing_nodes
    if require_models and missing_models:
        result.errors.append(
            "ERROR: Required identity-benchmark model files missing (no auto-download): "
            + ", ".join(missing_models)
        )
        result.errors.extend(format_manual_asset_instructions(bundle_models, missing_models))
    if require_nodes and missing_nodes:
        result.errors.append(
            "ERROR: Required identity-benchmark custom nodes missing: "
            + ", ".join(missing_nodes)
        )
        result.errors.append(
            "Install via Full Launch (install_nodes.py --execute) or Node Manager; "
            "pins are enforced from node_registry.json."
        )
    if result.errors:
        return result

    workflow_rel = _candidate_workflow_relpath(candidate)
    workflow_src = repo_root / workflow_rel
    if not workflow_src.is_file():
        result.errors.append(f"ERROR: Benchmark workflow missing: {workflow_rel}")
        return result
    try:
        workflow_data = json.loads(workflow_src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.errors.append(f"ERROR: Invalid benchmark workflow JSON: {exc}")
        return result
    graph_errors = assert_identity_benchmark_graph(workflow_data, candidate)
    if graph_errors:
        result.errors.extend(graph_errors)
        return result

    manifest_path = repo_root / _candidate_manifest_relpath(candidate)
    if not manifest_path.is_file():
        result.errors.append(f"ERROR: Benchmark manifest missing: {manifest_path.name}")
        return result
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = manifest.get("parameter_schema") or {}

    if seed is None:
        seed = generate_js_safe_seed()
    if not is_js_safe_seed(seed):
        result.errors.append(
            "ERROR: Seed must be between 0 and 9007199254740991 so it can be "
            "preserved exactly through ComfyUI."
        )
        return result

    import uuid

    preparation_id = f"prep_{uuid.uuid4()}"
    result.preparation_id = preparation_id
    result.workflow_identifier = _candidate_workflow_identifier(candidate)
    result.seed = int(seed)
    result.positive_prompt = SCENARIO_PROMPTS[scenario]
    result.staged_face_filename = f"ai_studio_idbench_{record.character_id[-8:]}_face.png"
    save_prefix = f"ai_studio_idbench_{candidate.split('_')[0]}"

    if dry_run:
        result.ok = True
        result.messages.append("Dry run: identity benchmark preparation would be created.")
        result.warnings.append(
            "Prepare/open alone does not quality-benchmark this identity method."
        )
        return result

    prepared_dir = Path(runtime_prepared_root) / preparation_id
    prepared_dir.mkdir(parents=True, exist_ok=False)
    archive_dir = prepared_dir / "benchmark_source"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_face = archive_dir / "primary_face.png"
    shutil.copy2(face_path, archived_face)
    if file_sha256(archived_face) != file_sha256(face_path):
        shutil.rmtree(prepared_dir, ignore_errors=True)
        result.errors.append("ERROR: Failed to archive character face for benchmark prep.")
        return result

    comfyui_input_dir = Path(comfyui_input_dir)
    comfyui_input_dir.mkdir(parents=True, exist_ok=True)
    staged = comfyui_input_dir / result.staged_face_filename
    shutil.copy2(archived_face, staged)

    params = {
        "input_image": result.staged_face_filename,
        "positive_prompt": result.positive_prompt,
        "seed": int(seed),
        "seed_mode": "fixed",
        "save_prefix": save_prefix,
    }
    bound = apply_parameter_bindings(workflow_data, schema, params)
    # Ensure LoadImage widget is the staged basename even if schema typing differs.
    for node in bound.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "LoadImage" and str(node.get("id")) == "1":
            widgets = list(node.get("widgets_values") or ["", "image"])
            widgets[0] = result.staged_face_filename
            if len(widgets) < 2:
                widgets.append("image")
            node["widgets_values"] = widgets
    bind_errors = assert_identity_benchmark_graph(bound, candidate)
    if bind_errors:
        shutil.rmtree(prepared_dir, ignore_errors=True)
        result.errors.extend(bind_errors)
        return result

    workflow_dest = prepared_dir / f"{preparation_id}.workflow.json"
    workflow_dest.write_text(json.dumps(bound, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    prepared_hash = hash_ui_workflow(bound)
    metadata = {
        "preparation_id": preparation_id,
        "preparation_kind": PREPARATION_KIND_IDENTITY_BENCHMARK,
        "benchmark_run": True,
        "benchmark_acknowledged": True,
        "capability": BENCHMARK_CAPABILITY,
        "candidate": candidate,
        "scenario": scenario,
        "character_id": record.character_id,
        "workflow_identifier": result.workflow_identifier,
        "package_version": PACKAGE_VERSION,
        "prepared_workflow_hash": prepared_hash,
        "canonical_workflow_hash": hash_ui_workflow(workflow_data),
        "parameters": params,
        "character_face_sha256": file_sha256(archived_face),
        "character_face_archived_path": "benchmark_source/primary_face.png",
        "license_notes": [
            "InsightFace / FaceID / inswapper weights are typically research-restricted; "
            "no production promotion without explicit license review."
        ],
        "quality_claim": "none — prepare/open is plumbing only",
        "graph_readiness": "structural_only",
    }
    (prepared_dir / f"{preparation_id}.metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result.prepared_dir = str(prepared_dir)
    result.ok = True
    result.messages.append(f"Identity benchmark preparation created: {preparation_id}")
    result.messages.append(f"Staged face: {result.staged_face_filename}")
    result.messages.append(f"Bound candidate graph hash: {prepared_hash[:16]}…")
    result.warnings.append(
        "CODE/SIM prepare/open does NOT mean this identity method was quality-benchmarked."
    )
    result.warnings.append(
        "Operational acceptance requires candidate × S1–S4 Runs and human rubric entries."
    )
    return result


def restage_identity_benchmark_face(
    *,
    prepared_dir: Path,
    metadata: dict[str, Any],
    comfyui_input_dir: Path,
) -> tuple[list[str], list[str]]:
    messages: list[str] = []
    errors: list[str] = []
    if str(metadata.get("preparation_kind") or "") != PREPARATION_KIND_IDENTITY_BENCHMARK:
        return messages, errors
    archived = prepared_dir / "benchmark_source" / "primary_face.png"
    if not archived.is_file():
        errors.append("ERROR: Identity benchmark archived face missing; cannot restage.")
        return messages, errors
    filename = str((metadata.get("parameters") or {}).get("input_image") or "").strip()
    if not filename:
        filename = "ai_studio_idbench_face.png"
    dest = Path(comfyui_input_dir) / Path(filename).name
    try:
        Path(comfyui_input_dir).mkdir(parents=True, exist_ok=True)
        if dest.is_file() and file_sha256(dest) == file_sha256(archived):
            messages.append(f"Identity benchmark face already staged: {dest.name}")
            return messages, errors
        shutil.copy2(archived, dest)
        messages.append(f"Restaged identity benchmark face to ComfyUI input: {dest.name}")
    except OSError as exc:
        errors.append(f"ERROR: Failed to restage identity benchmark face: {exc}")
    return messages, errors
