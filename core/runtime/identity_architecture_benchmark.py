#!/usr/bin/env python3
"""InstantID SDXL identity architecture benchmark (Package 4.12.3).

Separate ledger and preparation from Package 4.12 method benchmark.
No auto-download. Structural readiness only until live GPU QA.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .character_identity import (
    load_character,
    resolve_primary_face_path,
    verify_character_face,
)
from .generation_evidence_ledger import file_sha256
from .identity_benchmark import (
    format_manual_asset_instructions,
    node_pin_status,
    normalize_scenario_id,
    verify_named_model_files,
    verify_named_nodes,
)
from .prepared_workflow_index import (
    append_preparation_record,
    find_by_preparation_id,
    preparations_log_path,
)
from .seed_mode import generate_js_safe_seed, is_js_safe_seed
from .workflow_library_preparation import _copy_preparation_tree

PACKAGE_VERSION = "4.12.3"
CANDIDATE_INSTANTID = "instantid_sdxl_benchmark"
PREPARATION_KIND = "identity_architecture_benchmark"
BENCHMARK_CAPABILITY = "identity_architecture_benchmark"
ARCHITECTURE_INSTANTID = "instantid_sdxl"

INSTANTID_PINNED_COMMIT = "72495e806bc2ab9c41581e15ccaa1bcf83c477e8"
INSTANTID_REQUIRED_NODE = "ComfyUI_InstantID"
SECONDARY_CANDIDATE_PULID = "pulid_sdxl"
SECONDARY_CANDIDATE_STATUS = "investigated_not_selected"

ARCHITECTURE_STATUS: dict[str, str] = {
    "reactor_faceswap_benchmark": "REJECTED_FOR_PRODUCTION_IDENTITY",
    "ipadapter_faceid_sd15_benchmark": "REJECTED_FOR_PRODUCTION_IDENTITY",
    "faceid_conditioning_sweep": "FAILED_FIRST_SWEEP",
    "instantid_sdxl_benchmark": "INVESTIGATION",
}

ARCHITECTURE_SCENARIO_PROMPTS: dict[str, str] = {
    "S1_near_front_portrait": (
        "portrait photograph of the same person, near-front facing, neutral expression, "
        "soft studio lighting, head and shoulders"
    ),
    "S2_head_angle_pose": (
        "portrait photograph of the same person, unmistakable three-quarter head turn "
        "approximately 40 degrees to the right, both eyes still visible, clear jawline, "
        "studio lighting"
    ),
    "S3_expression_change": (
        "portrait photograph of the same person, unmistakable genuine broad smile, "
        "visible upper teeth, cheeks raised, near-front facing, soft daylight"
    ),
    "S4_wardrobe_environment": (
        "full-body environmental photograph of the same person wearing a clearly red jacket, "
        "standing outdoors on a recognizable city street, substantial street and building "
        "background visible, natural daylight, full-body framing, not a studio portrait"
    ),
}

SCENARIO_DIMENSIONS: dict[str, tuple[int, int]] = {
    "S1_near_front_portrait": (1024, 1024),
    "S2_head_angle_pose": (1024, 1024),
    "S3_expression_change": (1024, 1024),
    "S4_wardrobe_environment": (1024, 768),
}

INSTANTID_REQUIRED_MODEL_NAMES = (
    "sdxl_base",
    "instantid_ip_adapter",
    "instantid_controlnet",
    "insightface_antelopev2",
)

INSTANTID_REQUIRED_GRAPH_NODES = frozenset(
    {
        "InstantIDModelLoader",
        "InstantIDFaceAnalysis",
        "ControlNetLoader",
        "ApplyInstantIDAdvanced",
        "LoadImage",
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "EmptyLatentImage",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    }
)

BENCHMARK_WORKFLOW_IDENTIFIERS = frozenset(
    {
        "reference/identity_instantid_sdxl_benchmark",
        "benchmark/identity_instantid_sdxl",
    }
)

LEDGER_FILENAME = "identity_architecture_benchmark.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def architecture_status_for(candidate: str) -> str:
    return ARCHITECTURE_STATUS.get(str(candidate or "").strip(), "UNKNOWN")


def architecture_ledger_path(drive_root: Path) -> Path:
    return Path(drive_root) / "logs" / LEDGER_FILENAME


def assert_instantid_graph(workflow_data: dict[str, Any]) -> list[str]:
    """Structural graph checks for InstantID SDXL benchmark workflow."""
    errors: list[str] = []
    nodes = workflow_data.get("nodes") or []
    if not isinstance(nodes, list):
        return ["ERROR: Workflow nodes must be a list."]
    types = {str(node.get("type") or "") for node in nodes if isinstance(node, dict)}
    missing = sorted(INSTANTID_REQUIRED_GRAPH_NODES - types)
    if missing:
        errors.append(
            "ERROR: InstantID benchmark workflow missing required nodes: " + ", ".join(missing)
        )

    load_image = next(
        (n for n in nodes if isinstance(n, dict) and n.get("type") == "LoadImage" and str(n.get("id")) == "13"),
        None,
    )
    if load_image is None:
        errors.append("ERROR: LoadImage node id=13 is required for face reference binding.")
    else:
        widgets = load_image.get("widgets_values") or []
        if not widgets or not str(widgets[0]).strip():
            errors.append("ERROR: LoadImage id=13 face filename is not bound.")

    apply_node = next(
        (n for n in nodes if isinstance(n, dict) and n.get("type") == "ApplyInstantIDAdvanced"),
        None,
    )
    if apply_node is not None:
        inputs = {
            str(i.get("name") or ""): i for i in (apply_node.get("inputs") or []) if isinstance(i, dict)
        }
        for required_input in ("instantid", "insightface", "control_net", "image", "model", "positive", "negative"):
            row = inputs.get(required_input)
            if row is None or row.get("link") is None:
                errors.append(f"ERROR: ApplyInstantIDAdvanced {required_input} is not bound.")

    latent = next(
        (n for n in nodes if isinstance(n, dict) and n.get("type") == "EmptyLatentImage" and str(n.get("id")) == "5"),
        None,
    )
    if latent is None:
        errors.append("ERROR: EmptyLatentImage node id=5 is required for dimension binding.")
    return errors


def is_identity_architecture_metadata(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    if metadata.get("benchmark_run") is True and str(metadata.get("architecture") or "") == ARCHITECTURE_INSTANTID:
        return True
    if str(metadata.get("preparation_kind") or "") == PREPARATION_KIND:
        return True
    if str(metadata.get("capability") or "") == BENCHMARK_CAPABILITY:
        return True
    if str(metadata.get("candidate") or "") == CANDIDATE_INSTANTID:
        return True
    identifier = str(metadata.get("workflow_identifier") or "").strip()
    return identifier in BENCHMARK_WORKFLOW_IDENTIFIERS


@dataclass
class IdentityArchitectureRecord:
    candidate: str
    architecture: str
    scenario: str
    character_id: str
    seed: Any = None
    executed_seed: Any = None
    preparation_id: str = ""
    preparation_kind: str = PREPARATION_KIND
    workflow_identifier: str = ""
    prepared_workflow_hash: str = ""
    character_face_sha256: str = ""
    character_reference_path: str = ""
    prompt_id: str = ""
    output_node_id: str = ""
    output_path: str = ""
    output_sha256: str = ""
    local_path: str = ""
    width: int | None = None
    height: int | None = None
    execution_status: str = "pending"
    automated_qa: dict[str, Any] = field(default_factory=dict)
    human_review: dict[str, Any] = field(default_factory=dict)
    human_review_status: str = "pending"
    promotion_status: str = "pending"
    license_gate: dict[str, Any] = field(default_factory=dict)
    asset_verification: dict[str, Any] = field(default_factory=dict)
    asset_verification_override: bool = False
    capture_idempotence_key: str = ""
    benchmark_run: bool = True
    notes: list[str] = field(default_factory=list)
    project_id: str = ""
    package_version: str = PACKAGE_VERSION
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def architecture_idempotence_key(prompt_id: str, output_node_id: str, output_sha256: str) -> str:
    return "|".join(
        [
            str(prompt_id or ""),
            str(output_node_id or ""),
            str(output_sha256 or "").strip().lower(),
        ]
    )


def find_architecture_ledger_row(
    ledger_path: Path,
    *,
    prompt_id: str,
    output_node_id: str,
    output_sha256: str,
) -> dict[str, Any] | None:
    key = architecture_idempotence_key(prompt_id, output_node_id, output_sha256)
    if not key or key == "||":
        return None
    for row in load_architecture_benchmark_records(ledger_path):
        if str(row.get("capture_idempotence_key") or "") == key:
            return row
        legacy = architecture_idempotence_key(
            str(row.get("prompt_id") or ""),
            str(row.get("output_node_id") or ""),
            str(row.get("output_sha256") or ""),
        )
        if legacy == key:
            return row
    return None


def load_architecture_benchmark_records(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def append_architecture_benchmark_record(ledger_path: Path, record: IdentityArchitectureRecord) -> None:
    from .jsonl_file_lock import append_jsonl_line_unlocked, exclusive_jsonl_lock

    if not record.created_at:
        record.created_at = utc_now()
    if not record.capture_idempotence_key:
        record.capture_idempotence_key = architecture_idempotence_key(
            record.prompt_id, record.output_node_id, record.output_sha256
        )
    payload = json.dumps(record.to_dict(), ensure_ascii=False)
    with exclusive_jsonl_lock(ledger_path):
        append_jsonl_line_unlocked(ledger_path, payload)


def append_architecture_benchmark_record_if_absent(
    ledger_path: Path,
    record: IdentityArchitectureRecord,
    *,
    idempotence_key: str,
) -> tuple[bool, bool]:
    """Atomically check idempotence key then append. Returns (ok, skipped_duplicate)."""
    from .jsonl_file_lock import append_jsonl_line_unlocked, exclusive_jsonl_lock

    key = str(idempotence_key or record.capture_idempotence_key or "").strip()
    if not key or key == "||":
        return False, False
    if not record.capture_idempotence_key:
        record.capture_idempotence_key = key
    if not record.created_at:
        record.created_at = utc_now()
    path = Path(ledger_path)
    with exclusive_jsonl_lock(path):
        for row in load_architecture_benchmark_records(path):
            if str(row.get("capture_idempotence_key") or "") == key:
                return True, True
            legacy = architecture_idempotence_key(
                str(row.get("prompt_id") or ""),
                str(row.get("output_node_id") or ""),
                str(row.get("output_sha256") or ""),
            )
            if legacy == key:
                return True, True
        append_jsonl_line_unlocked(path, json.dumps(record.to_dict(), ensure_ascii=False))
        return True, False


def update_architecture_ledger_qa(
    ledger_path: Path,
    *,
    idempotence_key: str,
    automated_qa: dict[str, Any],
    human_review: dict[str, Any] | None = None,
) -> tuple[bool, bool, list[str]]:
    """Idempotent QA enrichment: update existing row in place. No second append.

    Returns (ok, updated, messages).
    """
    from .jsonl_file_lock import exclusive_jsonl_lock

    key = str(idempotence_key or "").strip()
    if not key:
        return False, False, ["ERROR: idempotence key required for QA enrichment."]
    path = Path(ledger_path)
    messages: list[str] = []
    with exclusive_jsonl_lock(path):
        if not path.is_file():
            return False, False, ["ERROR: Architecture ledger missing for QA enrichment."]
        lines = path.read_text(encoding="utf-8").splitlines()
        rewritten: list[str] = []
        updated = False
        found = False
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                rewritten.append(line)
                continue
            row_key = str(row.get("capture_idempotence_key") or "")
            if not row_key:
                row_key = architecture_idempotence_key(
                    str(row.get("prompt_id") or ""),
                    str(row.get("output_node_id") or ""),
                    str(row.get("output_sha256") or ""),
                )
            if row_key != key:
                rewritten.append(json.dumps(row, ensure_ascii=False))
                continue
            found = True
            existing_qa = row.get("automated_qa") if isinstance(row.get("automated_qa"), dict) else {}
            # Enrich only when missing/empty; never overwrite a scored QA with empty.
            if existing_qa and existing_qa.get("automated_quality_status") and not automated_qa:
                rewritten.append(json.dumps(row, ensure_ascii=False))
                messages.append("QA already present; enrichment skipped.")
                continue
            if existing_qa == automated_qa:
                rewritten.append(json.dumps(row, ensure_ascii=False))
                messages.append("QA identical; enrichment no-op.")
                continue
            row["automated_qa"] = automated_qa
            if human_review is not None:
                row["human_review"] = human_review
                row["human_review_status"] = str(
                    (human_review or {}).get("status")
                    or automated_qa.get("human_review_status")
                    or row.get("human_review_status")
                    or "pending"
                )
            else:
                row["human_review_status"] = str(
                    automated_qa.get("human_review_status") or row.get("human_review_status") or "pending"
                )
            rewritten.append(json.dumps(row, ensure_ascii=False))
            updated = True
            messages.append(f"Enriched architecture ledger QA for key={key}")
        if not found:
            return False, False, [f"ERROR: No architecture ledger row for key={key}"]
        if updated:
            path.write_text("\n".join(rewritten) + ("\n" if rewritten else ""), encoding="utf-8")
        return True, updated, messages


def format_architecture_benchmark_report(records: list[dict[str, Any]]) -> str:
    lines = [
        "AI Studio — Identity Architecture Benchmark Report (Package 4.12.3)",
        "=" * 50,
        f"Records: {len(records)}",
        f"Live candidate: {CANDIDATE_INSTANTID} ({architecture_status_for(CANDIDATE_INSTANTID)})",
        f"Secondary candidate {SECONDARY_CANDIDATE_PULID}: {SECONDARY_CANDIDATE_STATUS}",
        "",
    ]
    if not records:
        lines.append("No identity architecture benchmark records found.")
        return "\n".join(lines)
    for row in records:
        qa = row.get("automated_qa") if isinstance(row.get("automated_qa"), dict) else {}
        lines.append(
            f"- {row.get('candidate')} / {row.get('scenario')} / "
            f"char={row.get('character_id')} / prep={row.get('preparation_id') or '—'} / "
            f"exec={row.get('execution_status')} / "
            f"auto_qa={qa.get('automated_quality_status') or qa.get('overall_status') or '—'} / "
            f"promotion={row.get('promotion_status')}"
        )
        if row.get("output_path"):
            lines.append(f"    output: {row.get('output_path')}")
    return "\n".join(lines)


@dataclass
class IdentityArchitecturePrepResult:
    ok: bool
    candidate: str = CANDIDATE_INSTANTID
    scenario: str = ""
    character_id: str = ""
    preparation_id: str = ""
    prepared_dir: str = ""
    runtime_prepared_dir: str = ""
    drive_prepared_dir: str = ""
    prepared_workflow_hash: str = ""
    canonical_workflow_hash: str = ""
    index_appended: bool = False
    workflow_identifier: str = ""
    seed: int | None = None
    staged_face_filename: str = ""
    positive_prompt: str = ""
    width: int | None = None
    height: int | None = None
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_models: list[str] = field(default_factory=list)
    missing_nodes: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _drive_prepared_root(drive_root: Path) -> Path:
    return drive_root / "workflows" / "prepared"


def build_architecture_benchmark_index_record(
    *,
    preparation_id: str,
    runtime_prepared_dir: Path,
    drive_prepared_dir: Path,
    workflow_identifier: str,
    scenario: str,
    character_id: str,
    prepared_workflow_hash: str,
    canonical_workflow_hash: str,
    seed: int,
    positive_prompt: str,
    width: int,
    height: int,
    created_timestamp: str | None = None,
) -> dict[str, Any]:
    ts = created_timestamp or utc_now()
    return {
        "preparation_id": preparation_id,
        "preparation_kind": PREPARATION_KIND,
        "workflow_identifier": workflow_identifier,
        "created_timestamp": ts,
        "created_at": ts,
        "benchmark_run": True,
        "benchmark_acknowledged": True,
        "architecture": ARCHITECTURE_INSTANTID,
        "candidate": CANDIDATE_INSTANTID,
        "scenario": scenario,
        "character_id": character_id,
        "prepared_workflow_path": str(runtime_prepared_dir / f"{preparation_id}.workflow.json"),
        "prepared_drive_path": str(drive_prepared_dir),
        "runtime_prepared_dir": str(runtime_prepared_dir),
        "drive_prepared_dir": str(drive_prepared_dir),
        "parameter_summary": {
            "positive_prompt": positive_prompt,
            "seed": seed,
            "seed_mode": "fixed",
            "width": width,
            "height": height,
            "save_prefix": "ai_studio_idarch_instantid",
        },
        "prepared_workflow_hash": prepared_workflow_hash,
        "canonical_workflow_hash": canonical_workflow_hash,
        "package_version": PACKAGE_VERSION,
        "readiness_status": "structural_only",
        "promotion_status": "pending",
    }


def finalize_identity_architecture_benchmark_preparation(
    *,
    drive_root: Path,
    preparation_id: str,
    runtime_prepared_dir: Path,
    drive_prepared_root: Path | None = None,
    metadata: dict[str, Any],
    workflow_identifier: str,
    scenario: str,
    character_id: str,
    prepared_workflow_hash: str,
    canonical_workflow_hash: str,
    seed: int,
    positive_prompt: str,
    width: int,
    height: int,
    skip_drive_mirror: bool = False,
    skip_index_append: bool = False,
) -> tuple[list[str], list[str]]:
    messages: list[str] = []
    errors: list[str] = []
    drive_root = Path(drive_root)
    runtime_prepared_dir = Path(runtime_prepared_dir)
    drive_root_prepared = drive_prepared_root or _drive_prepared_root(drive_root)
    drive_dir = drive_root_prepared / preparation_id

    if not skip_drive_mirror:
        drive_root_prepared.mkdir(parents=True, exist_ok=True)
        if drive_dir.is_dir():
            messages.append(f"Drive prepared copy already exists: {drive_dir}")
        else:
            try:
                _copy_preparation_tree(runtime_prepared_dir, drive_dir)
                messages.append(f"Drive prepared copy: {drive_dir}")
            except (OSError, FileExistsError) as exc:
                errors.append(
                    f"ERROR: Failed to mirror identity architecture benchmark prep to Drive: {exc}"
                )
                return messages, errors

    log_path = preparations_log_path(drive_root)
    existing = find_by_preparation_id(log_path, preparation_id)
    if skip_index_append or existing is not None:
        if existing is not None:
            messages.append(f"Preparation index record already present: {preparation_id}")
        return messages, errors

    index_record = build_architecture_benchmark_index_record(
        preparation_id=preparation_id,
        runtime_prepared_dir=runtime_prepared_dir,
        drive_prepared_dir=drive_dir,
        workflow_identifier=workflow_identifier,
        scenario=scenario,
        character_id=character_id,
        prepared_workflow_hash=prepared_workflow_hash,
        canonical_workflow_hash=canonical_workflow_hash,
        seed=seed,
        positive_prompt=positive_prompt,
        width=width,
        height=height,
        created_timestamp=str(metadata.get("created_timestamp") or metadata.get("created_at") or utc_now()),
    )
    append_preparation_record(log_path, index_record)
    messages.append(f"Appended preparation record to {log_path}")
    return messages, errors


def assess_instantid_structural_readiness(
    *,
    bundle_models: list[dict[str, Any]],
    bundle_nodes: list[dict[str, Any]],
    comfyui_custom_nodes: Path | None,
) -> dict[str, Any]:
    """Registry + filesystem pin presence only — not live ComfyUI import or visual QA."""
    _, missing_models = verify_named_model_files(bundle_models, list(INSTANTID_REQUIRED_MODEL_NAMES))
    _, missing_nodes = verify_named_nodes(bundle_nodes, [INSTANTID_REQUIRED_NODE], comfyui_custom_nodes)
    node_row = node_pin_status(
        bundle_nodes,
        INSTANTID_REQUIRED_NODE,
        comfyui_custom_nodes,
        required_node_types=tuple(
            t
            for t in INSTANTID_REQUIRED_GRAPH_NODES
            if t
            in {
                "InstantIDModelLoader",
                "InstantIDFaceAnalysis",
                "ApplyInstantIDAdvanced",
            }
        ),
    )
    pin_ok = bool(node_row.get("pin_match")) if node_row.get("pin_determinable") else bool(
        node_row.get("present")
    )
    if node_row.get("pin_determinable") and not node_row.get("pin_match"):
        pin_ok = False
    ready = bool(node_row.get("present")) and pin_ok and not missing_models and not missing_nodes
    return {
        "candidate": CANDIDATE_INSTANTID,
        "architecture": ARCHITECTURE_INSTANTID,
        "models_missing": missing_models,
        "nodes_missing": missing_nodes,
        "node_pin": node_row,
        "ready": ready,
        "quality_claim": "none — structural registry/filesystem readiness only",
        "manual_instructions": format_manual_asset_instructions(bundle_models, missing_models),
    }


def assess_instantid_asset_readiness(
    *,
    drive_root: Path,
    bundle_models: list[dict[str, Any]],
    comfyui_runtime: Path | None = None,
) -> dict[str, Any]:
    """Fail closed unless each InstantID asset has verified SHA/size or explicit UNVERIFIED blocks readiness."""
    from .identity_benchmark import (
        INTEGRITY_VERIFIED,
        verify_model_asset_integrity,
    )

    del drive_root, comfyui_runtime  # reserved for future path remapping
    errors: list[str] = []
    assets: list[dict[str, Any]] = []
    by_name = {str(m.get("name") or ""): m for m in bundle_models if isinstance(m, dict)}
    for name in INSTANTID_REQUIRED_MODEL_NAMES:
        row = dict(by_name.get(name) or {})
        row.setdefault("name", name)
        expected_sha = str(row.get("expected_sha256") or "").strip()
        expected_size = row.get("expected_size_bytes")
        runtime_path = str(row.get("runtime_path") or "").strip()
        verification_state = str(row.get("verification_state") or "").strip()
        entry: dict[str, Any] = {
            "name": name,
            "runtime_path": runtime_path,
            "filename": row.get("filename"),
            "verification_state": verification_state
            or ("HASH_DEFINED" if expected_sha and expected_size is not None else "UNVERIFIED_MANUAL_ASSET"),
            "integrity": None,
        }
        if verification_state == "UNVERIFIED_MANUAL_ASSET" or not expected_sha or expected_size is None:
            entry["verification_state"] = "UNVERIFIED_MANUAL_ASSET"
            errors.append(
                f"ERROR: Asset {name} lacks expected_sha256/expected_size_bytes "
                "(UNVERIFIED_MANUAL_ASSET) — live readiness fail closed."
            )
            assets.append(entry)
            continue
        path = Path(runtime_path) if runtime_path else None
        # Directory packs (e.g. antelopev2): require directory presence + optional file list hashes.
        if path is not None and path.is_dir():
            required_files = row.get("required_files") or []
            if not required_files:
                entry["verification_state"] = "UNVERIFIED_MANUAL_ASSET"
                errors.append(
                    f"ERROR: Directory asset {name} has no required_files hashes "
                    "(UNVERIFIED_MANUAL_ASSET)."
                )
                assets.append(entry)
                continue
            file_results = []
            for rf in required_files:
                if not isinstance(rf, dict):
                    continue
                fname = str(rf.get("filename") or "")
                fpath = path / fname
                sub = verify_model_asset_integrity(
                    {
                        "name": f"{name}/{fname}",
                        "runtime_path": str(fpath),
                        "filename": fname,
                        "expected_sha256": rf.get("expected_sha256"),
                        "expected_size_bytes": rf.get("expected_size_bytes"),
                    }
                )
                file_results.append(sub)
                if not sub.get("verified"):
                    errors.append(
                        f"ERROR: InstantID asset integrity {sub.get('status')} for {name}/{fname}"
                    )
            entry["integrity"] = file_results
            entry["verification_state"] = (
                "VERIFIED" if all(r.get("verified") for r in file_results) else "FAILED"
            )
            assets.append(entry)
            continue
        integrity = verify_model_asset_integrity(row)
        entry["integrity"] = integrity
        if integrity.get("status") != INTEGRITY_VERIFIED:
            errors.append(
                f"ERROR: InstantID asset integrity {integrity.get('status')} for {name}"
            )
        else:
            entry["verification_state"] = "VERIFIED"
        assets.append(entry)
    ready = not errors
    return {
        "ready": ready,
        "assets": assets,
        "errors": errors,
        "quality_claim": "none — hash/size verification only",
    }


def assess_instantid_license_gate(repo_root: Path) -> dict[str, Any]:
    """Structured license statuses. Promotion requires all ACCEPTABLE."""
    path = Path(repo_root) / "configs" / "benchmarks" / "identity_architecture_licenses.json"
    default = {
        "components": {
            "ComfyUI_InstantID_node": {
                "status": "REVIEW_REQUIRED",
                "notes": "cubiq/ComfyUI_InstantID Apache-2.0-like node code; confirm LICENSE file.",
            },
            "InstantID_model_weights": {
                "status": "REVIEW_REQUIRED",
                "notes": "InstantX InstantID weights — review InstantX/Apache and research terms.",
            },
            "insightface_antelopev2": {
                "status": "BLOCKED_FOR_COMMERCIAL",
                "notes": "InsightFace models typically research/non-commercial — blocks production promotion.",
            },
            "sdxl_base": {
                "status": "RESTRICTED",
                "notes": "CreativeML Open RAIL++-M — use restrictions apply; not unconditional ACCEPTABLE.",
            },
        },
        "overall_status": "BLOCKED_FOR_COMMERCIAL",
        "promotion_allowed": False,
    }
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("components"):
                components = data["components"]
                statuses = [
                    str((v or {}).get("status") or "REVIEW_REQUIRED")
                    for v in components.values()
                    if isinstance(v, dict)
                ]
                promotion_allowed = bool(statuses) and all(s == "ACCEPTABLE" for s in statuses)
                if any(s == "BLOCKED_FOR_COMMERCIAL" for s in statuses):
                    overall = "BLOCKED_FOR_COMMERCIAL"
                elif any(s in {"REVIEW_REQUIRED", "RESTRICTED"} for s in statuses):
                    overall = "REVIEW_REQUIRED"
                elif promotion_allowed:
                    overall = "ACCEPTABLE"
                else:
                    overall = "REVIEW_REQUIRED"
                return {
                    "components": components,
                    "overall_status": overall,
                    "promotion_allowed": promotion_allowed,
                    "source": str(path),
                }
        except (OSError, json.JSONDecodeError):
            pass
    return {**default, "source": "defaults"}


def prepare_identity_architecture_benchmark(
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
    candidate: str = CANDIDATE_INSTANTID,
) -> IdentityArchitecturePrepResult:
    from .workflow_parameters import apply_parameter_bindings
    from .workflow_provenance import hash_ui_workflow

    result = IdentityArchitecturePrepResult(
        ok=False,
        candidate=candidate,
        scenario=scenario,
        character_id=character_id,
        dry_run=dry_run,
    )
    if not allow_benchmark:
        result.errors.append(
            "ERROR: Identity architecture benchmark preparation requires explicit "
            "--allow-benchmark (benchmark_only; not a production identity method)."
        )
        return result
    if candidate != CANDIDATE_INSTANTID:
        result.errors.append(
            f"ERROR: Package 4.12.3 supports only {CANDIDATE_INSTANTID}; got {candidate}."
        )
        return result
    canonical_scenario = normalize_scenario_id(scenario)
    if canonical_scenario is None:
        from .identity_benchmark import SCENARIO_IDS

        result.errors.append(
            f"ERROR: Unknown scenario: {scenario}. "
            f"Use S1–S4 shorthand or one of: {', '.join(SCENARIO_IDS)}"
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

    _, missing_models = verify_named_model_files(bundle_models, list(INSTANTID_REQUIRED_MODEL_NAMES))
    _, missing_nodes = verify_named_nodes(bundle_nodes, [INSTANTID_REQUIRED_NODE], comfyui_custom_nodes)
    result.missing_models = missing_models
    result.missing_nodes = missing_nodes
    if require_models and missing_models:
        result.errors.append(
            "ERROR: Required InstantID architecture model files missing (no auto-download): "
            + ", ".join(missing_models)
        )
        result.errors.extend(format_manual_asset_instructions(bundle_models, missing_models))
    if require_nodes and missing_nodes:
        result.errors.append(
            "ERROR: Required InstantID custom node missing: " + ", ".join(missing_nodes)
        )
        result.errors.append(
            f"Install via Full Launch; pin {INSTANTID_REQUIRED_NODE} @ {INSTANTID_PINNED_COMMIT}."
        )
    if result.errors:
        return result

    workflow_rel = Path("workflows/reference/identity_instantid_sdxl_benchmark/workflow.json")
    workflow_src = repo_root / workflow_rel
    if not workflow_src.is_file():
        result.errors.append(f"ERROR: Benchmark workflow missing: {workflow_rel}")
        return result
    try:
        workflow_data = json.loads(workflow_src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.errors.append(f"ERROR: Invalid benchmark workflow JSON: {exc}")
        return result
    graph_errors = assert_instantid_graph(workflow_data)
    if graph_errors:
        result.errors.extend(graph_errors)
        return result

    manifest_path = repo_root / "workflows/reference/identity_instantid_sdxl_benchmark/manifest.json"
    if not manifest_path.is_file():
        result.errors.append("ERROR: Benchmark manifest missing.")
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

    width, height = SCENARIO_DIMENSIONS[scenario]
    result.width = width
    result.height = height
    preparation_id = f"prep_{uuid.uuid4()}"
    result.preparation_id = preparation_id
    result.workflow_identifier = "reference/identity_instantid_sdxl_benchmark"
    result.seed = int(seed)
    result.positive_prompt = ARCHITECTURE_SCENARIO_PROMPTS[scenario]
    result.staged_face_filename = f"ai_studio_idarch_{record.character_id[-8:]}_face.png"
    save_prefix = "ai_studio_idarch_instantid"

    if dry_run:
        result.ok = True
        result.messages.append("Dry run: identity architecture benchmark preparation would be created.")
        result.warnings.append("Prepare/open alone does not quality-benchmark InstantID SDXL.")
        return result

    prepared_dir = Path(runtime_prepared_root) / preparation_id
    prepared_dir.mkdir(parents=True, exist_ok=False)
    archive_dir = prepared_dir / "benchmark_source"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_face = archive_dir / "primary_face.png"
    shutil.copy2(face_path, archived_face)
    if file_sha256(archived_face) != file_sha256(face_path):
        shutil.rmtree(prepared_dir, ignore_errors=True)
        result.errors.append("ERROR: Failed to archive character face for architecture benchmark prep.")
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
        "width": width,
        "height": height,
        "save_prefix": save_prefix,
    }
    bound = apply_parameter_bindings(workflow_data, schema, params)
    for node in bound.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "LoadImage" and str(node.get("id")) == "13":
            widgets = list(node.get("widgets_values") or ["", "image"])
            widgets[0] = result.staged_face_filename
            if len(widgets) < 2:
                widgets.append("image")
            node["widgets_values"] = widgets
    bind_errors = assert_instantid_graph(bound)
    if bind_errors:
        shutil.rmtree(prepared_dir, ignore_errors=True)
        result.errors.extend(bind_errors)
        return result

    bound.setdefault("extra", {})
    if not isinstance(bound.get("extra"), dict):
        bound["extra"] = {}
    bound["extra"]["ai_studio"] = {
        "preparation_id": preparation_id,
        "preparation_kind": PREPARATION_KIND,
        "benchmark_run": True,
        "benchmark_acknowledged": True,
        "capability": BENCHMARK_CAPABILITY,
        "architecture": ARCHITECTURE_INSTANTID,
        "candidate": CANDIDATE_INSTANTID,
        "scenario": scenario,
        "character_id": record.character_id,
        "workflow_identifier": result.workflow_identifier,
        "package_version": PACKAGE_VERSION,
        "promotion_status": "pending",
        "prepared_workflow_hash": "",
        "canonical_workflow_hash": "",
        "seed": int(seed),
        "seed_mode": "fixed",
        "character_face_sha256": file_sha256(archived_face),
        "character_reference_path": "benchmark_source/primary_face.png",
    }

    workflow_dest = prepared_dir / f"{preparation_id}.workflow.json"
    prepared_hash = hash_ui_workflow(bound)
    canonical_hash = hash_ui_workflow(workflow_data)
    bound["extra"]["ai_studio"]["prepared_workflow_hash"] = prepared_hash
    bound["extra"]["ai_studio"]["canonical_workflow_hash"] = canonical_hash
    workflow_dest.write_text(json.dumps(bound, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    created_ts = utc_now()
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
        "architecture": ARCHITECTURE_INSTANTID,
        "candidate": CANDIDATE_INSTANTID,
        "scenario": scenario,
        "character_id": record.character_id,
        "workflow_identifier": result.workflow_identifier,
        "package_version": PACKAGE_VERSION,
        "promotion_status": "pending",
        "prepared_workflow_hash": prepared_hash,
        "canonical_workflow_hash": canonical_hash,
        "prepared_runtime_path": str(prepared_dir),
        "prepared_drive_path": str(drive_dir),
        "parameters": params,
        "character_face_sha256": file_sha256(archived_face),
        "character_face_archived_path": "benchmark_source/primary_face.png",
        "license_notes": [
            "InstantID / InsightFace antelopev2 / SDXL weights require explicit license review.",
            "No auto-download of restricted weights.",
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
    result.index_appended = find_by_preparation_id(preparations_log_path(drive_root), preparation_id) is not None
    result.ok = True
    result.messages.append(f"Identity architecture benchmark preparation created: {preparation_id}")
    result.messages.append(f"Staged face: {result.staged_face_filename}")
    result.messages.append(f"Scenario dimensions: {width}x{height}")
    result.warnings.append("CODE/SIM prepare/open does NOT mean InstantID SDXL passed visual QA.")
    return result


def restage_identity_architecture_benchmark_face(
    *,
    prepared_dir: Path,
    metadata: dict[str, Any],
    comfyui_input_dir: Path,
) -> tuple[list[str], list[str]]:
    """Restage archived face for identity_architecture_benchmark preparations."""
    messages: list[str] = []
    errors: list[str] = []
    kind = str(metadata.get("preparation_kind") or "")
    if kind != PREPARATION_KIND:
        return messages, errors
    archived = prepared_dir / "benchmark_source" / "primary_face.png"
    if not archived.is_file():
        errors.append("ERROR: Identity architecture benchmark archived face missing; cannot restage.")
        return messages, errors
    filename = str((metadata.get("parameters") or {}).get("input_image") or "").strip()
    if not filename:
        filename = "ai_studio_idarch_face.png"
    dest = Path(comfyui_input_dir) / Path(filename).name
    try:
        Path(comfyui_input_dir).mkdir(parents=True, exist_ok=True)
        if dest.is_file() and file_sha256(dest) == file_sha256(archived):
            messages.append(f"Identity architecture benchmark face already staged: {dest.name}")
            return messages, errors
        shutil.copy2(archived, dest)
        messages.append(f"Restaged identity architecture benchmark face to ComfyUI input: {dest.name}")
    except OSError as exc:
        errors.append(f"ERROR: Failed to restage identity architecture benchmark face: {exc}")
    return messages, errors
