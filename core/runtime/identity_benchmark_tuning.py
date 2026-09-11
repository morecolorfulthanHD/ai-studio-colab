#!/usr/bin/env python3
"""Package 4.12.2 — controlled FaceID conditioning sweep (benchmark-only).

Isolated from baseline identity_benchmark records. First phase: S2 + S3 only.
Variants change only FaceID weight / weight_faceidv2 / end_at (and document start_at).
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .generation_evidence_ledger import file_sha256, utc_now
from .identity_benchmark import (
    BENCHMARK_CAPABILITY,
    CANDIDATE_FACEID,
    PREPARATION_KIND_IDENTITY_BENCHMARK,
    PREPARATION_KIND_IDENTITY_BENCHMARK_TUNING,
    SCENARIO_PROMPTS,
    normalize_scenario_id,
    prepare_identity_benchmark,
)
from .jsonl_file_lock import append_jsonl_line_unlocked, exclusive_jsonl_lock
from .workflow_provenance import hash_ui_workflow

PACKAGE_VERSION = "4.12.2"
BENCHMARK_SUBTYPE_FACEID_CONDITIONING_SWEEP = "faceid_conditioning_sweep"
BENCHMARK_FAMILY_IDENTITY_METHOD = "identity_method"

TUNING_LEDGER_REL = Path("logs") / "identity_benchmark_tuning.jsonl"

# Frozen live baseline evidence (do not rerun these prep IDs).
BASELINE_FACEID_PREPS: dict[str, dict[str, Any]] = {
    "S1_near_front_portrait": {
        "preparation_id": "prep_efa7b6d8-58ec-4d26-8d19-697ec3ce9558",
        "seed": 4791031672062905,
    },
    "S2_head_angle_pose": {
        "preparation_id": "prep_dcacc2ae-dc0a-45e7-90a5-5b6eb8026b1b",
        "seed": 470280831310422,
    },
    "S3_expression_change": {
        "preparation_id": "prep_5b0773a9-30fc-436a-aa30-d40dec98e517",
        "seed": 5926742613902171,
    },
    "S4_wardrobe_environment": {
        "preparation_id": "prep_5b669994-aa64-44bf-b349-3ec1e9021800",
        "seed": 2792331214840135,
    },
}

FIRST_PHASE_SCENARIOS = frozenset({"S2_head_angle_pose", "S3_expression_change"})

# Canonical FaceID widget layout (identity_faceid_benchmark/workflow.json).
FACEID_LOADER_NODE_ID = 9
FACEID_APPLY_NODE_ID = 10
BASELINE_LORA_STRENGTH = 0.6
BASELINE_WEIGHT = 1.0
BASELINE_WEIGHT_FACEIDV2 = 2.0
BASELINE_START_AT = 0.0
BASELINE_END_AT = 1.0
BASELINE_WEIGHT_TYPE = "linear"
BASELINE_COMBINE_EMBEDS = "concat"
BASELINE_PRESET = "FACEID PLUS V2"
BASELINE_PROVIDER = "CPU"

# Fields that variants may change (everything else must match baseline bound graph).
ALLOWED_TUNING_FIELDS = frozenset(
    {
        "weight",
        "weight_faceidv2",
        "start_at",
        "end_at",
    }
)


@dataclass(frozen=True)
class FaceidTuningVariant:
    variant_id: str
    label: str
    weight: float
    weight_faceidv2: float
    start_at: float
    end_at: float

    def parameters(self) -> dict[str, float]:
        return {
            "weight": float(self.weight),
            "weight_faceidv2": float(self.weight_faceidv2),
            "start_at": float(self.start_at),
            "end_at": float(self.end_at),
        }


FACEID_TUNING_VARIANTS: dict[str, FaceidTuningVariant] = {
    "faceid_v2_1p5_full": FaceidTuningVariant(
        "faceid_v2_1p5_full", "A", 1.0, 1.5, 0.0, 1.0
    ),
    "faceid_v2_1p0_full": FaceidTuningVariant(
        "faceid_v2_1p0_full", "B", 1.0, 1.0, 0.0, 1.0
    ),
    "faceid_v2_1p5_end080": FaceidTuningVariant(
        "faceid_v2_1p5_end080", "C", 1.0, 1.5, 0.0, 0.8
    ),
    "faceid_v2_1p0_end080": FaceidTuningVariant(
        "faceid_v2_1p0_end080", "D", 1.0, 1.0, 0.0, 0.8
    ),
}

VARIANT_ALIASES: dict[str, str] = {
    "a": "faceid_v2_1p5_full",
    "b": "faceid_v2_1p0_full",
    "c": "faceid_v2_1p5_end080",
    "d": "faceid_v2_1p0_end080",
}

S2_TUNING_RUBRIC = (
    "identity_similarity",
    "facial_naturalness",
    "pose_angle_robustness",
    "pose_instruction_adherence",
    "hair_head_boundary",
    "artifact_severity",
    "overall_4_13_fitness",
)
S3_TUNING_RUBRIC = (
    "identity_similarity",
    "facial_naturalness",
    "expression_robustness",
    "expression_instruction_adherence",
    "hair_head_boundary",
    "artifact_severity",
    "overall_4_13_fitness",
)

# Deferred S4 composition options (document only — do not hardcode in this package).
S4_COMPOSITION_OPTIONS = (
    {
        "id": "768x512_landscape",
        "width": 768,
        "height": 512,
        "notes": "Favors environmental width; may help city-street framing.",
    },
    {
        "id": "768x768_square",
        "width": 768,
        "height": 768,
        "notes": "Neutral framing; still risks portrait bias if camera is close.",
    },
    {
        "id": "512x768_portrait",
        "width": 512,
        "height": 768,
        "notes": "Baseline-like portrait bias; not recommended for S4 scene tests.",
    },
)


@dataclass
class FaceidTuningPrepResult:
    ok: bool
    candidate: str = CANDIDATE_FACEID
    scenario: str = ""
    character_id: str = ""
    preparation_id: str = ""
    baseline_preparation_id: str = ""
    baseline_seed: int | None = None
    tuning_variant_id: str = ""
    tuning_parameters: dict[str, float] = field(default_factory=dict)
    prepared_dir: str = ""
    drive_prepared_dir: str = ""
    prepared_workflow_hash: str = ""
    positive_prompt: str = ""
    seed: int | None = None
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_tuning_variant_id(raw: str) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text in FACEID_TUNING_VARIANTS:
        return text
    alias = VARIANT_ALIASES.get(text.lower())
    if alias:
        return alias
    # Allow A/B/C/D labels via variant.label
    for vid, variant in FACEID_TUNING_VARIANTS.items():
        if text.upper() == variant.label:
            return vid
    return None


def tuning_rubric_for_scenario(scenario: str) -> tuple[str, ...]:
    if scenario == "S2_head_angle_pose":
        return S2_TUNING_RUBRIC
    if scenario == "S3_expression_change":
        return S3_TUNING_RUBRIC
    return ()


def default_tuning_ledger_path(drive_root: Path) -> Path:
    return Path(drive_root) / TUNING_LEDGER_REL


def is_identity_benchmark_tuning_metadata(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    if metadata.get("benchmark_tuning") is True:
        return True
    kind = str(metadata.get("preparation_kind") or "").strip()
    if kind == PREPARATION_KIND_IDENTITY_BENCHMARK_TUNING:
        return True
    subtype = str(metadata.get("benchmark_subtype") or "").strip()
    return subtype == BENCHMARK_SUBTYPE_FACEID_CONDITIONING_SWEEP


def _find_node(workflow: dict[str, Any], node_id: int, node_type: str) -> dict[str, Any] | None:
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if int(node.get("id") or -1) == int(node_id) and str(node.get("type") or "") == node_type:
            return node
    return None


def read_faceid_conditioning(workflow: dict[str, Any]) -> dict[str, Any]:
    loader = _find_node(workflow, FACEID_LOADER_NODE_ID, "IPAdapterUnifiedLoaderFaceID")
    faceid = _find_node(workflow, FACEID_APPLY_NODE_ID, "IPAdapterFaceID")
    if loader is None or faceid is None:
        raise ValueError("FaceID loader/apply nodes missing from workflow")
    lw = list(loader.get("widgets_values") or [])
    fw = list(faceid.get("widgets_values") or [])
    if len(lw) < 3 or len(fw) < 6:
        raise ValueError("FaceID widgets_values shorter than expected")
    return {
        "preset": lw[0],
        "lora_strength": float(lw[1]),
        "provider": lw[2],
        "weight": float(fw[0]),
        "weight_faceidv2": float(fw[1]),
        "weight_type": fw[2],
        "combine_embeds": fw[3],
        "start_at": float(fw[4]),
        "end_at": float(fw[5]),
    }


def apply_faceid_tuning_variant(
    workflow: dict[str, Any], variant: FaceidTuningVariant
) -> dict[str, Any]:
    """Return a deep-copied workflow with only allowed FaceID conditioning fields changed."""
    out = copy.deepcopy(workflow)
    loader = _find_node(out, FACEID_LOADER_NODE_ID, "IPAdapterUnifiedLoaderFaceID")
    faceid = _find_node(out, FACEID_APPLY_NODE_ID, "IPAdapterFaceID")
    if loader is None or faceid is None:
        raise ValueError("FaceID loader/apply nodes missing from workflow")
    lw = list(loader.get("widgets_values") or [])
    fw = list(faceid.get("widgets_values") or [])
    if len(lw) < 3 or len(fw) < 6:
        raise ValueError("FaceID widgets_values shorter than expected")
    # Preserve loader (lora_strength / preset / provider) — variants do not change them.
    fw[0] = float(variant.weight)
    fw[1] = float(variant.weight_faceidv2)
    fw[4] = float(variant.start_at)
    fw[5] = float(variant.end_at)
    faceid["widgets_values"] = fw
    loader["widgets_values"] = lw
    return out


def _node_map(workflow: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for node in workflow.get("nodes") or []:
        if isinstance(node, dict) and node.get("id") is not None:
            out[int(node["id"])] = node
    return out


def assert_faceid_tuning_graph_diff(
    baseline_bound: dict[str, Any],
    tuned: dict[str, Any],
    variant: FaceidTuningVariant,
) -> list[str]:
    """Fail closed if anything other than allowed FaceID conditioning fields differs."""
    errors: list[str] = []
    base_nodes = _node_map(baseline_bound)
    tuned_nodes = _node_map(tuned)
    if set(base_nodes) != set(tuned_nodes):
        errors.append("ERROR: Tuning graph node ID set differs from baseline-bound graph.")
        return errors
    for node_id, base_node in base_nodes.items():
        tuned_node = tuned_nodes[node_id]
        if str(base_node.get("type") or "") != str(tuned_node.get("type") or ""):
            errors.append(f"ERROR: Node {node_id} type changed under tuning.")
            continue
        base_links = json.dumps(base_node.get("inputs") or [], sort_keys=True, default=str)
        tuned_links = json.dumps(tuned_node.get("inputs") or [], sort_keys=True, default=str)
        if base_links != tuned_links:
            errors.append(f"ERROR: Node {node_id} input topology changed under tuning.")
        if int(node_id) == FACEID_APPLY_NODE_ID and str(base_node.get("type")) == "IPAdapterFaceID":
            bw = list(base_node.get("widgets_values") or [])
            tw = list(tuned_node.get("widgets_values") or [])
            if len(bw) < 6 or len(tw) < 6:
                errors.append("ERROR: IPAdapterFaceID widgets_values incomplete.")
                continue
            expected = [
                float(variant.weight),
                float(variant.weight_faceidv2),
                bw[2],
                bw[3],
                float(variant.start_at),
                float(variant.end_at),
            ]
            actual = [float(tw[0]), float(tw[1]), tw[2], tw[3], float(tw[4]), float(tw[5])]
            if actual != expected:
                errors.append(
                    "ERROR: IPAdapterFaceID widgets do not match the selected tuning variant "
                    f"(expected {expected}, got {actual})."
                )
            # weight_type / combine_embeds must remain baseline.
            if tw[2] != BASELINE_WEIGHT_TYPE or tw[3] != BASELINE_COMBINE_EMBEDS:
                errors.append("ERROR: FaceID weight_type/combine_embeds must remain baseline.")
            continue
        if int(node_id) == FACEID_LOADER_NODE_ID and str(base_node.get("type")) == "IPAdapterUnifiedLoaderFaceID":
            bw = list(base_node.get("widgets_values") or [])
            tw = list(tuned_node.get("widgets_values") or [])
            if bw != tw:
                errors.append(
                    "ERROR: IPAdapterUnifiedLoaderFaceID must remain unchanged in this sweep "
                    f"(including lora_strength={BASELINE_LORA_STRENGTH})."
                )
            continue
        if json.dumps(base_node.get("widgets_values") or [], default=str) != json.dumps(
            tuned_node.get("widgets_values") or [], default=str
        ):
            errors.append(
                f"ERROR: Unexpected widgets mutation on node {node_id} "
                f"({base_node.get('type')}); only FaceID conditioning fields may change."
            )
    # Link list / topology
    if json.dumps(baseline_bound.get("links") or [], default=str) != json.dumps(
        tuned.get("links") or [], default=str
    ):
        errors.append("ERROR: Graph links differ from baseline-bound graph.")
    return errors


def prepare_faceid_tuning_benchmark(
    *,
    drive_root: Path,
    repo_root: Path,
    runtime_prepared_root: Path,
    comfyui_input_dir: Path,
    character_id: str,
    scenario: str,
    variant_id: str,
    bundle_models: list[dict[str, Any]],
    bundle_nodes: list[dict[str, Any]],
    comfyui_custom_nodes: Path | None,
    drive_prepared_root: Path | None = None,
    allow_benchmark: bool = False,
    require_models: bool = True,
    require_nodes: bool = True,
    dry_run: bool = False,
) -> FaceidTuningPrepResult:
    """Prepare an isolated FaceID conditioning-sweep graph for S2/S3 first-phase variants."""
    result = FaceidTuningPrepResult(ok=False, character_id=character_id)
    if not allow_benchmark:
        result.errors.append(
            "ERROR: FaceID tuning benchmark requires explicit --allow-benchmark "
            "(benchmark-only; not a quality claim)."
        )
        return result

    canonical = normalize_scenario_id(scenario)
    if canonical is None:
        result.errors.append(f"ERROR: Unknown scenario: {scenario}")
        return result
    result.scenario = canonical
    if canonical not in FIRST_PHASE_SCENARIOS:
        result.errors.append(
            "ERROR: First-phase FaceID conditioning sweep only allows S2 and S3. "
            f"Refusing {canonical}. S1/S4 tuning is deferred."
        )
        return result

    resolved_variant = resolve_tuning_variant_id(variant_id)
    if resolved_variant is None:
        result.errors.append(
            f"ERROR: Unknown tuning variant: {variant_id}. "
            f"Use A–D or one of: {', '.join(FACEID_TUNING_VARIANTS)}"
        )
        return result
    variant = FACEID_TUNING_VARIANTS[resolved_variant]
    result.tuning_variant_id = variant.variant_id
    result.tuning_parameters = variant.parameters()

    baseline = BASELINE_FACEID_PREPS[canonical]
    result.baseline_preparation_id = str(baseline["preparation_id"])
    result.baseline_seed = int(baseline["seed"])
    result.seed = int(baseline["seed"])
    result.positive_prompt = SCENARIO_PROMPTS[canonical]

    if dry_run:
        result.ok = True
        result.messages.append(
            f"Dry run: would prepare FaceID tuning {variant.variant_id} for {canonical} "
            f"seed={result.seed} params={result.tuning_parameters}"
        )
        result.warnings.append(
            "Prepare/open alone does not quality-benchmark FaceID. "
            "Visual scenario pass is separate from operational execution pass."
        )
        return result

    base_prep = prepare_identity_benchmark(
        repo_root,
        drive_root=drive_root,
        candidate=CANDIDATE_FACEID,
        scenario=canonical,
        character_id=character_id,
        runtime_prepared_root=runtime_prepared_root,
        comfyui_input_dir=comfyui_input_dir,
        bundle_models=bundle_models,
        bundle_nodes=bundle_nodes,
        comfyui_custom_nodes=comfyui_custom_nodes,
        seed=int(baseline["seed"]),
        drive_prepared_root=drive_prepared_root,
        allow_benchmark=True,
        require_models=require_models,
        require_nodes=require_nodes,
        dry_run=False,
    )
    if not base_prep.ok:
        result.errors.extend(base_prep.errors)
        result.messages.extend(base_prep.messages)
        return result

    prep_id = base_prep.preparation_id
    prepared_dir = Path(base_prep.runtime_prepared_dir or base_prep.prepared_dir)
    workflow_path = prepared_dir / f"{prep_id}.workflow.json"
    metadata_path = prepared_dir / f"{prep_id}.metadata.json"
    try:
        bound = json.loads(workflow_path.read_text(encoding="utf-8"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.errors.append(f"ERROR: Unable to read prepared baseline artifacts: {exc}")
        return result

    # Snapshot baseline-bound FaceID widgets before mutation.
    try:
        before = read_faceid_conditioning(bound)
    except ValueError as exc:
        result.errors.append(f"ERROR: {exc}")
        return result
    if (
        float(before["weight"]) != BASELINE_WEIGHT
        or float(before["weight_faceidv2"]) != BASELINE_WEIGHT_FACEIDV2
        or float(before["start_at"]) != BASELINE_START_AT
        or float(before["end_at"]) != BASELINE_END_AT
        or float(before["lora_strength"]) != BASELINE_LORA_STRENGTH
    ):
        result.errors.append(
            "ERROR: Prepared baseline FaceID widgets do not match frozen canonical defaults; "
            f"got {before}"
        )
        return result

    try:
        tuned = apply_faceid_tuning_variant(bound, variant)
        diff_errors = assert_faceid_tuning_graph_diff(bound, tuned, variant)
    except ValueError as exc:
        result.errors.append(f"ERROR: {exc}")
        return result
    if diff_errors:
        result.errors.extend(diff_errors)
        return result

    # Prompt / seed already bound by baseline prep — assert unchanged.
    if str(metadata.get("parameters", {}).get("positive_prompt") or "") != SCENARIO_PROMPTS[canonical]:
        result.errors.append("ERROR: Tuning prep prompt diverged from baseline scenario prompt.")
        return result
    if int(metadata.get("parameters", {}).get("seed") or -1) != int(baseline["seed"]):
        result.errors.append("ERROR: Tuning prep seed diverged from frozen baseline scenario seed.")
        return result

    face_sha = str(metadata.get("character_face_sha256") or "")
    ai = {
        "preparation_id": prep_id,
        "preparation_kind": PREPARATION_KIND_IDENTITY_BENCHMARK_TUNING,
        "benchmark_run": True,
        "benchmark_tuning": True,
        "benchmark_acknowledged": True,
        "benchmark_family": BENCHMARK_FAMILY_IDENTITY_METHOD,
        "benchmark_subtype": BENCHMARK_SUBTYPE_FACEID_CONDITIONING_SWEEP,
        "capability": BENCHMARK_CAPABILITY,
        "candidate": CANDIDATE_FACEID,
        "scenario": canonical,
        "character_id": character_id,
        "baseline_preparation_id": result.baseline_preparation_id,
        "baseline_seed": int(baseline["seed"]),
        "tuning_variant_id": variant.variant_id,
        "tuning_parameters": variant.parameters(),
        "workflow_identifier": "reference/identity_faceid_benchmark",
        "package_version": PACKAGE_VERSION,
        "prepared_workflow_hash": "",
        "canonical_workflow_hash": str(metadata.get("canonical_workflow_hash") or ""),
        "seed": int(baseline["seed"]),
        "seed_mode": "fixed",
        "character_face_sha256": face_sha,
        "character_reference_path": "benchmark_source/primary_face.png",
        "promotion": "pending",
        "quality_claim": "none — prepare/open is plumbing only; visual scenario pass is separate",
    }
    tuned.setdefault("extra", {})
    if not isinstance(tuned.get("extra"), dict):
        tuned["extra"] = {}
    prepared_hash = hash_ui_workflow(tuned)
    ai["prepared_workflow_hash"] = prepared_hash
    tuned["extra"]["ai_studio"] = ai
    # Re-hash after embedding hash field (hash_ui_workflow ignores extra).
    prepared_hash = hash_ui_workflow(tuned)
    ai["prepared_workflow_hash"] = prepared_hash
    tuned["extra"]["ai_studio"] = ai

    workflow_path.write_text(json.dumps(tuned, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    metadata.update(
        {
            "preparation_kind": PREPARATION_KIND_IDENTITY_BENCHMARK_TUNING,
            "benchmark_tuning": True,
            "benchmark_family": BENCHMARK_FAMILY_IDENTITY_METHOD,
            "benchmark_subtype": BENCHMARK_SUBTYPE_FACEID_CONDITIONING_SWEEP,
            "baseline_preparation_id": result.baseline_preparation_id,
            "baseline_seed": int(baseline["seed"]),
            "tuning_variant_id": variant.variant_id,
            "tuning_parameters": variant.parameters(),
            "prepared_workflow_hash": prepared_hash,
            "package_version": PACKAGE_VERSION,
            "promotion": "pending",
            "quality_claim": "none — operational prepare only; visual scenario pass is separate",
            "graph_readiness": "structural_only",
            "parameters": {
                **dict(metadata.get("parameters") or {}),
                "tuning_variant_id": variant.variant_id,
                "tuning_parameters": variant.parameters(),
                "baseline_preparation_id": result.baseline_preparation_id,
            },
        }
    )
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Refresh Drive mirror if present.
    drive_dir = Path(base_prep.drive_prepared_dir) if base_prep.drive_prepared_dir else None
    if drive_dir is not None and drive_dir.is_dir():
        (drive_dir / f"{prep_id}.workflow.json").write_text(
            workflow_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (drive_dir / f"{prep_id}.metadata.json").write_text(
            metadata_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # Append superseding index row so open/capture resolve tuning provenance.
    from .prepared_workflow_index import append_preparation_record, preparations_log_path

    node_count = len(tuned.get("nodes") or [])
    link_count = len(tuned.get("links") or [])
    index_row = {
        "preparation_id": prep_id,
        "preparation_kind": PREPARATION_KIND_IDENTITY_BENCHMARK_TUNING,
        "workflow_identifier": "reference/identity_faceid_benchmark",
        "created_timestamp": utc_now(),
        "created_at": utc_now(),
        "benchmark_run": True,
        "benchmark_tuning": True,
        "benchmark_acknowledged": True,
        "benchmark_family": BENCHMARK_FAMILY_IDENTITY_METHOD,
        "benchmark_subtype": BENCHMARK_SUBTYPE_FACEID_CONDITIONING_SWEEP,
        "candidate": CANDIDATE_FACEID,
        "scenario": canonical,
        "character_id": character_id,
        "baseline_preparation_id": result.baseline_preparation_id,
        "baseline_seed": int(baseline["seed"]),
        "tuning_variant_id": variant.variant_id,
        "tuning_parameters": variant.parameters(),
        "prepared_workflow_path": str(workflow_path),
        "prepared_drive_path": str(drive_dir) if drive_dir else "",
        "runtime_prepared_dir": str(prepared_dir),
        "drive_prepared_dir": str(drive_dir) if drive_dir else "",
        "parameter_summary": {
            "positive_prompt": result.positive_prompt,
            "seed": int(baseline["seed"]),
            "seed_mode": "fixed",
            "tuning_variant_id": variant.variant_id,
            "tuning_parameters": variant.parameters(),
        },
        "prepared_workflow_hash": prepared_hash,
        "canonical_workflow_hash": str(metadata.get("canonical_workflow_hash") or ""),
        "package_version": PACKAGE_VERSION,
        "promotion": "pending",
        "readiness_status": "structural_only",
        "node_count": node_count,
        "link_count": link_count,
        "character_face_sha256": face_sha,
    }
    append_preparation_record(preparations_log_path(drive_root), index_row)

    result.ok = True
    result.preparation_id = prep_id
    result.prepared_dir = str(prepared_dir)
    result.drive_prepared_dir = str(drive_dir) if drive_dir else ""
    result.prepared_workflow_hash = prepared_hash
    result.character_id = character_id
    result.messages.extend(
        [
            f"FaceID tuning preparation ready: {variant.variant_id} ({variant.label})",
            f"scenario={canonical}",
            f"baseline_prep={result.baseline_preparation_id}",
            f"seed={result.seed} (frozen baseline scenario seed)",
            f"prompt={result.positive_prompt}",
            f"tuning_parameters={json.dumps(result.tuning_parameters)}",
            f"preparation_id={prep_id}",
            f"prepared_workflow_hash={prepared_hash}",
            f"graph nodes/links={node_count}/{link_count}",
            "Benchmark-only. Does NOT auto-run. Does NOT quality-benchmark FaceID.",
            "Operational execution pass ≠ visual scenario pass.",
            "FaceID promotion remains pending.",
            "Does NOT overwrite frozen baseline prep IDs or baseline ledger rows.",
        ]
    )
    result.warnings.append(
        "Live visual inspection required. Do not mark S2/S3 pass for identity alone."
    )
    return result


@dataclass
class TuningCaptureResult:
    ok: bool
    skipped_duplicate: bool = False
    skipped_not_tuning: bool = False
    status: str = ""
    record: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def tuning_idempotence_key(prompt_id: str, output_node_id: str, output_sha256: str) -> str:
    return f"{prompt_id}|{output_node_id}|{str(output_sha256 or '').strip().lower()}"


def load_tuning_records(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def find_tuning_ledger_row(
    ledger_path: Path, *, prompt_id: str, output_node_id: str, output_sha256: str
) -> dict[str, Any] | None:
    key = tuning_idempotence_key(prompt_id, output_node_id, output_sha256)
    for row in load_tuning_records(ledger_path):
        if str(row.get("capture_idempotence_key") or "") == key:
            return row
        legacy = tuning_idempotence_key(
            str(row.get("prompt_id") or ""),
            str(row.get("output_node_id") or ""),
            str(row.get("output_sha256") or ""),
        )
        if legacy == key:
            return row
    return None


def append_tuning_record_if_absent(ledger_path: Path, record: dict[str, Any], *, key: str) -> tuple[bool, bool]:
    with exclusive_jsonl_lock(ledger_path):
        for row in load_tuning_records(ledger_path):
            if str(row.get("capture_idempotence_key") or "") == key:
                return True, True
        if not record.get("created_at"):
            record["created_at"] = utc_now()
        append_jsonl_line_unlocked(ledger_path, json.dumps(record, ensure_ascii=False))
        return True, False


def format_tuning_report(records: list[dict[str, Any]]) -> str:
    lines = [
        "FaceID conditioning sweep report (Package 4.12.2)",
        "Operational execution ≠ visual scenario pass. Promotion=pending.",
        f"Records: {len(records)}",
        "",
    ]
    for row in records:
        lines.append(
            f"- {row.get('tuning_variant_id')} / {row.get('scenario')} "
            f"prep={row.get('preparation_id')} prompt={row.get('prompt_id')} "
            f"sha={(str(row.get('output_sha256') or '')[:16] + '…') if row.get('output_sha256') else '—'} "
            f"human_review={row.get('human_review_status') or 'pending'} "
            f"promotion={row.get('promotion') or 'pending'}"
        )
    return "\n".join(lines)


def build_tuning_human_review(scenario: str) -> dict[str, str]:
    return {k: "pending" for k in tuning_rubric_for_scenario(scenario)}


def capture_faceid_tuning_execution(
    *,
    drive_root: Path,
    ledger_path: Path,
    prompt_id: str,
    output_node_id: str,
    output_path: Path,
    output_sha256: str,
    provenance: Any,
    ui_workflow: dict[str, Any] | None,
    local_path: str = "",
    ensure_durable: bool = True,
    drive_output_dir: Path | None = None,
    evidence_path: Path | None = None,
) -> TuningCaptureResult:
    """Append one FaceID conditioning-sweep row. Never writes identity_benchmark.jsonl."""
    from .identity_benchmark_capture import (
        STATUS_CAPTURED,
        STATUS_DUPLICATE_REUSED_LEDGER_ARTIFACT,
        ensure_durable_benchmark_artifact,
        verify_existing_ledger_artifact,
    )
    from .workflow_provenance import extract_ai_studio_extra

    result = TuningCaptureResult(ok=False)
    ai = extract_ai_studio_extra(ui_workflow) if ui_workflow else {}
    meta = dict(ai) if isinstance(ai, dict) else {}
    if provenance is not None:
        meta.setdefault("preparation_kind", getattr(provenance, "preparation_kind", "") or "")
        meta.setdefault("benchmark_tuning", getattr(provenance, "benchmark_tuning", None))
    if not is_identity_benchmark_tuning_metadata(meta):
        # Also accept provenance.preparation_kind directly.
        kind = str(getattr(provenance, "preparation_kind", "") or "")
        if kind != PREPARATION_KIND_IDENTITY_BENCHMARK_TUNING and not meta.get("benchmark_tuning"):
            result.skipped_not_tuning = True
            result.ok = True
            result.messages.append("Not a FaceID tuning execution; skipped.")
            return result

    if not prompt_id or not output_node_id:
        result.errors.append("ERROR: prompt_id and output_node_id are required for tuning capture.")
        return result

    source = Path(output_path)
    sha = str(output_sha256 or "").strip().lower()
    runtime_local = local_path or (str(source) if source.is_file() else "")
    if not sha:
        if not source.is_file():
            result.errors.append(f"ERROR: Tuning output missing and no SHA provided: {source}")
            return result
        try:
            sha = file_sha256(source).lower()
        except OSError as exc:
            result.errors.append(f"ERROR: Unable to hash tuning output: {exc}")
            return result
    if source.is_file():
        try:
            actual = file_sha256(source).lower()
        except OSError as exc:
            result.errors.append(f"ERROR: Unable to read tuning output for SHA: {exc}")
            return result
        if actual != sha:
            result.errors.append(
                f"ERROR: Tuning output SHA mismatch (expected {sha}, actual {actual})"
            )
            return result

    executed_seed = getattr(provenance, "seed", None)
    if executed_seed is None and isinstance(ai, dict) and ai.get("seed") is not None:
        executed_seed = ai.get("seed")
    if executed_seed is None:
        result.errors.append("ERROR: Executed seed missing from tuning provenance.")
        return result

    preparation_id = str(
        (ai.get("preparation_id") if isinstance(ai, dict) else None)
        or getattr(provenance, "preparation_id", "")
        or ""
    ).strip()
    scenario = str((ai.get("scenario") if isinstance(ai, dict) else "") or "").strip()
    character_id = str((ai.get("character_id") if isinstance(ai, dict) else "") or "").strip()
    variant_id = str((ai.get("tuning_variant_id") if isinstance(ai, dict) else "") or "").strip()
    baseline_prep = str(
        (ai.get("baseline_preparation_id") if isinstance(ai, dict) else "") or ""
    ).strip()
    baseline_seed = ai.get("baseline_seed") if isinstance(ai, dict) else None
    tuning_parameters = (
        ai.get("tuning_parameters") if isinstance(ai, dict) and isinstance(ai.get("tuning_parameters"), dict) else {}
    )
    if not preparation_id or not scenario or not character_id or not variant_id:
        result.errors.append(
            "ERROR: Tuning capture requires preparation_id, scenario, character_id, tuning_variant_id."
        )
        return result

    key = tuning_idempotence_key(prompt_id, output_node_id, sha)
    existing = find_tuning_ledger_row(
        ledger_path, prompt_id=prompt_id, output_node_id=output_node_id, output_sha256=sha
    )
    if existing is not None:
        status, _path, msgs, errs = verify_existing_ledger_artifact(existing, expected_sha256=sha)
        result.messages.extend(msgs)
        result.status = status
        if status == STATUS_DUPLICATE_REUSED_LEDGER_ARTIFACT:
            result.ok = True
            result.skipped_duplicate = True
            result.record = dict(existing)
            result.messages.append(f"Already captured tuning (idempotent, pre-persistence): {key}")
            return result
        result.ok = False
        result.errors.extend(errs)
        return result

    durable_path = source
    durable_sha = sha
    if ensure_durable:
        durable = ensure_durable_benchmark_artifact(
            drive_root=drive_root,
            source_path=source,
            prompt_id=prompt_id,
            output_node_id=output_node_id,
            source_sha256=sha,
            drive_output_dir=drive_output_dir,
            evidence_path=evidence_path,
        )
        result.messages.extend(durable.messages)
        if not durable.ok or durable.drive_path is None:
            result.errors.extend(durable.errors or ["ERROR: Durable Drive artifact unavailable."])
            return result
        durable_path = durable.drive_path
        durable_sha = durable.drive_sha256
        if durable_sha != sha:
            result.errors.append(
                f"ERROR: Durable SHA must equal source SHA (expected {sha}, got {durable_sha})."
            )
            return result

    record = {
        "candidate": CANDIDATE_FACEID,
        "scenario": scenario,
        "character_id": character_id,
        "baseline_preparation_id": baseline_prep,
        "baseline_seed": int(baseline_seed) if baseline_seed is not None else None,
        "tuning_variant_id": variant_id,
        "tuning_parameters": dict(tuning_parameters),
        "preparation_id": preparation_id,
        "preparation_kind": PREPARATION_KIND_IDENTITY_BENCHMARK_TUNING,
        "benchmark_run": True,
        "benchmark_tuning": True,
        "benchmark_family": BENCHMARK_FAMILY_IDENTITY_METHOD,
        "benchmark_subtype": BENCHMARK_SUBTYPE_FACEID_CONDITIONING_SWEEP,
        "prompt_id": prompt_id,
        "output_node_id": output_node_id,
        "output_path": str(durable_path),
        "output_sha256": durable_sha,
        "local_path": runtime_local,
        "executed_seed": int(executed_seed),
        "execution_success": True,
        "human_review": build_tuning_human_review(scenario),
        "human_review_status": "pending",
        "scenario_adherence": "pending",
        "identity_similarity": "pending",
        "facial_naturalness": "pending",
        "notes": [
            "FaceID conditioning sweep capture — operational only",
            "not an ordinary generation record",
            "not a baseline identity_benchmark ledger row",
            "visual scenario pass requires human review",
        ],
        "promotion": "pending",
        "package_version": PACKAGE_VERSION,
        "capture_idempotence_key": key,
        "created_at": utc_now(),
    }
    try:
        _ok, skipped_dup = append_tuning_record_if_absent(ledger_path, record, key=key)
    except TimeoutError as exc:
        result.errors.append(f"ERROR: {exc}")
        return result
    if not _ok:
        result.errors.append("ERROR: Failed to append tuning ledger row.")
        return result
    if skipped_dup:
        result.ok = True
        result.skipped_duplicate = True
        result.status = STATUS_DUPLICATE_REUSED_LEDGER_ARTIFACT
        result.record = find_tuning_ledger_row(
            ledger_path, prompt_id=prompt_id, output_node_id=output_node_id, output_sha256=sha
        )
        result.messages.append(f"Tuning ledger race: reused existing row for {key}")
        return result

    result.ok = True
    result.status = STATUS_CAPTURED
    result.record = record
    result.messages.append(
        f"Captured FaceID tuning execution: {variant_id}/{scenario} "
        f"prep={preparation_id} prompt={prompt_id} output={durable_path}"
    )
    return result
