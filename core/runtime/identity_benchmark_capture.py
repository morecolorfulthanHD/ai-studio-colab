#!/usr/bin/env python3
"""Capture prepared identity-benchmark ComfyUI executions into the durable ledger.

Ordinary autosync creates generation snapshots. Identity benchmarks must NOT enter
the ordinary generation ledger; they write ``identity_benchmark.jsonl`` instead.

Idempotence key: ``prompt_id|output_node_id|output_sha256``
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .comfyui_events import extract_output_files, fetch_history
from .generation_evidence_ledger import file_sha256, utc_now
from .identity_benchmark import (
    BENCHMARK_CAPABILITY,
    HUMAN_REVIEW_RUBRIC,
    IdentityBenchmarkRecord,
    PACKAGE_VERSION,
    PREPARATION_KIND_IDENTITY_BENCHMARK,
    append_identity_benchmark_record_if_absent,
    is_benchmark_generation_metadata,
    load_identity_benchmark_records,
)
from .prepared_workflow_index import find_by_preparation_id, preparations_log_path, read_preparation_records
from .workflow_provenance import (
    ExecutionProvenance,
    extract_ai_studio_extra,
    extract_execution_provenance,
    extract_ui_workflow_from_history,
    hash_ui_workflow,
)

CAPTURE_SCHEMA_VERSION = 1


def benchmark_idempotence_key(prompt_id: str, output_node_id: str, output_sha256: str) -> str:
    return f"{prompt_id}|{output_node_id}|{output_sha256}"


def ledger_has_idempotence_key(ledger_path: Path, key: str) -> bool:
    if not key:
        return False
    for row in load_identity_benchmark_records(ledger_path):
        if str(row.get("capture_idempotence_key") or "") == key:
            return True
        # Legacy / partial rows: same prompt+node+sha
        legacy = benchmark_idempotence_key(
            str(row.get("prompt_id") or ""),
            str(row.get("output_node_id") or ""),
            str(row.get("output_sha256") or ""),
        )
        if legacy == key:
            return True
    return False


def is_identity_benchmark_provenance(
    provenance: ExecutionProvenance | None,
    ui_workflow: dict[str, Any] | None = None,
) -> bool:
    meta: dict[str, Any] = {}
    if provenance is not None:
        meta = {
            "benchmark_run": True
            if str(provenance.preparation_kind or "") == PREPARATION_KIND_IDENTITY_BENCHMARK
            else None,
            "preparation_kind": provenance.preparation_kind,
            "capability": provenance.capability,
            "workflow_identifier": provenance.workflow_identifier,
        }
        if str(provenance.preparation_kind or "") == PREPARATION_KIND_IDENTITY_BENCHMARK:
            return True
        if str(provenance.capability or "") == BENCHMARK_CAPABILITY:
            return True
    if ui_workflow is not None:
        ai = extract_ai_studio_extra(ui_workflow)
        if is_benchmark_generation_metadata(ai):
            return True
        meta.update(ai)
    return is_benchmark_generation_metadata(meta)


@dataclass
class BenchmarkCaptureContext:
    preparation_id: str
    candidate: str
    scenario: str
    character_id: str
    character_face_sha256: str = ""
    character_reference_path: str = ""
    prepared_workflow_hash: str = ""
    workflow_identifier: str = ""
    intended_seed: int | None = None
    match_method: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class BenchmarkCaptureResult:
    ok: bool
    skipped_duplicate: bool = False
    skipped_not_benchmark: bool = False
    status: str = ""
    record: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


STATUS_DUPLICATE_REUSED_LEDGER_ARTIFACT = "DUPLICATE_REUSED_LEDGER_ARTIFACT"
STATUS_REPAIR_REQUIRED_MISSING = "REPAIR_REQUIRED"
STATUS_REPAIR_REQUIRED_SHA_MISMATCH = "REPAIR_REQUIRED_SHA_MISMATCH"
STATUS_CAPTURED = "CAPTURED"


def find_identity_benchmark_ledger_row(
    ledger_path: Path,
    *,
    prompt_id: str,
    output_node_id: str,
    output_sha256: str,
) -> dict[str, Any] | None:
    """Return the first ledger row for exact prompt/node/SHA (idempotence key)."""
    key = benchmark_idempotence_key(prompt_id, output_node_id, output_sha256)
    if not key or key == "||":
        return None
    for row in load_identity_benchmark_records(ledger_path):
        if str(row.get("capture_idempotence_key") or "") == key:
            return row
        legacy = benchmark_idempotence_key(
            str(row.get("prompt_id") or ""),
            str(row.get("output_node_id") or ""),
            str(row.get("output_sha256") or ""),
        )
        if legacy == key:
            return row
    return None


def verify_existing_ledger_artifact(
    row: dict[str, Any],
    *,
    expected_sha256: str,
) -> tuple[str, Path | None, list[str], list[str]]:
    """Verify a ledger-referenced durable artifact without creating files.

    Returns ``(status, path_or_none, messages, errors)``.
    """
    sha = str(expected_sha256 or "").strip().lower()
    raw = str(row.get("output_path") or "").strip()
    if not raw:
        return (
            STATUS_REPAIR_REQUIRED_MISSING,
            None,
            [],
            [
                "ERROR: REPAIR_REQUIRED — existing identity benchmark ledger row "
                "has empty output_path; refuse silent replacement."
            ],
        )
    path = Path(raw)
    if not path.is_file():
        return (
            STATUS_REPAIR_REQUIRED_MISSING,
            path,
            [],
            [
                f"ERROR: REPAIR_REQUIRED — ledger artifact missing at {path}; "
                "refuse silent replacement / new Drive copy."
            ],
        )
    try:
        actual = file_sha256(path).lower()
    except OSError as exc:
        return (
            STATUS_REPAIR_REQUIRED_MISSING,
            path,
            [],
            [f"ERROR: REPAIR_REQUIRED — unable to read ledger artifact {path}: {exc}"],
        )
    if actual != sha:
        return (
            STATUS_REPAIR_REQUIRED_SHA_MISMATCH,
            path,
            [],
            [
                f"ERROR: REPAIR_REQUIRED_SHA_MISMATCH — ledger artifact {path} "
                f"has SHA {actual}, expected {sha}; refuse overwrite/replacement."
            ],
        )
    return (
        STATUS_DUPLICATE_REUSED_LEDGER_ARTIFACT,
        path,
        [
            f"Durable benchmark artifact: {STATUS_DUPLICATE_REUSED_LEDGER_ARTIFACT}",
            f"Reused existing ledger artifact (zero persistence writes): {path}",
        ],
        [],
    )


def _load_prep_metadata(drive_root: Path, preparation_id: str) -> dict[str, Any] | None:
    drive_meta = (
        Path(drive_root) / "workflows" / "prepared" / preparation_id / f"{preparation_id}.metadata.json"
    )
    if drive_meta.is_file():
        try:
            payload = json.loads(drive_meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            return payload
    index_row = find_by_preparation_id(preparations_log_path(drive_root), preparation_id)
    return index_row if isinstance(index_row, dict) else None


def _context_from_prep_row(row: dict[str, Any], *, match_method: str) -> BenchmarkCaptureContext | None:
    preparation_id = str(row.get("preparation_id") or "").strip()
    candidate = str(row.get("candidate") or "").strip()
    scenario = str(row.get("scenario") or "").strip()
    character_id = str(row.get("character_id") or "").strip()
    if not preparation_id or not candidate or not scenario or not character_id:
        return None
    params = row.get("parameters") if isinstance(row.get("parameters"), dict) else {}
    summary = row.get("parameter_summary") if isinstance(row.get("parameter_summary"), dict) else {}
    seed_val = params.get("seed", summary.get("seed"))
    intended_seed: int | None
    try:
        intended_seed = int(seed_val) if seed_val is not None else None
    except (TypeError, ValueError):
        intended_seed = None
    return BenchmarkCaptureContext(
        preparation_id=preparation_id,
        candidate=candidate,
        scenario=scenario,
        character_id=character_id,
        character_face_sha256=str(row.get("character_face_sha256") or ""),
        character_reference_path=str(
            row.get("character_face_archived_path")
            or row.get("character_reference_path")
            or ""
        ),
        prepared_workflow_hash=str(row.get("prepared_workflow_hash") or ""),
        workflow_identifier=str(row.get("workflow_identifier") or ""),
        intended_seed=intended_seed,
        match_method=match_method,
    )


def _load_image_filename(ui_workflow: dict[str, Any] | None) -> str:
    if not isinstance(ui_workflow, dict):
        return ""
    for node in ui_workflow.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "LoadImage":
            continue
        widgets = node.get("widgets_values") or []
        if widgets:
            return str(widgets[0] or "")
    return ""


def resolve_benchmark_capture_context(
    *,
    drive_root: Path,
    provenance: ExecutionProvenance | None,
    ui_workflow: dict[str, Any] | None,
) -> tuple[BenchmarkCaptureContext | None, list[str]]:
    """Resolve prep context. Prefer embedded preparation_id; else fail-closed fingerprint match."""
    errors: list[str] = []
    ai = extract_ai_studio_extra(ui_workflow) if ui_workflow else {}
    prep_id = str(
        (ai.get("preparation_id") if ai else None)
        or (provenance.preparation_id if provenance else "")
        or ""
    ).strip()
    if prep_id:
        row = _load_prep_metadata(drive_root, prep_id)
        if row is not None:
            kind = str(row.get("preparation_kind") or "")
            if kind and kind != PREPARATION_KIND_IDENTITY_BENCHMARK and row.get("benchmark_run") is not True:
                errors.append(
                    f"ERROR: preparation {prep_id} is not an identity_benchmark preparation."
                )
                return None, errors
            ctx = _context_from_prep_row(row, match_method="embedded_preparation_id")
            if ctx is None:
                errors.append(
                    f"ERROR: preparation {prep_id} missing candidate/scenario/character fields."
                )
                return None, errors
            if not ctx.character_face_sha256 and isinstance(row.get("character_face_sha256"), str):
                ctx.character_face_sha256 = str(row.get("character_face_sha256") or "")
            return ctx, errors

        # Drive/index miss: durable executed workflow may still carry full ai_studio
        # provenance (Package 4.12 capture embed). Do not invent from filenames.
        if isinstance(ai, dict) and is_benchmark_generation_metadata(ai):
            candidate = str(ai.get("candidate") or "").strip()
            scenario = str(ai.get("scenario") or "").strip()
            character_id = str(ai.get("character_id") or "").strip()
            if candidate and scenario and character_id:
                seed_val = ai.get("seed")
                try:
                    intended = int(seed_val) if seed_val is not None else None
                except (TypeError, ValueError):
                    intended = None
                return (
                    BenchmarkCaptureContext(
                        preparation_id=prep_id,
                        candidate=candidate,
                        scenario=scenario,
                        character_id=character_id,
                        character_face_sha256=str(ai.get("character_face_sha256") or ""),
                        character_reference_path=str(
                            ai.get("character_reference_path")
                            or ai.get("character_face_archived_path")
                            or ""
                        ),
                        prepared_workflow_hash=str(ai.get("prepared_workflow_hash") or ""),
                        workflow_identifier=str(ai.get("workflow_identifier") or ""),
                        intended_seed=intended,
                        match_method="embedded_ai_studio",
                        notes=["Drive/index metadata missing; used executed ai_studio embed"],
                    ),
                    errors,
                )
        errors.append(
            f"ERROR: preparation_id {prep_id} not found on Drive/index and executed "
            "workflow lacks complete identity-benchmark ai_studio provenance."
        )
        return None, errors

    # Fingerprint match against indexed identity preparations (legacy workflows without embed).
    if ui_workflow is None:
        errors.append(
            "ERROR: Cannot resolve identity benchmark prep without preparation_id or UI workflow."
        )
        return None, errors

    executed_hash = hash_ui_workflow(ui_workflow)
    face_name = _load_image_filename(ui_workflow)
    executed_seed = provenance.seed if provenance else None
    save_prefix = str(provenance.save_prefix or "") if provenance else ""

    index_rows = [
        row
        for row in read_preparation_records(preparations_log_path(drive_root))
        if str(row.get("preparation_kind") or "") == PREPARATION_KIND_IDENTITY_BENCHMARK
        or row.get("benchmark_run") is True
    ]
    matches: list[BenchmarkCaptureContext] = []
    for row in index_rows:
        ctx = _context_from_prep_row(row, match_method="fingerprint")
        if ctx is None:
            continue
        meta = _load_prep_metadata(drive_root, ctx.preparation_id) or row
        prepared_hash = str(meta.get("prepared_workflow_hash") or ctx.prepared_workflow_hash or "")
        params = meta.get("parameters") if isinstance(meta.get("parameters"), dict) else {}
        summary = meta.get("parameter_summary") if isinstance(meta.get("parameter_summary"), dict) else {}
        expected_face = str(params.get("input_image") or "").strip()
        expected_prefix = str(params.get("save_prefix") or summary.get("save_prefix") or "").strip()
        expected_seed = params.get("seed", summary.get("seed"))
        try:
            expected_seed_i = int(expected_seed) if expected_seed is not None else None
        except (TypeError, ValueError):
            expected_seed_i = None

        hash_match = bool(prepared_hash) and prepared_hash == executed_hash
        face_match = bool(expected_face) and expected_face == face_name
        seed_match = expected_seed_i is not None and executed_seed is not None and int(executed_seed) == expected_seed_i
        prefix_match = bool(expected_prefix) and (
            save_prefix == expected_prefix or save_prefix.startswith(expected_prefix)
        )
        if hash_match or (face_match and seed_match and (prefix_match or not expected_prefix)):
            ctx.prepared_workflow_hash = prepared_hash or executed_hash
            ctx.character_face_sha256 = str(meta.get("character_face_sha256") or ctx.character_face_sha256)
            ctx.match_method = "prepared_workflow_hash" if hash_match else "face_seed_prefix"
            matches.append(ctx)

    if len(matches) == 0:
        errors.append(
            "ERROR: Ambiguous/uncapturable identity benchmark execution — no preparation matched "
            f"(ui_hash={executed_hash[:16]}… face={face_name!r} seed={executed_seed} prefix={save_prefix!r})."
        )
        return None, errors
    if len(matches) > 1:
        ids = ", ".join(m.preparation_id for m in matches)
        errors.append(
            f"ERROR: Ambiguous identity benchmark history — multiple preparations matched: {ids}"
        )
        return None, errors
    return matches[0], errors


@dataclass
class DurableArtifactResult:
    ok: bool
    drive_path: Path | None = None
    drive_sha256: str = ""
    local_path: str = ""
    reused_existing: bool = False
    status: str = ""
    historical_duplicates: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def find_verified_drive_copies_for_execution(
    evidence_path: Path,
    *,
    prompt_id: str,
    output_node_id: str,
    output_sha256: str,
) -> list[Path]:
    """Return verified Drive paths for exact prompt/node/SHA (fail closed on mismatch)."""
    from .identity_benchmark_artifact import (
        find_verified_drive_copies_for_execution as _find,
    )

    return _find(
        evidence_path,
        prompt_id=prompt_id,
        output_node_id=output_node_id,
        output_sha256=output_sha256,
    )


def ensure_durable_benchmark_artifact(
    *,
    drive_root: Path,
    source_path: Path,
    prompt_id: str,
    output_node_id: str,
    source_sha256: str,
    drive_output_dir: Path | None = None,
    evidence_path: Path | None = None,
    preferred_drive_path: Path | None = None,
    wait_for_autosync_seconds: float | None = None,
    created_by: str = "benchmark_capture",
) -> DurableArtifactResult:
    """Ensure a verified canonical Drive copy exists before ledger append.

    Cross-path ownership (Package 4.12.1): reuse verified autosync Drive copies
    when present; create a canonical fallback only when watcher evidence is absent.
    """
    from .identity_benchmark_artifact import (
        DEFAULT_AUTOSYNC_WAIT_SECONDS,
        ensure_canonical_identity_benchmark_artifact,
    )

    wait = (
        DEFAULT_AUTOSYNC_WAIT_SECONDS
        if wait_for_autosync_seconds is None
        else float(wait_for_autosync_seconds)
    )
    canonical = ensure_canonical_identity_benchmark_artifact(
        drive_root=drive_root,
        source_path=source_path,
        prompt_id=prompt_id,
        output_node_id=output_node_id,
        source_sha256=source_sha256,
        drive_output_dir=drive_output_dir,
        evidence_path=evidence_path,
        preferred_drive_path=preferred_drive_path,
        wait_for_autosync_seconds=wait,
        allow_create_fallback=True,
        created_by=created_by,
    )
    return DurableArtifactResult(
        ok=canonical.ok,
        drive_path=canonical.drive_path,
        drive_sha256=canonical.drive_sha256,
        local_path=canonical.local_path,
        reused_existing=canonical.reused_existing,
        status=canonical.status,
        historical_duplicates=list(canonical.historical_duplicates),
        errors=list(canonical.errors),
        messages=list(canonical.messages),
    )


@dataclass
class LegacyReclassifyResult:
    ok: bool
    changed: bool = False
    generation_id: str = ""
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _default_drive_output_dir(drive_root: Path) -> Path:
    return Path(drive_root) / "outputs"


def _default_evidence_path(drive_root: Path) -> Path:
    return Path(drive_root) / "logs" / "autosync" / "evidence.jsonl"


def _default_generation_index_path(drive_root: Path) -> Path:
    return Path(drive_root) / "logs" / "autosync" / "generation_index.jsonl"


def _default_reclass_audit_path(drive_root: Path) -> Path:
    return Path(drive_root) / "logs" / "identity_benchmark_reclassifications.jsonl"


def _path_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def reclassify_legacy_ordinary_generation(
    *,
    drive_root: Path,
    prompt_id: str,
    output_node_id: str,
    output_sha256: str,
    preparation_id: str,
    candidate: str = "",
    scenario: str = "",
    character_id: str = "",
    evidence_path: Path | None = None,
    generation_index_path: Path | None = None,
) -> LegacyReclassifyResult:
    """Reclassify a proven ordinary misclassification of an identity-benchmark run.

    Proof required: same prompt_id + output_node_id + output SHA, uniquely tied to
    an identity-benchmark preparation. Prefer index/metadata quarantine over deleting
    the image artifact.
    """
    from .generation_evidence_ledger import EvidenceLedger, EvidenceRecord
    from .generation_index import GenerationIndex, GenerationIndexRecord
    from .generation_snapshot import METADATA_FILENAME, _atomic_write_json

    result = LegacyReclassifyResult(ok=True, changed=False)
    sha = str(output_sha256 or "").strip().lower()
    if not prompt_id or not output_node_id or not sha or not preparation_id:
        result.ok = False
        result.errors.append(
            "ERROR: Reclassification requires prompt_id, output_node_id, output_sha256, preparation_id."
        )
        return result

    ev_path = Path(evidence_path) if evidence_path else _default_evidence_path(drive_root)
    idx_path = (
        Path(generation_index_path)
        if generation_index_path
        else _default_generation_index_path(drive_root)
    )
    audit_path = _default_reclass_audit_path(drive_root)

    matches: list[dict[str, Any]] = []
    if ev_path.is_file():
        for row in EvidenceLedger(ev_path).read_all():
            if str(row.get("sync_status") or "") != "verified":
                continue
            if str(row.get("prompt_id") or "") != prompt_id:
                continue
            if str(row.get("output_node_id") or "") != output_node_id:
                continue
            row_sha = str(row.get("drive_sha256") or row.get("local_sha256") or "").strip().lower()
            if row_sha != sha:
                continue
            # Already benchmark-isolated evidence — nothing to reclassify.
            if str(row.get("capability") or "") == BENCHMARK_CAPABILITY:
                continue
            if str(row.get("snapshot_status") or "") in {
                "skipped_identity_benchmark",
                "reclassified_identity_benchmark",
            }:
                continue
            matches.append(row)

    generation_ids = sorted(
        {str(r.get("generation_id") or "").strip() for r in matches if str(r.get("generation_id") or "").strip()}
    )
    if not matches and not generation_ids:
        # Also scan generation index for exact prompt/node/sha without relying on filenames.
        index = GenerationIndex(idx_path)
        index_hits = []
        for row in index.read_all():
            if str(row.get("prompt_id") or "") != prompt_id:
                continue
            if str(row.get("output_node_id") or "") != output_node_id:
                continue
            if str(row.get("image_sha256") or "").strip().lower() != sha:
                continue
            if str(row.get("snapshot_status") or "") == "reclassified_identity_benchmark":
                continue
            index_hits.append(row)
        if not index_hits:
            result.messages.append(
                "No ordinary generation representation found for this execution; no reclassification."
            )
            return result
        gids = sorted({str(r.get("generation_id") or "") for r in index_hits if r.get("generation_id")})
        if len(gids) != 1:
            result.ok = False
            result.errors.append(
                "ERROR: Ambiguous ordinary generation index hits for prompt/node/SHA; fail closed."
            )
            return result
        generation_ids = gids
        matches = index_hits

    if len(generation_ids) > 1:
        result.ok = False
        result.errors.append(
            "ERROR: Ambiguous ordinary generation_ids for prompt/node/SHA; fail closed: "
            + ", ".join(generation_ids)
        )
        return result

    generation_id = generation_ids[0] if generation_ids else ""
    if not generation_id:
        # Verified ordinary evidence without snapshot/generation_id — still quarantine via evidence.
        latest = matches[-1]
        EvidenceLedger(ev_path).append(
            EvidenceRecord(
                prompt_id=prompt_id,
                schema_version=int(latest.get("schema_version") or 2),
                output_node_id=output_node_id,
                local_path=str(latest.get("local_path") or ""),
                drive_path=str(latest.get("drive_path") or ""),
                source_filename=str(latest.get("source_filename") or ""),
                drive_filename=str(latest.get("drive_filename") or ""),
                local_sha256=str(latest.get("local_sha256") or sha),
                drive_sha256=str(latest.get("drive_sha256") or sha),
                byte_size=int(latest.get("byte_size") or 0),
                created_timestamp=utc_now(),
                synchronized_timestamp=utc_now(),
                sync_status="verified",
                capability=BENCHMARK_CAPABILITY,
                snapshot_status="reclassified_identity_benchmark",
                messages=["reclassified_from_ordinary_generation"],
                generation_id="",
                project_id=str(latest.get("project_id") or ""),
                project_output_path=str(latest.get("project_output_path") or ""),
            )
        )
        audit = {
            "timestamp": utc_now(),
            "action": "reclassify_ordinary_evidence_without_generation_id",
            "prompt_id": prompt_id,
            "output_node_id": output_node_id,
            "output_sha256": sha,
            "preparation_id": preparation_id,
            "drive_path": str(latest.get("drive_path") or ""),
        }
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        from .jsonl_file_lock import append_jsonl_line

        append_jsonl_line(audit_path, json.dumps(audit, ensure_ascii=False))
        result.changed = True
        result.messages.append("Reclassified ordinary evidence row (no generation_id).")
        return result

    # Patch snapshot metadata so parent eligibility refuses this generation.
    index = GenerationIndex(idx_path)
    latest_index = None
    try:
        latest_index = index.lookup_by_generation_id(generation_id)
    except Exception:
        # Fall back to raw scan for non-canonical IDs in sims/legacy rows.
        latest_index = index.latest_by_generation_id().get(generation_id)
    snapshot_root = Path(str((latest_index or {}).get("snapshot_root") or ""))
    if not snapshot_root.is_dir():
        # Discover under global generations root.
        from .generation_snapshot import global_generations_root, resolve_snapshot_root

        candidate_root = resolve_snapshot_root(drive_root, generation_id, project_slug="")
        if candidate_root.is_dir():
            snapshot_root = candidate_root
        else:
            snapshot_root = global_generations_root(drive_root) / generation_id

    meta_path = snapshot_root / METADATA_FILENAME
    if meta_path.is_file():
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result.ok = False
            result.errors.append(f"ERROR: Unable to read generation metadata for reclass: {exc}")
            return result
        if not isinstance(metadata, dict):
            result.ok = False
            result.errors.append("ERROR: Generation metadata is not an object; fail closed.")
            return result
        metadata["benchmark_run"] = True
        metadata["preparation_kind"] = PREPARATION_KIND_IDENTITY_BENCHMARK
        metadata["preparation_id"] = preparation_id
        metadata["capability"] = BENCHMARK_CAPABILITY
        if candidate:
            metadata["candidate"] = candidate
        if scenario:
            metadata["scenario"] = scenario
        if character_id:
            metadata["character_id"] = character_id
        metadata["excluded_from_ordinary_index"] = True
        metadata["reclassified_identity_benchmark"] = True
        metadata["reclassified_at"] = utc_now()
        _atomic_write_json(meta_path, metadata)
        result.messages.append(f"Patched snapshot metadata: {meta_path}")

    # Preserve canonical image path; append quarantine index row.
    canonical = ""
    image_sha = sha
    if latest_index:
        canonical = str(latest_index.get("canonical_output_path") or "")
        image_sha = str(latest_index.get("image_sha256") or sha)
    elif matches:
        canonical = str(matches[-1].get("drive_path") or "")
    index.append(
        GenerationIndexRecord(
            generation_id=generation_id,
            dedupe_key=str((latest_index or {}).get("dedupe_key") or matches[-1].get("local_path") or ""),
            prompt_id=prompt_id,
            output_node_id=output_node_id,
            project_id=str((latest_index or {}).get("project_id") or matches[-1].get("project_id") or ""),
            project_slug=str((latest_index or {}).get("project_slug") or ""),
            capability=BENCHMARK_CAPABILITY,
            created_timestamp=utc_now(),
            canonical_output_path=canonical,
            snapshot_root=str(snapshot_root) if snapshot_root else str((latest_index or {}).get("snapshot_root") or ""),
            snapshot_status="reclassified_identity_benchmark",
            image_sha256=image_sha,
            drive_filename=Path(canonical).name if canonical else str((latest_index or {}).get("drive_filename") or ""),
        )
    )

    if matches:
        latest = matches[-1]
        EvidenceLedger(ev_path).append(
            EvidenceRecord(
                prompt_id=prompt_id,
                schema_version=int(latest.get("schema_version") or 2),
                output_node_id=output_node_id,
                local_path=str(latest.get("local_path") or ""),
                drive_path=str(latest.get("drive_path") or canonical),
                source_filename=str(latest.get("source_filename") or ""),
                drive_filename=str(latest.get("drive_filename") or Path(canonical).name),
                local_sha256=str(latest.get("local_sha256") or sha),
                drive_sha256=str(latest.get("drive_sha256") or sha),
                byte_size=int(latest.get("byte_size") or 0),
                created_timestamp=utc_now(),
                synchronized_timestamp=utc_now(),
                sync_status="verified",
                capability=BENCHMARK_CAPABILITY,
                snapshot_status="reclassified_identity_benchmark",
                messages=["reclassified_from_ordinary_generation"],
                generation_id=generation_id,
                project_id=str(latest.get("project_id") or ""),
                project_output_path=str(latest.get("project_output_path") or ""),
            )
        )

    audit = {
        "timestamp": utc_now(),
        "action": "reclassify_ordinary_generation_as_identity_benchmark",
        "prompt_id": prompt_id,
        "output_node_id": output_node_id,
        "output_sha256": sha,
        "preparation_id": preparation_id,
        "generation_id": generation_id,
        "canonical_output_path": canonical,
        "snapshot_root": str(snapshot_root) if snapshot_root else "",
        "candidate": candidate,
        "scenario": scenario,
        "character_id": character_id,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    from .jsonl_file_lock import append_jsonl_line

    append_jsonl_line(audit_path, json.dumps(audit, ensure_ascii=False))

    result.changed = True
    result.generation_id = generation_id
    result.messages.append(
        f"Reclassified ordinary generation {generation_id} as identity benchmark "
        f"(image preserved at {canonical or 'unknown'})."
    )
    return result


def capture_identity_benchmark_execution(
    *,
    drive_root: Path,
    ledger_path: Path,
    prompt_id: str,
    output_node_id: str,
    output_path: Path,
    output_sha256: str,
    provenance: ExecutionProvenance,
    ui_workflow: dict[str, Any] | None,
    local_path: str = "",
    project_id: str = "",
    allow_missing_output: bool = False,
    ensure_durable: bool = True,
    drive_output_dir: Path | None = None,
    evidence_path: Path | None = None,
    reclassify_ordinary: bool = True,
) -> BenchmarkCaptureResult:
    """Append one identity benchmark ledger row for a verified durable execution output.

    Ordering (Package 4.12.1 recovery fix):
      validate → SHA → context → idempotence key → **ledger search** →
      only then durable ensure → append-once.

    Already-ledgered executions perform ZERO artifact writes.
    """
    result = BenchmarkCaptureResult(ok=False)
    if not is_identity_benchmark_provenance(provenance, ui_workflow):
        result.skipped_not_benchmark = True
        result.messages.append("Not an identity-benchmark execution; skipped.")
        result.ok = True
        return result

    if not prompt_id or not output_node_id:
        result.errors.append("ERROR: prompt_id and output_node_id are required for capture.")
        return result

    source = Path(output_path)
    sha = str(output_sha256 or "").strip().lower()
    runtime_local = local_path or (str(source) if source.is_file() else "")

    if not sha:
        if not source.is_file():
            result.errors.append(f"ERROR: Output missing and no SHA provided: {source}")
            return result
        try:
            sha = file_sha256(source).lower()
        except OSError as exc:
            result.errors.append(f"ERROR: Unable to hash benchmark output: {exc}")
            return result
    if not allow_missing_output and not source.is_file() and ensure_durable:
        # Durable ensure may still succeed via existing Drive evidence / ledger.
        pass
    elif not allow_missing_output and not source.is_file() and not ensure_durable:
        result.errors.append(f"ERROR: Benchmark output file missing: {source}")
        return result
    if source.is_file():
        try:
            actual = file_sha256(source).lower()
        except OSError as exc:
            result.errors.append(f"ERROR: Unable to read benchmark output for SHA: {exc}")
            return result
        if actual != sha:
            result.errors.append(
                f"ERROR: Output SHA mismatch (expected {sha}, actual {actual}) for {source}"
            )
            return result

    ctx, resolve_errors = resolve_benchmark_capture_context(
        drive_root=drive_root,
        provenance=provenance,
        ui_workflow=ui_workflow,
    )
    if ctx is None:
        result.errors.extend(resolve_errors or ["ERROR: Unable to resolve benchmark preparation."])
        return result

    executed_seed = provenance.seed
    if executed_seed is None:
        result.errors.append("ERROR: Executed seed missing from ComfyUI history provenance.")
        return result

    # Pre-persistence ledger idempotence: already-captured executions must not
    # allocate filenames, copy bytes, or append durability evidence.
    key = benchmark_idempotence_key(prompt_id, output_node_id, sha)
    existing_row = find_identity_benchmark_ledger_row(
        ledger_path,
        prompt_id=prompt_id,
        output_node_id=output_node_id,
        output_sha256=sha,
    )
    if existing_row is not None:
        status, existing_path, msgs, errs = verify_existing_ledger_artifact(
            existing_row, expected_sha256=sha
        )
        result.messages.extend(msgs)
        result.status = status
        if status == STATUS_DUPLICATE_REUSED_LEDGER_ARTIFACT:
            result.ok = True
            result.skipped_duplicate = True
            result.record = dict(existing_row)
            result.messages.append(f"Already captured (idempotent, pre-persistence): {key}")
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
            preferred_drive_path=source if _path_under(source, _default_drive_output_dir(drive_root)) else None,
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

    human_review = {k: "pending" for k in HUMAN_REVIEW_RUBRIC}
    record = IdentityBenchmarkRecord(
        candidate=ctx.candidate,
        scenario=ctx.scenario,
        character_id=ctx.character_id,
        seed=int(executed_seed),
        preparation_id=ctx.preparation_id,
        preparation_kind=PREPARATION_KIND_IDENTITY_BENCHMARK,
        workflow_identifier=ctx.workflow_identifier
        or provenance.workflow_identifier
        or "",
        prepared_workflow_hash=ctx.prepared_workflow_hash
        or provenance.prepared_workflow_hash
        or provenance.workflow_hash
        or "",
        character_face_sha256=ctx.character_face_sha256,
        character_reference_path=ctx.character_reference_path,
        prompt_id=prompt_id,
        output_node_id=output_node_id,
        output_path=str(durable_path),
        output_sha256=durable_sha,
        local_path=runtime_local,
        success=True,
        benchmark_run=True,
        human_review=human_review,
        human_review_status="pending",
        promotion_status="pending",
        capture_idempotence_key=key,
        project_id=project_id or "",
        package_version=PACKAGE_VERSION,
        capture_schema_version=CAPTURE_SCHEMA_VERSION,
        notes=[
            f"match_method={ctx.match_method}",
            "human rubric unscored — execution/provenance capture only",
            "not an ordinary generation record",
            f"durable_output={durable_path}",
        ],
    )
    try:
        _ok, skipped_dup = append_identity_benchmark_record_if_absent(
            ledger_path, record, idempotence_key=key
        )
    except TimeoutError as exc:
        result.errors.append(f"ERROR: {exc}")
        return result
    if not _ok:
        result.errors.append("ERROR: Failed to append identity benchmark ledger row.")
        return result
    if skipped_dup:
        # Race: another writer appended between our pre-check and append.
        # Do not treat as failure; durable ensure may have already run.
        result.ok = True
        result.skipped_duplicate = True
        result.status = STATUS_DUPLICATE_REUSED_LEDGER_ARTIFACT
        result.messages.append(f"Already captured (idempotent): {key}")
        return result

    if reclassify_ordinary:
        reclass = reclassify_legacy_ordinary_generation(
            drive_root=drive_root,
            prompt_id=prompt_id,
            output_node_id=output_node_id,
            output_sha256=durable_sha,
            preparation_id=ctx.preparation_id,
            candidate=ctx.candidate,
            scenario=ctx.scenario,
            character_id=ctx.character_id,
            evidence_path=evidence_path,
        )
        result.messages.extend(reclass.messages)
        if not reclass.ok:
            # Capture succeeded; surface reclass failure without deleting the benchmark row.
            result.errors.extend(reclass.errors)
            result.messages.append(
                "WARNING: Benchmark ledger captured, but ordinary-generation reclassification failed."
            )

    result.ok = True
    result.status = STATUS_CAPTURED
    result.record = record.to_dict()
    result.messages.append(
        f"Captured identity benchmark execution: {ctx.candidate}/{ctx.scenario} "
        f"prep={ctx.preparation_id} prompt={prompt_id} output={durable_path}"
    )
    return result


def recover_identity_benchmarks_from_history(
    *,
    drive_root: Path,
    ledger_path: Path,
    comfy_output_dir: Path,
    base_url: str,
    registered_hashes: dict[str, tuple[str, str, str]] | None = None,
    history: dict[str, Any] | None = None,
    resolve_output_path: Any | None = None,
    drive_output_dir: Path | None = None,
    evidence_path: Path | None = None,
) -> dict[str, Any]:
    """Scan ComfyUI history for uncaptured identity-benchmark executions (fail closed)."""
    from .output_autosync import resolve_comfy_output_path

    resolve = resolve_output_path or resolve_comfy_output_path
    report: dict[str, Any] = {
        "ok": True,
        "examined": 0,
        "captured": 0,
        "duplicates": 0,
        "skipped_non_benchmark": 0,
        "failed": 0,
        "reclassified": 0,
        "errors": [],
        "messages": [],
        "captures": [],
    }
    try:
        hist = history if history is not None else fetch_history(base_url=base_url)
    except RuntimeError as exc:
        report["ok"] = False
        report["errors"].append(str(exc))
        return report

    if not isinstance(hist, dict):
        report["ok"] = False
        report["errors"].append("ERROR: ComfyUI history payload is not an object.")
        return report

    out_dir = Path(drive_output_dir) if drive_output_dir else _default_drive_output_dir(drive_root)
    ev_path = Path(evidence_path) if evidence_path else _default_evidence_path(drive_root)

    for prompt_id, entry in hist.items():
        if not isinstance(entry, dict):
            continue
        report["examined"] += 1
        ui_workflow = extract_ui_workflow_from_history(entry)
        output_metas = extract_output_files(entry)
        if not output_metas:
            continue
        for meta in output_metas:
            node_id = str(meta.get("node_id") or "")
            provenance = extract_execution_provenance(
                entry,
                registered_hashes=registered_hashes or {},
                ui_workflow=ui_workflow,
                output_node_id=node_id,
            )
            if not is_identity_benchmark_provenance(provenance, ui_workflow):
                if ui_workflow is None:
                    report["skipped_non_benchmark"] += 1
                    continue
                probe_ctx, _ = resolve_benchmark_capture_context(
                    drive_root=drive_root,
                    provenance=provenance,
                    ui_workflow=ui_workflow,
                )
                if probe_ctx is None:
                    report["skipped_non_benchmark"] += 1
                    continue
                provenance.capability = BENCHMARK_CAPABILITY
                provenance.preparation_kind = PREPARATION_KIND_IDENTITY_BENCHMARK
                provenance.preparation_id = probe_ctx.preparation_id

            local_path = resolve(
                Path(comfy_output_dir),
                filename=str(meta.get("filename") or ""),
                subfolder=str(meta.get("subfolder") or ""),
            )
            # Prefer hashing local runtime file; durable ensure can fall back to Drive evidence.
            sha = ""
            if local_path.is_file():
                try:
                    sha = file_sha256(local_path)
                except OSError as exc:
                    report["failed"] += 1
                    report["errors"].append(
                        f"ERROR: History prompt {prompt_id}: cannot hash output: {exc}"
                    )
                    continue
            else:
                # Attempt SHA from evidence for this prompt/node (unique).
                from .generation_evidence_ledger import EvidenceLedger

                sha_candidates: set[str] = set()
                if ev_path.is_file():
                    for row in EvidenceLedger(ev_path).read_all():
                        if str(row.get("prompt_id") or "") != str(prompt_id):
                            continue
                        if str(row.get("output_node_id") or "") != node_id:
                            continue
                        if str(row.get("sync_status") or "") != "verified":
                            continue
                        row_sha = str(row.get("drive_sha256") or row.get("local_sha256") or "").lower()
                        if row_sha:
                            sha_candidates.add(row_sha)
                if len(sha_candidates) != 1:
                    report["failed"] += 1
                    report["errors"].append(
                        f"ERROR: History prompt {prompt_id} node {node_id}: output missing at "
                        f"{local_path} and no unique verified Drive SHA."
                    )
                    continue
                sha = next(iter(sha_candidates))

            capture = capture_identity_benchmark_execution(
                drive_root=drive_root,
                ledger_path=ledger_path,
                prompt_id=str(prompt_id),
                output_node_id=node_id,
                output_path=local_path,
                output_sha256=sha,
                provenance=provenance,
                ui_workflow=ui_workflow,
                local_path=str(local_path),
                ensure_durable=True,
                drive_output_dir=out_dir,
                evidence_path=ev_path,
                reclassify_ordinary=True,
            )
            if any("Reclassified" in m for m in capture.messages):
                report["reclassified"] += 1
            if capture.skipped_duplicate:
                report["duplicates"] += 1
                continue
            if capture.skipped_not_benchmark:
                report["skipped_non_benchmark"] += 1
                continue
            if not capture.ok:
                report["failed"] += 1
                report["errors"].extend(capture.errors)
                continue
            report["captured"] += 1
            report["captures"].append(capture.record)
            report["messages"].extend(capture.messages)
            # Capture may be ok with reclass warnings in errors — keep visible.
            if capture.errors:
                report["errors"].extend(capture.errors)
                report["ok"] = False

    if report["failed"]:
        report["ok"] = False
    return report
