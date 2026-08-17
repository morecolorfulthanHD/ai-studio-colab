#!/usr/bin/env python3
"""Generation → reproduction preparation (Package 4.10).

Creates a NEW prep_<uuid> from an executed generation snapshot. Never mutates
the source generation or the original preparation. Never auto-executes.

Source-of-truth priority:
  1. generation snapshot workflow.json (api_prompt / ui_workflow)
  2. generation metadata execution values
  3. canonical workflow reconstruction only for compatible schema defaults
     that do not override executed values

Batch policy (Package 4.10 hardening):
  Generation records distinguish batch members by local filename / SHA / dedupe
  key, not by a preserved latent batch index. Isolated single-member
  reconstruction via batch_size=1 is therefore not proven.

  - Recoverable batch_size == 1 → reproduction_scope = single_generation
  - Recoverable batch_size > 1 → reproduction_scope = source_batch_execution
    (preserve original batch_size; warn that the full batch will regenerate)
  - Unrecoverable batch_size → refuse (do not guess batch_size=1)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .generation_identity import (
    InvalidGenerationIdError,
    format_generation_not_found,
    normalize_generation_id,
)
from .generation_snapshot import (
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    WORKFLOW_FILENAME,
    load_snapshot_by_id,
)
from .preparation_project_context import PreparationProjectContext, resolve_preparation_project
from .project_workspace import ProjectManifest
from .seed_mode import (
    CONTROL_AFTER_GENERATE_FIXED,
    SEED_MODE_FIXED,
    coerce_execution_seed,
)
from .workflow_library_preparation import (
    LibraryPreparationResult,
    prepare_library_workflow,
)

PACKAGE_VERSION = "4.10"
PREPARATION_KIND_ORDINARY = "ordinary"
PREPARATION_KIND_GENERATION_REPRODUCTION = "generation_reproduction"

REPRODUCTION_SCOPE_SINGLE = "single_generation"
REPRODUCTION_SCOPE_SOURCE_BATCH = "source_batch_execution"

# Preferred Package 4.10 production scope.
SUPPORTED_REPRODUCTION_IDENTIFIERS = frozenset({"base/txt2img"})

REQUIRED_TXT2IMG_KEYS = (
    "positive_prompt",
    "seed",
    "steps",
    "cfg",
    "sampler_name",
    "scheduler",
    "width",
    "height",
    "checkpoint",
)

INSUFFICIENT_STATE_ERROR = (
    "ERROR: Generation does not contain sufficient executed workflow state "
    "for deterministic reproduction."
)


def should_prompt_open_reproduction_preparation(
    *,
    lookup_ok: bool,
    prepare_ok: bool,
    preparation_id: str = "",
) -> bool:
    """Prompt to open a reproduction prep only after one was actually created."""
    if not lookup_ok or not prepare_ok:
        return False
    text = str(preparation_id or "").strip()
    if text:
        return text.lower().startswith("prep_")
    return True

BATCH_STATE_UNRECOVERABLE_ERROR = (
    "ERROR: Source generation came from a multi-image execution whose batch "
    "state cannot be reconstructed deterministically."
)

BATCH_SIZE_REQUIRED_ERROR = (
    "ERROR: Generation does not contain recoverable batch_size for "
    "deterministic reproduction."
)


@dataclass
class ReproductionEligibility:
    eligible: bool
    reason: str
    workflow_snapshot_status: str = "unavailable"
    snapshot_status: str = "unavailable"
    workflow_identifier: str = ""
    missing_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReproductionResult:
    ok: bool
    generation_id: str = ""
    preparation_id: str = ""
    workflow_identifier: str = ""
    preparation_kind: str = PREPARATION_KIND_GENERATION_REPRODUCTION
    parameters: dict[str, Any] = field(default_factory=dict)
    lineage: dict[str, Any] = field(default_factory=dict)
    eligibility: ReproductionEligibility | None = None
    preparation: LibraryPreparationResult | None = None
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_batch_size: int | None = None
    reproduction_batch_size: int | None = None
    reproduction_scope: str = ""
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "generation_id": self.generation_id,
            "preparation_id": self.preparation_id,
            "workflow_identifier": self.workflow_identifier,
            "preparation_kind": self.preparation_kind,
            "parameters": self.parameters,
            "lineage": self.lineage,
            "eligibility": self.eligibility.to_dict() if self.eligibility else None,
            "messages": self.messages,
            "errors": self.errors,
            "warnings": self.warnings,
            "source_batch_size": self.source_batch_size,
            "reproduction_batch_size": self.reproduction_batch_size,
            "reproduction_scope": self.reproduction_scope,
            "dry_run": self.dry_run,
        }
        if self.preparation is not None:
            payload["preparation"] = self.preparation.to_dict()
        return payload


def reproduction_save_prefix(generation_id: str) -> str:
    """Deterministic ComfyUI Save Image prefix for reproduction preps.

    Uses a short generation-id fragment. Does not affect permanent Drive naming
    (autosync still assigns txt2img_<date>_<seq>.png).
    """
    canonical = normalize_generation_id(generation_id)
    uuid_part = canonical[len("gen_") :]
    short = uuid_part.replace("-", "")[:8]
    return f"ai_studio_repro_{short}"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _nodes_by_type(api_prompt: dict[str, Any], class_type: str) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for node_id, node in api_prompt.items():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type") or "") == class_type:
            found.append((str(node_id), node))
    return found


def _ui_node(ui_workflow: dict[str, Any] | None, node_id: str) -> dict[str, Any] | None:
    if not isinstance(ui_workflow, dict):
        return None
    for node in ui_workflow.get("nodes") or []:
        if isinstance(node, dict) and str(node.get("id")) == str(node_id):
            return node
    return None


def _ui_widgets(ui_workflow: dict[str, Any] | None, node_id: str) -> list[Any]:
    node = _ui_node(ui_workflow, node_id)
    if not node:
        return []
    widgets = node.get("widgets_values")
    return list(widgets) if isinstance(widgets, list) else []


def extract_batch_size(
    *,
    api_prompt: dict[str, Any] | None = None,
    ui_workflow: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> int | None:
    if isinstance(api_prompt, dict) and api_prompt:
        for _, node in _nodes_by_type(api_prompt, "EmptyLatentImage"):
            inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
            raw = inputs.get("batch_size")
            if isinstance(raw, bool):
                continue
            if isinstance(raw, int) and raw >= 1:
                return raw
            if isinstance(raw, float) and raw.is_integer() and raw >= 1:
                return int(raw)
    widgets = _ui_widgets(ui_workflow, "5")
    if len(widgets) >= 3:
        raw = widgets[2]
        if isinstance(raw, bool):
            pass
        elif isinstance(raw, int) and raw >= 1:
            return raw
        elif isinstance(raw, float) and raw.is_integer() and raw >= 1:
            return int(raw)
    if isinstance(metadata, dict):
        raw = metadata.get("batch_size")
        if isinstance(raw, int) and raw >= 1:
            return raw
    return None


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip() and value != "":
            # empty string for prompts may still be meaningful; allow ""
            continue
        if isinstance(value, str) and value.strip() == "" and value != "":
            continue
        return value
    return None


def _api_text(api_prompt: dict[str, Any] | None, node_id: str) -> str | None:
    if not isinstance(api_prompt, dict):
        return None
    node = api_prompt.get(str(node_id))
    if not isinstance(node, dict):
        return None
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    text = inputs.get("text")
    return text if isinstance(text, str) else None


def _api_sampler(api_prompt: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(api_prompt, dict):
        return {}
    for _, node in _nodes_by_type(api_prompt, "KSampler"):
        inputs = node.get("inputs")
        return dict(inputs) if isinstance(inputs, dict) else {}
    return {}


def _api_checkpoint(api_prompt: dict[str, Any] | None) -> str | None:
    if not isinstance(api_prompt, dict):
        return None
    for _, node in _nodes_by_type(api_prompt, "CheckpointLoaderSimple"):
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        name = inputs.get("ckpt_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _api_latent(api_prompt: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(api_prompt, dict):
        return {}
    for _, node in _nodes_by_type(api_prompt, "EmptyLatentImage"):
        inputs = node.get("inputs")
        return dict(inputs) if isinstance(inputs, dict) else {}
    return {}


def resolve_reproduction_batch_policy(
    source_batch: int | None,
) -> tuple[str | None, int | None, str | None]:
    """Return (reproduction_scope, reproduction_batch_size, error_message).

    Isolated single-image reproduction from a multi-image batch is not proven:
    snapshots do not preserve a latent batch-member index that would make
    batch_size=1 reconstruct the selected artifact.
    """
    if source_batch is None:
        return None, None, BATCH_SIZE_REQUIRED_ERROR
    if not isinstance(source_batch, int) or source_batch < 1:
        return None, None, BATCH_SIZE_REQUIRED_ERROR
    if source_batch == 1:
        return REPRODUCTION_SCOPE_SINGLE, 1, None
    return REPRODUCTION_SCOPE_SOURCE_BATCH, source_batch, None


def batch_scope_warning(source_batch: int) -> str:
    return (
        f"Source generation is one image from a batch_size={source_batch} execution. "
        "Exact isolated reproduction of this single batch member is not supported "
        "because per-image latent identity is not preserved. This reproduction will "
        f"regenerate the original {source_batch}-image batch."
    )


def extract_executed_txt2img_parameters(
    *,
    metadata: dict[str, Any],
    workflow_payload: dict[str, Any],
    generation_id: str,
) -> tuple[dict[str, Any], list[str], int | None]:
    """Build preparation parameters from executed generation state.

    Returns (parameters, missing_required_keys, source_batch_size).
    ``parameters['batch_size']`` is set only when source batch size is recoverable;
    callers must apply resolve_reproduction_batch_policy before prepare.
    """
    api_prompt = workflow_payload.get("api_prompt")
    api_prompt = api_prompt if isinstance(api_prompt, dict) else None
    ui_workflow = workflow_payload.get("ui_workflow")
    ui_workflow = ui_workflow if isinstance(ui_workflow, dict) else None

    sampler = _api_sampler(api_prompt)
    latent = _api_latent(api_prompt)
    ksampler_widgets = _ui_widgets(ui_workflow, "3")
    latent_widgets = _ui_widgets(ui_workflow, "5")
    prompt_widgets = _ui_widgets(ui_workflow, "6")
    negative_widgets = _ui_widgets(ui_workflow, "7")
    ckpt_widgets = _ui_widgets(ui_workflow, "4")

    positive = _first_non_empty(
        _api_text(api_prompt, "6"),
        prompt_widgets[0] if prompt_widgets else None,
        metadata.get("positive_prompt"),
    )
    negative = _first_non_empty(
        _api_text(api_prompt, "7"),
        negative_widgets[0] if negative_widgets else None,
        metadata.get("negative_prompt"),
        "",
    )
    seed = coerce_execution_seed(
        _first_non_empty(
            sampler.get("seed"),
            ksampler_widgets[0] if ksampler_widgets else None,
            metadata.get("seed"),
        )
    )
    steps = _first_non_empty(
        sampler.get("steps") if isinstance(sampler.get("steps"), int) else None,
        ksampler_widgets[2] if len(ksampler_widgets) > 2 else None,
        metadata.get("steps"),
    )
    cfg = _first_non_empty(
        float(sampler["cfg"]) if isinstance(sampler.get("cfg"), (int, float)) else None,
        ksampler_widgets[3] if len(ksampler_widgets) > 3 else None,
        metadata.get("cfg"),
    )
    sampler_name = _first_non_empty(
        sampler.get("sampler_name"),
        ksampler_widgets[4] if len(ksampler_widgets) > 4 else None,
        metadata.get("sampler_name"),
    )
    scheduler = _first_non_empty(
        sampler.get("scheduler"),
        ksampler_widgets[5] if len(ksampler_widgets) > 5 else None,
        metadata.get("scheduler"),
    )
    width = _first_non_empty(
        latent.get("width") if isinstance(latent.get("width"), int) else None,
        latent_widgets[0] if latent_widgets else None,
        metadata.get("width"),
    )
    height = _first_non_empty(
        latent.get("height") if isinstance(latent.get("height"), int) else None,
        latent_widgets[1] if len(latent_widgets) > 1 else None,
        metadata.get("height"),
    )
    checkpoint = _first_non_empty(
        _api_checkpoint(api_prompt),
        ckpt_widgets[0] if ckpt_widgets else None,
        (metadata.get("model_files") or [None])[0]
        if isinstance(metadata.get("model_files"), list)
        else None,
    )

    source_batch = extract_batch_size(api_prompt=api_prompt, ui_workflow=ui_workflow, metadata=metadata)
    scope, repro_batch, _batch_err = resolve_reproduction_batch_policy(source_batch)

    params: dict[str, Any] = {
        "positive_prompt": positive if isinstance(positive, str) else None,
        "negative_prompt": negative if isinstance(negative, str) else "",
        "seed": seed,
        "seed_mode": SEED_MODE_FIXED,
        "control_after_generate": CONTROL_AFTER_GENERATE_FIXED,
        "steps": int(steps) if isinstance(steps, (int, float)) and not isinstance(steps, bool) else None,
        "cfg": float(cfg) if isinstance(cfg, (int, float)) and not isinstance(cfg, bool) else None,
        "sampler_name": str(sampler_name).strip() if sampler_name not in (None, "") else None,
        "scheduler": str(scheduler).strip() if scheduler not in (None, "") else None,
        "width": int(width) if isinstance(width, (int, float)) and not isinstance(width, bool) else None,
        "height": int(height) if isinstance(height, (int, float)) and not isinstance(height, bool) else None,
        "checkpoint": str(checkpoint).strip() if checkpoint not in (None, "") else None,
        "save_prefix": reproduction_save_prefix(generation_id),
    }
    if repro_batch is not None:
        params["batch_size"] = repro_batch

    missing = [key for key in REQUIRED_TXT2IMG_KEYS if params.get(key) in (None, "")]
    if source_batch is None or scope is None:
        missing.append("batch_size")
    return params, missing, source_batch


def assess_reproduction_eligibility(
    *,
    metadata: dict[str, Any],
    workflow_payload: dict[str, Any],
    manifest: dict[str, Any] | None = None,
) -> ReproductionEligibility:
    workflow_status = str(
        workflow_payload.get("workflow_snapshot_status")
        or metadata.get("workflow_snapshot_status")
        or "unavailable"
    )
    snapshot_status = str((manifest or {}).get("snapshot_status") or "unavailable")
    identifier = str(
        metadata.get("workflow_identifier")
        or metadata.get("canonical_workflow_identifier")
        or workflow_payload.get("workflow_identifier")
        or ""
    ).strip()

    warnings: list[str] = []
    if not identifier or identifier == "unknown":
        return ReproductionEligibility(
            eligible=False,
            reason=INSUFFICIENT_STATE_ERROR,
            workflow_snapshot_status=workflow_status,
            snapshot_status=snapshot_status,
            workflow_identifier=identifier,
            missing_fields=["workflow_identifier"],
        )

    if identifier not in SUPPORTED_REPRODUCTION_IDENTIFIERS:
        return ReproductionEligibility(
            eligible=False,
            reason=(
                f"ERROR: Deterministic reproduction for workflow '{identifier}' "
                "is not supported in Package 4.10 (base/txt2img only)."
            ),
            workflow_snapshot_status=workflow_status,
            snapshot_status=snapshot_status,
            workflow_identifier=identifier,
        )

    api_available = bool(workflow_payload.get("api_prompt_available")) and isinstance(
        workflow_payload.get("api_prompt"), dict
    )
    ui_available = bool(workflow_payload.get("ui_workflow_available")) and isinstance(
        workflow_payload.get("ui_workflow"), dict
    )

    if workflow_status == "unavailable" and not api_available and not ui_available:
        return ReproductionEligibility(
            eligible=False,
            reason=INSUFFICIENT_STATE_ERROR,
            workflow_snapshot_status=workflow_status,
            snapshot_status=snapshot_status,
            workflow_identifier=identifier,
            missing_fields=["workflow.json executed state"],
        )

    # Probe required params without allocating a prep id.
    probe_gid = str(metadata.get("generation_id") or "gen_00000000-0000-0000-0000-000000000000")
    try:
        normalize_generation_id(probe_gid)
    except InvalidGenerationIdError:
        probe_gid = "gen_00000000-0000-0000-0000-000000000000"
    _params, missing, source_batch = extract_executed_txt2img_parameters(
        metadata=metadata,
        workflow_payload=workflow_payload,
        generation_id=probe_gid,
    )
    scope, _repro_batch, batch_err = resolve_reproduction_batch_policy(source_batch)
    if batch_err:
        # Prefer the explicit batch error when batch_size is the blocker.
        other_missing = [m for m in missing if m != "batch_size"]
        if not other_missing:
            return ReproductionEligibility(
                eligible=False,
                reason=batch_err,
                workflow_snapshot_status=workflow_status,
                snapshot_status=snapshot_status,
                workflow_identifier=identifier,
                missing_fields=["batch_size"],
            )

    if missing:
        return ReproductionEligibility(
            eligible=False,
            reason=INSUFFICIENT_STATE_ERROR,
            workflow_snapshot_status=workflow_status,
            snapshot_status=snapshot_status,
            workflow_identifier=identifier,
            missing_fields=missing,
        )

    if workflow_status == "partial":
        warnings.append(
            "Source workflow snapshot is partial; reproduction used recoverable "
            "executed parameters only (no fabricated nodes)."
        )
    if scope == REPRODUCTION_SCOPE_SOURCE_BATCH and source_batch is not None:
        warnings.append(batch_scope_warning(source_batch))

    return ReproductionEligibility(
        eligible=True,
        reason="eligible",
        workflow_snapshot_status=workflow_status,
        snapshot_status=snapshot_status,
        workflow_identifier=identifier,
        warnings=warnings,
    )


def build_reproduction_lineage(
    *,
    generation_id: str,
    snapshot_root: Path,
    metadata: dict[str, Any],
    workflow_payload: dict[str, Any],
    eligibility: ReproductionEligibility,
    source_batch_size: int | None,
    reproduction_scope: str,
    source_output_index: int | None = None,
) -> dict[str, Any]:
    def _null(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    return {
        "preparation_kind": PREPARATION_KIND_GENERATION_REPRODUCTION,
        "reproduction_source_generation_id": generation_id,
        "reproduction_source_snapshot_path": str(snapshot_root),
        "reproduction_source_image_sha256": _null(metadata.get("image_sha256")),
        "reproduction_source_prompt_id": _null(metadata.get("prompt_id")),
        "reproduction_source_preparation_id": _null(metadata.get("preparation_id")),
        "reproduction_source_workflow_identifier": _null(
            metadata.get("workflow_identifier")
            or metadata.get("canonical_workflow_identifier")
            or workflow_payload.get("workflow_identifier")
        ),
        "reproduction_source_snapshot_status": _null(eligibility.snapshot_status),
        "reproduction_source_workflow_snapshot_status": _null(
            eligibility.workflow_snapshot_status
        ),
        "source_batch_size": source_batch_size,
        "source_output_index": source_output_index,
        "reproduction_scope": reproduction_scope or None,
    }


def prepare_from_generation(
    repo_root: Path,
    *,
    generation_id: str,
    runtime_prepared_root: Path,
    drive_prepared_root: Path,
    comfyui_input_dir: Path,
    drive_root: Path,
    use_global: bool = False,
    project_ref: str | None = None,
    dry_run: bool = False,
    allowed_input_roots: list[Path] | None = None,
    comfy_object_info: dict[str, Any] | None = None,
    model_files_present: dict[str, bool] | None = None,
    active_project: ProjectManifest | None = None,
    project_context: PreparationProjectContext | None = None,
) -> ReproductionResult:
    """Create a new fixed reproduction preparation from a generation snapshot."""
    result = ReproductionResult(ok=False, dry_run=dry_run)
    try:
        canonical_gid = normalize_generation_id(generation_id)
    except InvalidGenerationIdError as exc:
        result.errors.append(str(exc))
        return result
    result.generation_id = canonical_gid

    try:
        manifest = load_snapshot_by_id(drive_root, canonical_gid)
    except InvalidGenerationIdError as exc:
        result.errors.append(str(exc))
        return result
    if manifest is None:
        result.errors.append(format_generation_not_found(canonical_gid))
        return result

    snapshot_root = Path(str(manifest.get("snapshot_root") or ""))
    metadata = _load_json(snapshot_root / METADATA_FILENAME)
    workflow_payload = _load_json(snapshot_root / WORKFLOW_FILENAME)
    if not metadata:
        result.errors.append(INSUFFICIENT_STATE_ERROR)
        result.errors.append("Missing or unreadable generation metadata.json")
        return result

    eligibility = assess_reproduction_eligibility(
        metadata=metadata,
        workflow_payload=workflow_payload,
        manifest=manifest,
    )
    result.eligibility = eligibility
    result.warnings.extend(eligibility.warnings)
    if not eligibility.eligible:
        result.errors.append(eligibility.reason)
        if eligibility.missing_fields:
            result.errors.append(
                "Missing required executed fields: " + ", ".join(eligibility.missing_fields)
            )
        return result

    params, missing, source_batch = extract_executed_txt2img_parameters(
        metadata=metadata,
        workflow_payload=workflow_payload,
        generation_id=canonical_gid,
    )
    scope, repro_batch, batch_err = resolve_reproduction_batch_policy(source_batch)
    result.source_batch_size = source_batch
    result.reproduction_batch_size = repro_batch
    result.reproduction_scope = scope or ""
    if batch_err and (not missing or missing == ["batch_size"]):
        result.errors.append(batch_err)
        return result
    if missing:
        result.errors.append(INSUFFICIENT_STATE_ERROR)
        result.errors.append("Missing required executed fields: " + ", ".join(missing))
        return result
    if scope is None or repro_batch is None:
        result.errors.append(batch_err or BATCH_SIZE_REQUIRED_ERROR)
        return result

    # Proven meaning only: current snapshots do not store a latent batch index.
    source_output_index = metadata.get("source_output_index")
    if not isinstance(source_output_index, int):
        source_output_index = None

    lineage = build_reproduction_lineage(
        generation_id=canonical_gid,
        snapshot_root=snapshot_root,
        metadata=metadata,
        workflow_payload=workflow_payload,
        eligibility=eligibility,
        source_batch_size=source_batch,
        reproduction_scope=scope,
        source_output_index=source_output_index,
    )
    result.lineage = lineage
    result.parameters = params
    result.workflow_identifier = eligibility.workflow_identifier

    if project_context is None and active_project is None:
        try:
            project_context = resolve_preparation_project(
                drive_root,
                use_global=use_global,
                project_ref=project_ref,
            )
        except ValueError as exc:
            result.errors.append(f"ERROR: {exc}")
            return result
    project = active_project
    if project is None and project_context is not None:
        project = project_context.project

    # Never silently use archived/stale projects (resolve_preparation_project already guards).
    if project is not None and hasattr(project, "is_archived") and project.is_archived():
        result.errors.append(
            f"ERROR: Project is archived and cannot receive preparations: {project.slug}"
        )
        return result

    prep = prepare_library_workflow(
        repo_root,
        workflow_identifier=eligibility.workflow_identifier,
        parameters=params,
        runtime_prepared_root=runtime_prepared_root,
        drive_prepared_root=drive_prepared_root,
        comfyui_input_dir=comfyui_input_dir,
        drive_root=drive_root,
        active_project=project,
        dry_run=dry_run,
        allowed_input_roots=allowed_input_roots,
        comfy_object_info=comfy_object_info,
        model_files_present=model_files_present,
        preparation_kind=PREPARATION_KIND_GENERATION_REPRODUCTION,
        lineage_metadata=lineage,
        package_version=PACKAGE_VERSION,
    )
    result.preparation = prep
    result.preparation_id = prep.preparation_id
    result.messages.extend(prep.messages)
    result.errors.extend(prep.errors)
    result.warnings.extend(
        msg for msg in prep.messages if msg.upper().startswith("WARNING")
    )
    result.ok = prep.ok
    if prep.ok:
        result.messages.append(
            "Reproduction preparation created (fixed seed; open prepared workflow "
            "to inspect and manually Run — no automatic execution)."
        )
        if scope == REPRODUCTION_SCOPE_SOURCE_BATCH and source_batch is not None:
            result.messages.append(
                f"Source generation is part of a batch execution:\n"
                f"  source batch size: {source_batch}\n"
                f"Reproduction scope:\n"
                f"  original batch execution\n"
                f"This preparation will generate {source_batch} images when manually Run."
            )
    return result


def compare_generation_to_preparation(
    *,
    generation_metadata: dict[str, Any],
    generation_workflow: dict[str, Any],
    preparation_metadata: dict[str, Any],
    preparation_workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only comparison of source generation vs reproduction preparation."""
    del preparation_workflow  # reserved for future structural graph diff
    gid = str(generation_metadata.get("generation_id") or "")
    params, _missing, source_batch = extract_executed_txt2img_parameters(
        metadata=generation_metadata,
        workflow_payload=generation_workflow,
        generation_id=gid or "gen_00000000-0000-0000-0000-000000000000",
    )
    scope, expected_batch, _batch_err = resolve_reproduction_batch_policy(source_batch)
    prep_params = preparation_metadata.get("parameters")
    prep_params = prep_params if isinstance(prep_params, dict) else {}
    prep_scope = str(
        preparation_metadata.get("reproduction_scope")
        or (prep_params.get("reproduction_scope") if isinstance(prep_params, dict) else "")
        or ""
    ).strip()

    def _cmp(key: str, left: Any, right: Any) -> dict[str, Any]:
        return {"field": key, "match": left == right, "source": left, "preparation": right}

    checks = [
        _cmp(
            "workflow_identifier",
            generation_metadata.get("workflow_identifier")
            or generation_metadata.get("canonical_workflow_identifier"),
            preparation_metadata.get("workflow_identifier"),
        ),
        _cmp("positive_prompt", params.get("positive_prompt"), prep_params.get("positive_prompt")),
        _cmp("negative_prompt", params.get("negative_prompt"), prep_params.get("negative_prompt")),
        _cmp("seed", params.get("seed"), prep_params.get("seed") or preparation_metadata.get("seed")),
        _cmp("seed_mode", SEED_MODE_FIXED, prep_params.get("seed_mode") or preparation_metadata.get("seed_mode")),
        _cmp(
            "control_after_generate",
            CONTROL_AFTER_GENERATE_FIXED,
            prep_params.get("control_after_generate")
            or preparation_metadata.get("control_after_generate"),
        ),
        _cmp("steps", params.get("steps"), prep_params.get("steps")),
        _cmp("cfg", params.get("cfg"), prep_params.get("cfg")),
        _cmp("sampler_name", params.get("sampler_name"), prep_params.get("sampler_name")),
        _cmp("scheduler", params.get("scheduler"), prep_params.get("scheduler")),
        _cmp("checkpoint", params.get("checkpoint"), prep_params.get("checkpoint")),
        _cmp("width", params.get("width"), prep_params.get("width")),
        _cmp("height", params.get("height"), prep_params.get("height")),
        _cmp("batch_size", expected_batch, prep_params.get("batch_size")),
        _cmp(
            "reproduction_scope",
            scope,
            prep_scope or preparation_metadata.get("reproduction_scope"),
        ),
        _cmp(
            "source_batch_size",
            source_batch,
            preparation_metadata.get("source_batch_size"),
        ),
    ]
    lineage_ok = (
        preparation_metadata.get("preparation_kind") == PREPARATION_KIND_GENERATION_REPRODUCTION
        and preparation_metadata.get("reproduction_source_generation_id") == gid
    )
    return {
        "all_match": all(item["match"] for item in checks) and lineage_ok,
        "lineage_ok": lineage_ok,
        "source_batch_size": source_batch,
        "expected_batch_size": expected_batch,
        "reproduction_scope": scope,
        "checks": checks,
        "preparation_kind": preparation_metadata.get("preparation_kind"),
        "reproduction_source_generation_id": preparation_metadata.get(
            "reproduction_source_generation_id"
        ),
    }
