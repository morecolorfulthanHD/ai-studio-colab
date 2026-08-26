#!/usr/bin/env python3
"""Identity-method benchmark ledger and preparation (Package 4.12).

Benchmark artifacts are separated from ordinary creative generation semantics.
No automatic method promotion. Human rubric only — no invented perceptual scores.
"""

from __future__ import annotations

import json
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
REACTOR_REQUIRED_MODEL_NAMES = ("insightface",)
FACEID_REQUIRED_NODE = "ComfyUI_IPAdapter_plus"
REACTOR_REQUIRED_NODE = "ComfyUI-ReActor"

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


def verify_named_nodes(bundle_nodes: list[dict[str, Any]], names: list[str], comfyui_custom_nodes: Path | None) -> tuple[list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    registered = {str(entry.get("name") or "") for entry in bundle_nodes}
    for name in names:
        if name not in registered:
            missing.append(name)
            continue
        if comfyui_custom_nodes is not None:
            node_dir = Path(comfyui_custom_nodes) / name
            if not node_dir.is_dir():
                missing.append(name)
                continue
        present.append(name)
    return present, missing


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
    if require_nodes and missing_nodes:
        result.errors.append(
            "ERROR: Required identity-benchmark custom nodes missing: "
            + ", ".join(missing_nodes)
        )
    if result.errors:
        return result

    workflow_rel = _candidate_workflow_relpath(candidate)
    workflow_src = repo_root / workflow_rel
    if not workflow_src.is_file():
        result.errors.append(f"ERROR: Benchmark workflow missing: {workflow_rel}")
        return result

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

    workflow_dest = prepared_dir / f"{preparation_id}.workflow.json"
    shutil.copy2(workflow_src, workflow_dest)
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
        "parameters": {
            "seed": int(seed),
            "seed_mode": "fixed",
            "positive_prompt": result.positive_prompt,
            "input_image": result.staged_face_filename,
            "save_prefix": f"ai_studio_idbench_{candidate.split('_')[0]}",
        },
        "character_face_sha256": file_sha256(archived_face),
        "character_face_archived_path": "benchmark_source/primary_face.png",
        "license_notes": [
            "InsightFace / FaceID weights are typically research-restricted; "
            "no production promotion without explicit license review."
        ],
        "quality_claim": "none — prepare/open is plumbing only",
    }
    (prepared_dir / f"{preparation_id}.metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result.prepared_dir = str(prepared_dir)
    result.ok = True
    result.messages.append(f"Identity benchmark preparation created: {preparation_id}")
    result.messages.append(f"Staged face: {result.staged_face_filename}")
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
