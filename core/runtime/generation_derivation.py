#!/usr/bin/env python3
"""Generation → derivation preparation (Package 4.11).

Creates a NEW prep_<uuid> img2img variation from a verified generation artifact.
Never mutates the source generation, snapshot, or original preparation.
Never auto-executes.

Primary creative parentage:
  derived_from_generation_id = parent generation (lineage only)

Primary img2img source asset (Package 4.11):
  verified permanent PNG → SHA verify → prep-scoped archive → ComfyUI input staging

Durable archive identity is preparation-relative:
  derivation_source/derivation_source.png
resolved against whichever preparation archive is in use (runtime, Drive, project).

Future conditioning assets (identity references, masks, etc.) are intentionally
NOT modeled here; derivation_source_* fields describe the primary parent-generation
image only so Package 4.12+ can add auxiliary references without overloading lineage.
"""

from __future__ import annotations

import json
import secrets
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .generation_evidence_ledger import file_sha256
from .generation_identity import (
    InvalidGenerationIdError,
    format_generation_not_found,
    normalize_generation_id,
)
from .generation_snapshot import (
    METADATA_FILENAME,
    WORKFLOW_FILENAME,
    load_snapshot_by_id,
)
from .preparation_project_context import PreparationProjectContext
from .project_workspace import ProjectManifest, ProjectWorkspace
from .seed_mode import (
    ALLOWED_SEED_MODE_SET,
    SEED_MODE_FIXED,
    SEED_MODE_RANDOMIZE,
    coerce_execution_seed,
    control_after_generate_for_seed_mode,
    extract_ksampler_widgets,
)
from .workflow_library_preparation import (
    LibraryPreparationResult,
    allocate_preparation_id,
    prepare_library_workflow,
)
from .workflow_manifest import load_workflow_manifest

PACKAGE_VERSION = "4.11"
PREPARATION_KIND_GENERATION_DERIVATION = "generation_derivation"
DERIVATION_TYPE_IMAGE_VARIATION = "image_variation"
DERIVATION_WORKFLOW_IDENTIFIER = "base/img2img"

DERIVATION_SOURCE_SUBDIR = "derivation_source"
DERIVATION_SOURCE_FILENAME = "derivation_source.png"
DERIVATION_SOURCE_RELATIVE_PATH = f"{DERIVATION_SOURCE_SUBDIR}/{DERIVATION_SOURCE_FILENAME}"

DEFAULT_DENOISE = 0.55
LOCKED_PARAMETER_KEYS = frozenset({"input_image", "save_prefix"})

# Inherited from the source generation. Missing values fail closed — they are
# never silently replaced with canonical img2img defaults.
REQUIRED_INHERITED_KEYS = (
    "positive_prompt",
    "steps",
    "cfg",
    "sampler_name",
    "scheduler",
    "checkpoint",
)

INSUFFICIENT_STATE_ERROR = (
    "ERROR: Generation does not contain sufficient state for image variation."
)
MISSING_METADATA_ERROR = "ERROR: Generation metadata is missing or unreadable."
SOURCE_IMAGE_MISSING_ERROR = "ERROR: Source generation image file is missing."
SOURCE_SHA_MISMATCH_ERROR = (
    "ERROR: Source generation image SHA-256 does not match snapshot metadata."
)
SOURCE_SHA_MISSING_ERROR = (
    "ERROR: Generation metadata does not contain image_sha256 for verification."
)


def should_prompt_open_derivation_preparation(
    *,
    lookup_ok: bool,
    prepare_ok: bool,
    preparation_id: str = "",
) -> bool:
    """Prompt to open a derivation prep only after one was actually created."""
    if not lookup_ok or not prepare_ok:
        return False
    text = str(preparation_id or "").strip()
    if text:
        return text.lower().startswith("prep_")
    return True


def derivation_save_prefix(generation_id: str) -> str:
    """Deterministic ComfyUI Save Image prefix for variation preps."""
    canonical = normalize_generation_id(generation_id)
    uuid_part = canonical[len("gen_") :]
    short = uuid_part.replace("-", "")[:8]
    return f"ai_studio_var_{short}"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _null(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _nodes_by_type(api_prompt: dict[str, Any], class_type: str) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for node_id, node in api_prompt.items():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type") or "") == class_type:
            found.append((str(node_id), node))
    return found


def resolve_source_image_path(
    *,
    metadata: dict[str, Any],
    manifest: dict[str, Any],
) -> Path | None:
    """Resolve the verified permanent generation artifact path."""
    for key in ("canonical_output_path",):
        raw = metadata.get(key) or manifest.get(key)
        if raw:
            path = Path(str(raw))
            if path.is_file():
                return path
    project_path = metadata.get("project_output_path") or manifest.get("project_output_path")
    if project_path:
        path = Path(str(project_path))
        if path.is_file():
            return path
    return None


def verify_source_image(path: Path, expected_sha256: str) -> tuple[bool, str]:
    if not expected_sha256 or not str(expected_sha256).strip():
        return False, SOURCE_SHA_MISSING_ERROR
    if not path.is_file():
        return False, SOURCE_IMAGE_MISSING_ERROR
    actual = file_sha256(path)
    if actual != str(expected_sha256).strip():
        return False, SOURCE_SHA_MISMATCH_ERROR
    return True, ""


def resolve_derivation_archived_source(
    prepared_dir: Path,
    metadata: dict[str, Any] | None = None,
) -> Path | None:
    """Resolve the archived source PNG relative to a preparation archive.

    Authoritative identity is preparation-relative
    ``derivation_source/derivation_source.png``. Transient runtime absolute
    paths are ignored so restart/open cannot succeed from a stale runtime copy.
    """
    recorded = ""
    if isinstance(metadata, dict):
        recorded = str(metadata.get("derivation_source_archived_path") or "").strip()
    relative = DERIVATION_SOURCE_RELATIVE_PATH
    if recorded and not Path(recorded).is_absolute():
        relative = recorded.replace("\\", "/")
    candidate = prepared_dir / relative
    if candidate.is_file():
        return candidate
    fallback = prepared_dir / DERIVATION_SOURCE_SUBDIR / DERIVATION_SOURCE_FILENAME
    if fallback.is_file():
        return fallback
    return None


@dataclass
class DerivationEligibility:
    eligible: bool
    reason: str
    snapshot_status: str = "unavailable"
    workflow_snapshot_status: str = "unavailable"
    workflow_identifier: str = ""
    source_image_path: str = ""
    source_image_sha256: str = ""
    missing_fields: list[str] = field(default_factory=list)
    inherited_parameters: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DerivationResult:
    ok: bool
    generation_id: str = ""
    preparation_id: str = ""
    workflow_identifier: str = DERIVATION_WORKFLOW_IDENTIFIER
    preparation_kind: str = PREPARATION_KIND_GENERATION_DERIVATION
    derivation_type: str = DERIVATION_TYPE_IMAGE_VARIATION
    parameters: dict[str, Any] = field(default_factory=dict)
    lineage: dict[str, Any] = field(default_factory=dict)
    eligibility: DerivationEligibility | None = None
    preparation: LibraryPreparationResult | None = None
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "generation_id": self.generation_id,
            "preparation_id": self.preparation_id,
            "workflow_identifier": self.workflow_identifier,
            "preparation_kind": self.preparation_kind,
            "derivation_type": self.derivation_type,
            "parameters": self.parameters,
            "lineage": self.lineage,
            "eligibility": self.eligibility.to_dict() if self.eligibility else None,
            "messages": self.messages,
            "errors": self.errors,
            "warnings": self.warnings,
            "dry_run": self.dry_run,
        }
        if self.preparation is not None:
            payload["preparation"] = self.preparation.to_dict()
        return payload


def _clip_texts_from_api(api_prompt: dict[str, Any] | None) -> list[str]:
    texts: list[str] = []
    if not isinstance(api_prompt, dict):
        return texts
    for _, node in _nodes_by_type(api_prompt, "CLIPTextEncode"):
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        text = inputs.get("text")
        if isinstance(text, str):
            texts.append(text)
    return texts


def _api_sampler_inputs(api_prompt: dict[str, Any] | None) -> dict[str, Any]:
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


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip() and value != "":
            continue
        return value
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def extract_inherited_variation_parameters(
    *,
    metadata: dict[str, Any],
    workflow_payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Recover inherited creative values. Never invent canonical defaults.

    negative_prompt: empty string is a valid recovered value. Missing/null is
    treated as explicit empty inheritance (source recorded no negative), not as
    a fabricated img2img default.
    """
    workflow_payload = workflow_payload if isinstance(workflow_payload, dict) else {}
    api_prompt = workflow_payload.get("api_prompt")
    api_prompt = api_prompt if isinstance(api_prompt, dict) else None
    ui_workflow = workflow_payload.get("ui_workflow")
    ui_workflow = ui_workflow if isinstance(ui_workflow, dict) else None

    clip_texts = _clip_texts_from_api(api_prompt)
    sampler = _api_sampler_inputs(api_prompt)
    widgets = extract_ksampler_widgets(ui_workflow)

    positive = _first_present(
        metadata.get("positive_prompt") if isinstance(metadata.get("positive_prompt"), str) else None,
        clip_texts[0] if clip_texts else None,
    )
    negative_raw = metadata.get("negative_prompt")
    if isinstance(negative_raw, str):
        negative = negative_raw
    elif clip_texts and len(clip_texts) > 1 and isinstance(clip_texts[1], str):
        negative = clip_texts[1]
    else:
        negative = ""

    steps = _coerce_int(
        _first_present(
            metadata.get("steps"),
            sampler.get("steps"),
            widgets[2] if len(widgets) > 2 else None,
        )
    )
    cfg = _coerce_float(
        _first_present(
            metadata.get("cfg"),
            sampler.get("cfg"),
            widgets[3] if len(widgets) > 3 else None,
        )
    )
    sampler_name = _first_present(
        metadata.get("sampler_name") if metadata.get("sampler_name") not in (None, "") else None,
        sampler.get("sampler_name"),
        widgets[4] if len(widgets) > 4 else None,
    )
    scheduler = _first_present(
        metadata.get("scheduler") if metadata.get("scheduler") not in (None, "") else None,
        sampler.get("scheduler"),
        widgets[5] if len(widgets) > 5 else None,
    )
    checkpoint = _checkpoint_from_source(metadata, api_prompt)

    inherited: dict[str, Any] = {
        "positive_prompt": positive if isinstance(positive, str) else None,
        "negative_prompt": negative if isinstance(negative, str) else "",
        "steps": steps,
        "cfg": cfg,
        "sampler_name": str(sampler_name).strip() if sampler_name not in (None, "") else None,
        "scheduler": str(scheduler).strip() if scheduler not in (None, "") else None,
        "checkpoint": checkpoint,
    }
    missing = [key for key in REQUIRED_INHERITED_KEYS if inherited.get(key) in (None, "")]
    return inherited, missing


def _checkpoint_from_source(
    metadata: dict[str, Any],
    api_prompt: dict[str, Any] | None,
) -> str | None:
    model_files = metadata.get("model_files")
    if isinstance(model_files, list):
        for item in model_files:
            text = str(item or "").strip()
            if text:
                return text
    candidate = str(metadata.get("candidate_model") or "").strip()
    if candidate:
        return candidate
    api_ckpt = _api_checkpoint(api_prompt)
    if api_ckpt:
        return api_ckpt
    return None


def assess_derivation_eligibility(
    *,
    metadata: dict[str, Any],
    manifest: dict[str, Any],
    workflow_payload: dict[str, Any] | None = None,
) -> DerivationEligibility:
    """Fail closed unless the source can truthfully supply inherited values.

    Source workflow capability is intentionally generic: any verified
    image-producing generation with recoverable inherited creative state is
    eligible. Package 4.11 always targets base/img2img; it does not reproduce
    the source graph.
    """
    workflow_status = str(
        (workflow_payload or {}).get("workflow_snapshot_status")
        or metadata.get("workflow_snapshot_status")
        or "unavailable"
    )
    snapshot_status = str(
        (manifest or {}).get("snapshot_status")
        or metadata.get("snapshot_status")
        or "unavailable"
    )
    identifier = str(
        metadata.get("workflow_identifier")
        or metadata.get("canonical_workflow_identifier")
        or (workflow_payload or {}).get("workflow_identifier")
        or ""
    ).strip()

    if not metadata:
        return DerivationEligibility(
            eligible=False,
            reason=MISSING_METADATA_ERROR,
            snapshot_status=snapshot_status,
            workflow_snapshot_status=workflow_status,
            workflow_identifier=identifier,
            missing_fields=["metadata.json"],
        )

    image_sha = str(metadata.get("image_sha256") or manifest.get("image_sha256") or "").strip()
    if not image_sha:
        return DerivationEligibility(
            eligible=False,
            reason=SOURCE_SHA_MISSING_ERROR,
            snapshot_status=snapshot_status,
            workflow_snapshot_status=workflow_status,
            workflow_identifier=identifier,
            missing_fields=["image_sha256"],
        )

    source_path = resolve_source_image_path(metadata=metadata, manifest=manifest)
    if source_path is None:
        return DerivationEligibility(
            eligible=False,
            reason=SOURCE_IMAGE_MISSING_ERROR,
            snapshot_status=snapshot_status,
            workflow_snapshot_status=workflow_status,
            workflow_identifier=identifier,
            source_image_sha256=image_sha,
            missing_fields=["source_image"],
        )
    ok, err = verify_source_image(source_path, image_sha)
    if not ok:
        return DerivationEligibility(
            eligible=False,
            reason=err,
            snapshot_status=snapshot_status,
            workflow_snapshot_status=workflow_status,
            workflow_identifier=identifier,
            source_image_path=str(source_path),
            source_image_sha256=image_sha,
            missing_fields=["image_sha256"] if err == SOURCE_SHA_MISMATCH_ERROR else ["source_image"],
        )

    inherited, missing = extract_inherited_variation_parameters(
        metadata=metadata,
        workflow_payload=workflow_payload,
    )
    if missing:
        return DerivationEligibility(
            eligible=False,
            reason=INSUFFICIENT_STATE_ERROR,
            snapshot_status=snapshot_status,
            workflow_snapshot_status=workflow_status,
            workflow_identifier=identifier,
            source_image_path=str(source_path),
            source_image_sha256=image_sha,
            missing_fields=missing,
            inherited_parameters=inherited,
        )

    warnings: list[str] = []
    if workflow_status == "partial":
        warnings.append(
            "Source workflow snapshot is partial; variation inherited only "
            "recoverable creative parameters (no fabricated graph)."
        )
    if workflow_status == "unavailable":
        warnings.append(
            "Source workflow snapshot is unavailable; variation inherited "
            "creative parameters from generation metadata."
        )

    return DerivationEligibility(
        eligible=True,
        reason="eligible",
        snapshot_status=snapshot_status,
        workflow_snapshot_status=workflow_status,
        workflow_identifier=identifier,
        source_image_path=str(source_path),
        source_image_sha256=image_sha,
        inherited_parameters=inherited,
        warnings=warnings,
    )


def _default_variation_seed() -> int:
    return secrets.randbelow(2**63)


def build_default_variation_parameters(
    *,
    inherited: dict[str, Any],
    generation_id: str,
    parameter_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build variation parameters: inherited source values + new derivation defaults."""
    overrides = dict(parameter_overrides or {})
    for locked in LOCKED_PARAMETER_KEYS:
        overrides.pop(locked, None)

    seed_override = overrides.pop("seed", None)
    seed_mode_override = overrides.pop("seed_mode", None)
    denoise_override = overrides.pop("denoise", None)

    seed = coerce_execution_seed(seed_override)
    if seed is None:
        seed = _default_variation_seed()

    seed_mode = str(seed_mode_override or SEED_MODE_RANDOMIZE).strip() or SEED_MODE_RANDOMIZE
    denoise = DEFAULT_DENOISE if denoise_override is None else denoise_override

    params: dict[str, Any] = {
        "positive_prompt": inherited.get("positive_prompt"),
        "negative_prompt": inherited.get("negative_prompt") or "",
        "seed": seed,
        "seed_mode": seed_mode,
        "control_after_generate": control_after_generate_for_seed_mode(seed_mode)
        if seed_mode in ALLOWED_SEED_MODE_SET
        else None,
        "steps": inherited.get("steps"),
        "cfg": inherited.get("cfg"),
        "sampler_name": inherited.get("sampler_name"),
        "scheduler": inherited.get("scheduler"),
        "denoise": denoise,
        "checkpoint": inherited.get("checkpoint"),
        "save_prefix": derivation_save_prefix(generation_id),
    }
    for key, value in overrides.items():
        params[key] = value
    return params


def archive_derivation_source_image(
    source_path: Path,
    *,
    preparation_id: str,
    runtime_prepared_root: Path,
    expected_sha256: str,
    dry_run: bool = False,
) -> tuple[Path | None, list[str], list[str]]:
    """Copy verified source PNG into immutable prep-scoped archive."""
    messages: list[str] = []
    errors: list[str] = []
    archive_dir = runtime_prepared_root / preparation_id / DERIVATION_SOURCE_SUBDIR
    archive_path = archive_dir / DERIVATION_SOURCE_FILENAME
    if dry_run:
        messages.append(f"Dry run: would archive source to {archive_path}")
        return archive_path, messages, errors
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, archive_path)
    except OSError as exc:
        errors.append(f"ERROR: Failed to archive derivation source image: {exc}")
        return None, messages, errors
    actual = file_sha256(archive_path)
    if actual != str(expected_sha256).strip():
        errors.append(SOURCE_SHA_MISMATCH_ERROR)
        try:
            archive_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None, messages, errors
    messages.append(f"Archived derivation source: {DERIVATION_SOURCE_RELATIVE_PATH}")
    return archive_path, messages, errors


def build_derivation_lineage(
    *,
    generation_id: str,
    snapshot_root: Path,
    metadata: dict[str, Any],
    source_image_path: Path,
    image_sha256: str,
) -> dict[str, Any]:
    return {
        "preparation_kind": PREPARATION_KIND_GENERATION_DERIVATION,
        "derivation_type": DERIVATION_TYPE_IMAGE_VARIATION,
        "derived_from_generation_id": generation_id,
        "derivation_source_image_sha256": _null(image_sha256),
        "derivation_source_canonical_path": _null(str(source_image_path)),
        "derivation_source_project_output_path": _null(metadata.get("project_output_path")),
        "derivation_source_archived_path": DERIVATION_SOURCE_RELATIVE_PATH,
        "derivation_source_prompt_id": _null(metadata.get("prompt_id")),
        "derivation_source_preparation_id": _null(metadata.get("preparation_id")),
        "derivation_source_workflow_identifier": _null(
            metadata.get("workflow_identifier") or metadata.get("canonical_workflow_identifier")
        ),
        "derivation_source_snapshot_path": _null(str(snapshot_root)),
    }


def resolve_derivation_project(
    drive_root: Path,
    metadata: dict[str, Any],
    *,
    use_global: bool = False,
    project_ref: str | None = None,
) -> PreparationProjectContext:
    """Default to the source generation's project; allow explicit override."""
    from .preparation_project_context import resolve_preparation_project

    if use_global or project_ref:
        return resolve_preparation_project(
            drive_root,
            use_global=use_global,
            project_ref=project_ref,
        )
    project_slug = str(metadata.get("project_slug") or "").strip()
    project_id = str(metadata.get("project_id") or "").strip()
    ref = project_slug or project_id
    if not ref:
        return PreparationProjectContext(project=None, mode="global", source="source-generation-global")
    workspace = ProjectWorkspace(drive_root)
    try:
        project = workspace.resolve_project(ref)
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(
            f"Source generation project ({ref}) cannot be resolved for variation prep: {exc}"
        ) from exc
    if project.is_archived():
        raise ValueError(
            f"Source generation project is archived and cannot receive preparations: {project.slug}"
        )
    return PreparationProjectContext(project=project, mode="project", source="source-generation")


def derivation_allowed_input_roots(
    *,
    archive_dir: Path,
    comfyui_input_dir: Path,
) -> list[Path]:
    """Controlled roots for derivation prep input staging (not global outputs/)."""
    return [archive_dir.resolve(), comfyui_input_dir.resolve()]


def _cleanup_unusable_preparation(
    *,
    runtime_prepared_root: Path,
    drive_prepared_root: Path,
    preparation_id: str,
) -> None:
    drive_meta = drive_prepared_root / preparation_id / f"{preparation_id}.metadata.json"
    if drive_meta.is_file():
        return
    leftover = runtime_prepared_root / preparation_id
    if leftover.is_dir():
        shutil.rmtree(leftover, ignore_errors=True)


def prepare_variation_from_generation(
    repo_root: Path,
    *,
    generation_id: str,
    runtime_prepared_root: Path,
    drive_prepared_root: Path,
    comfyui_input_dir: Path,
    drive_root: Path,
    use_global: bool = False,
    project_ref: str | None = None,
    parameter_overrides: dict[str, Any] | None = None,
    dry_run: bool = False,
    comfy_object_info: dict[str, Any] | None = None,
    model_files_present: dict[str, bool] | None = None,
    active_project: ProjectManifest | None = None,
    project_context: PreparationProjectContext | None = None,
) -> DerivationResult:
    """Create a new img2img variation preparation from a generation snapshot."""
    result = DerivationResult(ok=False, dry_run=dry_run)
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
    eligibility = assess_derivation_eligibility(
        metadata=metadata,
        manifest=manifest,
        workflow_payload=workflow_payload,
    )
    result.eligibility = eligibility
    result.warnings.extend(eligibility.warnings)
    if not eligibility.eligible:
        result.errors.append(eligibility.reason)
        if eligibility.missing_fields:
            result.errors.append(
                "Missing required inherited fields: " + ", ".join(eligibility.missing_fields)
            )
        return result

    source_path = Path(str(eligibility.source_image_path))
    image_sha = str(eligibility.source_image_sha256)

    try:
        load_workflow_manifest(repo_root, DERIVATION_WORKFLOW_IDENTIFIER)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result.errors.append(f"ERROR: Cannot load img2img workflow manifest: {exc}")
        return result

    params = build_default_variation_parameters(
        inherited=eligibility.inherited_parameters,
        generation_id=canonical_gid,
        parameter_overrides=parameter_overrides,
    )
    result.parameters = dict(params)

    if project_context is None and active_project is None:
        try:
            project_context = resolve_derivation_project(
                drive_root,
                metadata,
                use_global=use_global,
                project_ref=project_ref,
            )
        except ValueError as exc:
            result.errors.append(f"ERROR: {exc}")
            return result
    project = active_project
    if project is None and project_context is not None:
        project = project_context.project

    preparation_id = allocate_preparation_id(runtime_prepared_root)
    archived_path, archive_messages, archive_errors = archive_derivation_source_image(
        source_path,
        preparation_id=preparation_id,
        runtime_prepared_root=runtime_prepared_root,
        expected_sha256=image_sha,
        dry_run=dry_run,
    )
    result.messages.extend(archive_messages)
    if archive_errors:
        result.errors.extend(archive_errors)
        if not dry_run:
            _cleanup_unusable_preparation(
                runtime_prepared_root=runtime_prepared_root,
                drive_prepared_root=drive_prepared_root,
                preparation_id=preparation_id,
            )
        return result
    if archived_path is None:
        result.errors.append(SOURCE_IMAGE_MISSING_ERROR)
        return result

    params["input_image"] = str(archived_path)
    lineage = build_derivation_lineage(
        generation_id=canonical_gid,
        snapshot_root=snapshot_root,
        metadata=metadata,
        source_image_path=source_path,
        image_sha256=image_sha,
    )
    result.lineage = lineage

    allowed_roots = derivation_allowed_input_roots(
        archive_dir=archived_path.parent,
        comfyui_input_dir=comfyui_input_dir,
    )

    prep = prepare_library_workflow(
        repo_root,
        workflow_identifier=DERIVATION_WORKFLOW_IDENTIFIER,
        parameters=params,
        runtime_prepared_root=runtime_prepared_root,
        drive_prepared_root=drive_prepared_root,
        comfyui_input_dir=comfyui_input_dir,
        drive_root=drive_root,
        active_project=project,
        dry_run=dry_run,
        allowed_input_roots=allowed_roots,
        comfy_object_info=comfy_object_info,
        model_files_present=model_files_present,
        preparation_kind=PREPARATION_KIND_GENERATION_DERIVATION,
        lineage_metadata=lineage,
        package_version=PACKAGE_VERSION,
        preparation_id=preparation_id,
    )
    result.preparation = prep
    result.messages.extend(prep.messages)
    result.errors.extend(prep.errors)
    result.warnings.extend(msg for msg in prep.messages if msg.upper().startswith("WARNING"))
    result.ok = prep.ok
    if prep.ok:
        result.preparation_id = prep.preparation_id or preparation_id
        result.parameters = dict(prep.parameters)
        result.messages.append(
            "Variation preparation created (inspect/edit and manually Run — "
            "no automatic execution)."
        )
    else:
        if not dry_run:
            _cleanup_unusable_preparation(
                runtime_prepared_root=runtime_prepared_root,
                drive_prepared_root=drive_prepared_root,
                preparation_id=preparation_id,
            )
        result.preparation_id = ""
    return result


def restage_derivation_inputs_for_open(
    *,
    prepared_dir: Path,
    metadata: dict[str, Any],
    comfyui_input_dir: Path,
) -> tuple[list[str], list[str]]:
    """Restage archived derivation source into ComfyUI input after runtime restart."""
    messages: list[str] = []
    errors: list[str] = []
    kind = str(metadata.get("preparation_kind") or "")
    if kind != PREPARATION_KIND_GENERATION_DERIVATION:
        return messages, errors

    staged_inputs = metadata.get("staged_inputs")
    staged_filename = ""
    if isinstance(staged_inputs, dict):
        input_block = staged_inputs.get("input_image")
        if isinstance(input_block, dict):
            staged_filename = str(input_block.get("staged_filename") or "").strip()
    if not staged_filename:
        parameters = metadata.get("parameters")
        if isinstance(parameters, dict):
            raw = str(parameters.get("input_image") or "").strip()
            if raw and not Path(raw).is_absolute():
                staged_filename = Path(raw).name

    archive_path = resolve_derivation_archived_source(prepared_dir, metadata)
    if archive_path is None:
        errors.append("ERROR: Derivation archived source image missing; cannot restage input.")
        return messages, errors

    dest = comfyui_input_dir / (staged_filename or DERIVATION_SOURCE_FILENAME)
    try:
        comfyui_input_dir.mkdir(parents=True, exist_ok=True)
        if dest.is_file() and file_sha256(dest) == file_sha256(archive_path):
            messages.append(f"Derivation input already staged: {dest.name}")
            return messages, errors
        shutil.copy2(archive_path, dest)
        messages.append(f"Restaged derivation source to ComfyUI input: {dest.name}")
    except OSError as exc:
        errors.append(f"ERROR: Failed to restage derivation input: {exc}")
    return messages, errors


def compare_generation_to_derivation(
    *,
    generation_metadata: dict[str, Any],
    generation_manifest: dict[str, Any],
    preparation_metadata: dict[str, Any],
    child_generation_metadata: dict[str, Any] | None = None,
    prepared_dir: Path | None = None,
    generation_workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only comparison of source generation vs variation preparation."""
    gid = str(generation_metadata.get("generation_id") or "")
    eligibility = assess_derivation_eligibility(
        metadata=generation_metadata,
        manifest=generation_manifest,
        workflow_payload=generation_workflow,
    )
    prep_params = preparation_metadata.get("parameters")
    if not isinstance(prep_params, dict):
        prep_params = {}

    checks: list[dict[str, Any]] = []

    def _add(field: str, source: Any, preparation: Any, *, match: bool | None = None) -> None:
        if match is None:
            match = source == preparation
        checks.append(
            {
                "field": field,
                "source": source,
                "preparation": preparation,
                "match": match,
            }
        )

    _add(
        "derived_from_generation_id",
        gid,
        preparation_metadata.get("derived_from_generation_id"),
    )
    _add(
        "preparation_kind",
        PREPARATION_KIND_GENERATION_DERIVATION,
        preparation_metadata.get("preparation_kind"),
    )
    _add(
        "derivation_type",
        DERIVATION_TYPE_IMAGE_VARIATION,
        preparation_metadata.get("derivation_type"),
    )
    _add(
        "derivation_source_image_sha256",
        generation_metadata.get("image_sha256"),
        preparation_metadata.get("derivation_source_image_sha256"),
    )
    archived_relative = str(preparation_metadata.get("derivation_source_archived_path") or "")
    _add(
        "derivation_source_archived_path",
        DERIVATION_SOURCE_RELATIVE_PATH,
        archived_relative.replace("\\", "/"),
        match=not Path(archived_relative).is_absolute()
        and archived_relative.replace("\\", "/").endswith(DERIVATION_SOURCE_FILENAME),
    )
    archived_ok = False
    archive_path = None
    if prepared_dir is not None:
        archive_path = resolve_derivation_archived_source(prepared_dir, preparation_metadata)
    if archive_path is not None and archive_path.is_file() and generation_metadata.get("image_sha256"):
        archived_ok = file_sha256(archive_path) == str(generation_metadata.get("image_sha256"))
    _add(
        "archived_source_sha256",
        generation_metadata.get("image_sha256"),
        "(verified)" if archived_ok else "(missing or mismatch)",
        match=archived_ok,
    )
    parent_seed = generation_metadata.get("seed")
    prep_seed = prep_params.get("seed")
    prep_mode = prep_params.get("seed_mode")
    _add(
        "seed_mode",
        SEED_MODE_RANDOMIZE,
        prep_mode,
        match=prep_mode in ALLOWED_SEED_MODE_SET,
    )
    _add(
        "seed_intent_not_reproduction",
        f"parent_executed={parent_seed}",
        f"prep_seed={prep_seed} mode={prep_mode}",
        match=prep_mode == SEED_MODE_RANDOMIZE or prep_seed != parent_seed,
    )
    _add(
        "denoise",
        "(default_or_override)",
        prep_params.get("denoise"),
        match=prep_params.get("denoise") is not None,
    )
    _add(
        "workflow_identifier",
        DERIVATION_WORKFLOW_IDENTIFIER,
        preparation_metadata.get("workflow_identifier"),
    )

    lineage_ok = all(
        c.get("match")
        for c in checks
        if c.get("field")
        in {
            "derived_from_generation_id",
            "preparation_kind",
            "derivation_type",
            "derivation_source_image_sha256",
            "archived_source_sha256",
            "derivation_source_archived_path",
            "workflow_identifier",
        }
    )
    payload: dict[str, Any] = {
        "lineage_ok": lineage_ok,
        "checks": checks,
        "source_eligible": eligibility.eligible,
        "source_image_path": eligibility.source_image_path,
    }
    if child_generation_metadata:
        _add(
            "child_derived_from_generation_id",
            gid,
            child_generation_metadata.get("derived_from_generation_id"),
        )
        _add(
            "child_preparation_kind",
            PREPARATION_KIND_GENERATION_DERIVATION,
            child_generation_metadata.get("preparation_kind"),
        )
        child_repro = child_generation_metadata.get("reproduced_from_generation_id")
        _add(
            "child_not_reproduction",
            None,
            child_repro,
            match=not child_repro,
        )
        payload["child_lineage_ok"] = (
            child_generation_metadata.get("derived_from_generation_id") == gid
            and child_generation_metadata.get("preparation_kind")
            == PREPARATION_KIND_GENERATION_DERIVATION
            and not child_repro
        )
    payload["all_match"] = all(c.get("match") for c in checks)
    return payload
