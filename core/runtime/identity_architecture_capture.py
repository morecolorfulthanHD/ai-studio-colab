#!/usr/bin/env python3
"""Capture InstantID architecture-benchmark executions (Package 4.12.3).

Shared by live runner, autosync watcher, and missed-history recovery.
Durable Drive artifact + architecture ledger idempotence; never ordinary generations.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .generation_evidence_ledger import file_sha256
from .identity_architecture_benchmark import (
    ARCHITECTURE_INSTANTID,
    BENCHMARK_CAPABILITY,
    CANDIDATE_INSTANTID,
    PACKAGE_VERSION,
    PREPARATION_KIND,
    SCENARIO_DIMENSIONS,
    IdentityArchitectureRecord,
    append_architecture_benchmark_record_if_absent,
    architecture_idempotence_key,
    architecture_ledger_path,
    assess_instantid_license_gate,
    find_architecture_ledger_row,
    find_architecture_ledger_rows_by_execution,
    is_identity_architecture_metadata,
    load_architecture_benchmark_records,
    update_architecture_ledger_qa,
)
from .identity_benchmark_capture import (
    STATUS_CAPTURED,
    STATUS_DUPLICATE_REUSED_LEDGER_ARTIFACT,
    STATUS_REPAIR_REQUIRED_MISSING,
    STATUS_REPAIR_REQUIRED_SHA_MISMATCH,
    verify_existing_ledger_artifact,
)
from .prepared_workflow_index import find_by_preparation_id, preparations_log_path
from .workflow_provenance import ExecutionProvenance, extract_ai_studio_extra


SNAPSHOT_SKIPPED_ARCHITECTURE = "skipped_identity_architecture_benchmark"


@dataclass
class ArchitectureCaptureResult:
    ok: bool
    skipped_duplicate: bool = False
    skipped_not_architecture: bool = False
    status: str = ""
    record: dict[str, Any] | None = None
    drive_path: str = ""
    local_path: str = ""
    output_sha256: str = ""
    automated_qa: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_identity_architecture_benchmark_provenance(
    provenance: ExecutionProvenance | None,
    ui_workflow: dict[str, Any] | None = None,
) -> bool:
    """True when this execution belongs on the architecture ledger (not ordinary / FaceID)."""
    if provenance is not None:
        if str(provenance.preparation_kind or "") == PREPARATION_KIND:
            return True
        if str(provenance.capability or "") == BENCHMARK_CAPABILITY:
            return True
    meta: dict[str, Any] = {}
    if ui_workflow is not None:
        ai = extract_ai_studio_extra(ui_workflow)
        if isinstance(ai, dict) and is_identity_architecture_metadata(ai):
            return True
        if isinstance(ai, dict):
            meta.update(ai)
    if provenance is not None:
        meta.setdefault("preparation_kind", provenance.preparation_kind)
        meta.setdefault("capability", provenance.capability)
    return is_identity_architecture_metadata(meta)


def _path_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def _default_drive_output_dir(drive_root: Path) -> Path:
    return Path(drive_root) / "outputs"


def _default_evidence_path(drive_root: Path) -> Path:
    return Path(drive_root) / "logs" / "autosync" / "evidence.jsonl"


def _load_prep_metadata(drive_root: Path, preparation_id: str) -> dict[str, Any] | None:
    drive_meta = (
        Path(drive_root)
        / "workflows"
        / "prepared"
        / preparation_id
        / f"{preparation_id}.metadata.json"
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


def resolve_architecture_capture_context(
    *,
    drive_root: Path,
    provenance: ExecutionProvenance | None,
    ui_workflow: dict[str, Any] | None,
    preparation_id: str = "",
    scenario: str = "",
    character_id: str = "",
    candidate: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Resolve architecture fields from ai_studio / preparation metadata."""
    errors: list[str] = []
    ctx: dict[str, Any] = {
        "preparation_id": preparation_id,
        "candidate": candidate or CANDIDATE_INSTANTID,
        "architecture": ARCHITECTURE_INSTANTID,
        "scenario": scenario,
        "character_id": character_id,
        "character_face_sha256": "",
        "character_reference_path": "",
        "prepared_workflow_hash": "",
        "workflow_identifier": "",
        "seed": None,
        "width": None,
        "height": None,
    }
    ai: dict[str, Any] = {}
    if ui_workflow is not None:
        extracted = extract_ai_studio_extra(ui_workflow)
        if isinstance(extracted, dict):
            ai = extracted
    if provenance is not None:
        if not ctx["preparation_id"]:
            ctx["preparation_id"] = str(provenance.preparation_id or "")
        if not ctx["workflow_identifier"]:
            ctx["workflow_identifier"] = str(provenance.workflow_identifier or "")
        if provenance.seed is not None:
            ctx["seed"] = provenance.seed
        if provenance.width is not None:
            ctx["width"] = provenance.width
        if provenance.height is not None:
            ctx["height"] = provenance.height
        if provenance.prepared_workflow_hash:
            ctx["prepared_workflow_hash"] = provenance.prepared_workflow_hash

    for key in (
        "preparation_id",
        "candidate",
        "architecture",
        "scenario",
        "character_id",
        "character_face_sha256",
        "character_reference_path",
        "prepared_workflow_hash",
        "workflow_identifier",
        "seed",
    ):
        if ai.get(key) not in (None, "") and not ctx.get(key):
            ctx[key] = ai.get(key)

    prep_id = str(ctx.get("preparation_id") or "").strip()
    if prep_id:
        prep = _load_prep_metadata(drive_root, prep_id)
        if isinstance(prep, dict):
            for key in (
                "candidate",
                "architecture",
                "scenario",
                "character_id",
                "character_face_sha256",
                "character_reference_path",
                "prepared_workflow_hash",
                "workflow_identifier",
                "seed",
                "width",
                "height",
            ):
                if prep.get(key) not in (None, "") and not ctx.get(key):
                    ctx[key] = prep.get(key)

    if not ctx.get("scenario"):
        errors.append("ERROR: Architecture capture missing scenario.")
    if not ctx.get("character_id"):
        errors.append("ERROR: Architecture capture missing character_id.")
    if not ctx.get("preparation_id"):
        errors.append("ERROR: Architecture capture missing preparation_id.")
    return ctx, errors


def capture_identity_architecture_execution(
    *,
    drive_root: Path,
    ledger_path: Path | None = None,
    prompt_id: str,
    output_node_id: str,
    output_path: Path,
    output_sha256: str,
    provenance: ExecutionProvenance | None = None,
    ui_workflow: dict[str, Any] | None = None,
    local_path: str = "",
    project_id: str = "",
    ensure_durable: bool = True,
    drive_output_dir: Path | None = None,
    evidence_path: Path | None = None,
    automated_qa: dict[str, Any] | None = None,
    compute_qa_fn: Callable[[Path], dict[str, Any]] | None = None,
    license_gate: dict[str, Any] | None = None,
    asset_verification: dict[str, Any] | None = None,
    asset_verification_override: bool = False,
    preparation_id: str = "",
    scenario: str = "",
    character_id: str = "",
    seed: Any = None,
    repo_root: Path | None = None,
    created_by: str = "architecture_capture",
) -> ArchitectureCaptureResult:
    """Durable Drive verify/persist + architecture ledger append-once + optional QA.

    Ordering:
      validate → SHA → context → idempotence search → durable ensure →
      QA against Drive path → append-once (or enrich QA if duplicate).
    """
    result = ArchitectureCaptureResult(ok=False)
    if not is_identity_architecture_benchmark_provenance(provenance, ui_workflow):
        # Allow explicit runner context when provenance not yet stamped on watcher path.
        if not (preparation_id and scenario and character_id):
            result.skipped_not_architecture = True
            result.messages.append("Not an identity-architecture-benchmark execution; skipped.")
            result.ok = True
            return result

    if not prompt_id or not output_node_id:
        result.errors.append("ERROR: prompt_id and output_node_id are required for architecture capture.")
        return result

    ledger = Path(ledger_path) if ledger_path else architecture_ledger_path(drive_root)
    source = Path(output_path)
    sha = str(output_sha256 or "").strip().lower()
    runtime_local = local_path or (str(source) if source.is_file() else "")
    result.local_path = runtime_local

    if not sha:
        if not source.is_file():
            result.errors.append(f"ERROR: Output missing and no SHA provided: {source}")
            return result
        try:
            sha = file_sha256(source).lower()
        except OSError as exc:
            result.errors.append(f"ERROR: Unable to hash architecture output: {exc}")
            return result

    if source.is_file():
        try:
            actual = file_sha256(source).lower()
        except OSError as exc:
            result.errors.append(f"ERROR: Unable to read architecture output for SHA: {exc}")
            return result
        if actual != sha:
            result.errors.append(
                f"ERROR: Output SHA mismatch (expected {sha}, actual {actual}) for {source}"
            )
            return result

    ctx, resolve_errors = resolve_architecture_capture_context(
        drive_root=drive_root,
        provenance=provenance,
        ui_workflow=ui_workflow,
        preparation_id=preparation_id,
        scenario=scenario,
        character_id=character_id,
    )
    if resolve_errors:
        result.errors.extend(resolve_errors)
        return result
    if seed is not None:
        ctx["seed"] = seed
    elif provenance is not None and provenance.seed is not None:
        ctx["seed"] = provenance.seed

    key = architecture_idempotence_key(prompt_id, output_node_id, sha)
    existing_row = find_architecture_ledger_row(
        ledger,
        prompt_id=prompt_id,
        output_node_id=output_node_id,
        output_sha256=sha,
    )
    if existing_row is not None:
        status, existing_path, msgs, errs = verify_existing_ledger_artifact(
            existing_row, expected_sha256=sha
        )
        # Reword REPAIR messages for architecture ledger clarity.
        errs = [
            e.replace("identity benchmark ledger", "identity architecture ledger")
            for e in errs
        ]
        result.messages.extend(msgs)
        result.status = status
        if status != STATUS_DUPLICATE_REUSED_LEDGER_ARTIFACT:
            result.ok = False
            result.errors.extend(errs)
            return result
        result.ok = True
        result.skipped_duplicate = True
        result.record = dict(existing_row)
        result.drive_path = str(existing_path or existing_row.get("output_path") or "")
        result.output_sha256 = sha
        result.messages.append(f"Already captured (idempotent, pre-persistence): {key}")
        # Optional QA enrichment — never append a second row.
        qa = automated_qa
        if qa is None and compute_qa_fn is not None and existing_path is not None:
            qa = compute_qa_fn(Path(existing_path))
        if qa:
            ok_e, updated, emsgs = update_architecture_ledger_qa(
                ledger,
                idempotence_key=key,
                automated_qa=qa,
                human_review={
                    "status": qa.get("human_review_status") or "pending",
                    "notes": "",
                },
            )
            result.messages.extend(emsgs)
            if ok_e:
                result.automated_qa = qa
                if updated and result.record is not None:
                    result.record["automated_qa"] = qa
            else:
                result.errors.extend(emsgs)
                result.ok = False
        else:
            existing_qa = existing_row.get("automated_qa")
            if isinstance(existing_qa, dict):
                result.automated_qa = existing_qa
        return result

    durable_path = source
    durable_sha = sha
    if ensure_durable:
        from .identity_benchmark_artifact import ensure_canonical_identity_benchmark_artifact

        out_dir = Path(drive_output_dir) if drive_output_dir else _default_drive_output_dir(drive_root)
        ev_path = Path(evidence_path) if evidence_path else _default_evidence_path(drive_root)
        preferred = source if _path_under(source, out_dir) else None
        canonical = ensure_canonical_identity_benchmark_artifact(
            drive_root=drive_root,
            source_path=source,
            prompt_id=prompt_id,
            output_node_id=output_node_id,
            source_sha256=sha,
            drive_output_dir=out_dir,
            evidence_path=ev_path,
            preferred_drive_path=preferred,
            wait_for_autosync_seconds=0.0,
            allow_create_fallback=True,
            created_by=created_by,
            capability=BENCHMARK_CAPABILITY,
            snapshot_status=SNAPSHOT_SKIPPED_ARCHITECTURE,
        )
        result.messages.extend(canonical.messages)
        if not canonical.ok or canonical.drive_path is None:
            result.errors.extend(
                canonical.errors or ["ERROR: Durable Drive architecture artifact unavailable."]
            )
            return result
        durable_path = Path(canonical.drive_path)
        durable_sha = str(canonical.drive_sha256 or "").lower()
        if durable_sha != sha:
            result.errors.append(
                f"ERROR: Durable SHA must equal local SHA (expected {sha}, got {durable_sha})."
            )
            return result
        # Fail closed: Drive path must be under Drive outputs (not ephemeral /content).
        if not _path_under(durable_path, out_dir) and not preferred:
            # SOURCE_UNDER_DRIVE with preferred under drive is OK; otherwise require under out_dir.
            if not _path_under(durable_path, Path(drive_root)):
                result.errors.append(
                    f"ERROR: Canonical output_path is not under Drive root: {durable_path}"
                )
                return result

    qa = automated_qa
    if qa is None and compute_qa_fn is not None:
        qa = compute_qa_fn(Path(durable_path))
    qa = qa or {}

    lic = license_gate
    if lic is None and repo_root is not None:
        lic = assess_instantid_license_gate(repo_root)
    lic = lic or {}

    scenario_id = str(ctx.get("scenario") or "")
    width, height = SCENARIO_DIMENSIONS.get(scenario_id, (None, None))
    if ctx.get("width") is not None:
        width = ctx.get("width")
    if ctx.get("height") is not None:
        height = ctx.get("height")

    notes = [
        "identity_architecture_benchmark durable capture",
        f"durable_output={durable_path}",
        "not an ordinary generation record",
    ]
    if asset_verification_override:
        notes.append("INVESTIGATION OVERRIDE: asset_verification_override=true")
        notes.append("promotion remains blocked regardless of override")
    if qa:
        notes.append(f"automated_quality_status={qa.get('automated_quality_status')}")

    # Investigation override must never mark production-eligible.
    promotion = "pending"
    if asset_verification_override or not lic.get("promotion_allowed", False):
        promotion = "pending"
    if lic and not lic.get("promotion_allowed", False):
        notes.append(f"license_gate={lic.get('overall_status')}")

    record = IdentityArchitectureRecord(
        candidate=str(ctx.get("candidate") or CANDIDATE_INSTANTID),
        architecture=str(ctx.get("architecture") or ARCHITECTURE_INSTANTID),
        scenario=scenario_id,
        character_id=str(ctx.get("character_id") or ""),
        seed=ctx.get("seed"),
        executed_seed=ctx.get("seed"),
        preparation_id=str(ctx.get("preparation_id") or ""),
        preparation_kind=PREPARATION_KIND,
        workflow_identifier=str(ctx.get("workflow_identifier") or ""),
        prepared_workflow_hash=str(ctx.get("prepared_workflow_hash") or ""),
        character_face_sha256=str(ctx.get("character_face_sha256") or ""),
        character_reference_path=str(ctx.get("character_reference_path") or ""),
        prompt_id=prompt_id,
        output_node_id=output_node_id,
        output_path=str(durable_path),
        output_sha256=durable_sha,
        local_path=runtime_local,
        width=width if isinstance(width, int) else None,
        height=height if isinstance(height, int) else None,
        execution_status="pass",
        automated_qa=qa,
        human_review={
            "status": (qa.get("human_review_status") if qa else None) or "pending",
            "notes": "",
        },
        human_review_status=str((qa.get("human_review_status") if qa else None) or "pending"),
        promotion_status=promotion,
        license_gate=lic,
        asset_verification=asset_verification or {},
        asset_verification_override=bool(asset_verification_override),
        capture_idempotence_key=key,
        benchmark_run=True,
        notes=notes,
        project_id=project_id or "",
        package_version=PACKAGE_VERSION,
    )
    try:
        _ok, skipped_dup = append_architecture_benchmark_record_if_absent(
            ledger, record, idempotence_key=key
        )
    except TimeoutError as exc:
        result.errors.append(f"ERROR: {exc}")
        return result
    if not _ok:
        result.errors.append("ERROR: Failed to append architecture ledger row.")
        return result
    if skipped_dup:
        result.ok = True
        result.skipped_duplicate = True
        result.status = STATUS_DUPLICATE_REUSED_LEDGER_ARTIFACT
        result.drive_path = str(durable_path)
        result.output_sha256 = durable_sha
        result.automated_qa = qa
        result.messages.append(f"Already captured (idempotent): {key}")
        if qa:
            ok_e, _upd, emsgs = update_architecture_ledger_qa(
                ledger,
                idempotence_key=key,
                automated_qa=qa,
                human_review=record.human_review,
            )
            result.messages.extend(emsgs)
            if not ok_e:
                result.errors.extend(emsgs)
                result.ok = False
        return result

    result.ok = True
    result.status = STATUS_CAPTURED
    result.record = record.to_dict()
    result.drive_path = str(durable_path)
    result.output_sha256 = durable_sha
    result.automated_qa = qa
    result.messages.append(
        f"Captured identity architecture execution: {record.candidate}/{record.scenario} "
        f"prep={record.preparation_id} prompt={prompt_id} output={durable_path}"
    )
    return result


STATUS_AMBIGUOUS_LEDGER_EXECUTION = "AMBIGUOUS_LEDGER_EXECUTION"


def recover_identity_architecture_from_history(
    *,
    drive_root: Path,
    ledger_path: Path | None = None,
    comfy_output_dir: Path,
    base_url: str,
    history: dict[str, Any] | None = None,
    resolve_output_path: Any | None = None,
    drive_output_dir: Path | None = None,
    evidence_path: Path | None = None,
    registered_hashes: dict[str, tuple[str, str, str]] | None = None,
) -> dict[str, Any]:
    """Scan ComfyUI history for uncaptured architecture-benchmark executions.

    Already-captured executions are verified via the durable Drive ledger row
    without requiring the ephemeral local ComfyUI file.
    """
    from .comfyui_events import extract_output_files, fetch_history
    from .output_autosync import resolve_comfy_output_path
    from .workflow_provenance import extract_execution_provenance, extract_ui_workflow_from_history

    resolve = resolve_output_path or resolve_comfy_output_path
    ledger = Path(ledger_path) if ledger_path else architecture_ledger_path(drive_root)
    report: dict[str, Any] = {
        "ok": True,
        "examined": 0,
        "captured": 0,
        "duplicates": 0,
        "skipped_non_architecture": 0,
        "failed": 0,
        "new_drive_files": 0,
        "new_architecture_rows": 0,
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
    before_rows = len(load_architecture_benchmark_records(ledger))
    before_drive_files = (
        len(list(out_dir.glob("identity_architecture_benchmark_*"))) if out_dir.is_dir() else 0
    )

    for prompt_id, entry in hist.items():
        if not isinstance(entry, dict):
            continue
        report["examined"] += 1
        ui_workflow = extract_ui_workflow_from_history(entry)
        files = extract_output_files(entry)
        if not files:
            continue
        meta = files[0]
        node_id = str(meta.get("node_id") or "")
        provenance = extract_execution_provenance(
            entry,
            registered_hashes=registered_hashes or {},
            ui_workflow=ui_workflow,
            output_node_id=node_id,
        )
        if not is_identity_architecture_benchmark_provenance(provenance, ui_workflow):
            report["skipped_non_architecture"] += 1
            continue

        pid = str(prompt_id)
        existing_rows = find_architecture_ledger_rows_by_execution(
            ledger, prompt_id=pid, output_node_id=node_id
        )
        if len(existing_rows) > 1:
            shas = {
                str(r.get("output_sha256") or "").strip().lower() for r in existing_rows
            }
            if len(shas) > 1:
                report["failed"] += 1
                report["ok"] = False
                report["errors"].append(
                    f"ERROR: {STATUS_AMBIGUOUS_LEDGER_EXECUTION} — multiple architecture "
                    f"ledger rows for prompt_id={pid} output_node_id={node_id} with "
                    f"different SHAs; refuse guess."
                )
                continue
            # Same SHA duplicated rows — treat as single captured execution.
            existing_rows = [existing_rows[0]]

        if len(existing_rows) == 1:
            row = existing_rows[0]
            status, _path, msgs, errs = verify_existing_ledger_artifact(
                row, expected_sha256=str(row.get("output_sha256") or "")
            )
            errs = [
                e.replace("identity benchmark ledger", "identity architecture ledger")
                for e in errs
            ]
            report["messages"].extend(msgs)
            if status == STATUS_DUPLICATE_REUSED_LEDGER_ARTIFACT:
                report["duplicates"] += 1
                report["messages"].append(
                    f"Recovery duplicate (ledger verified, local not required): {pid}|{node_id}"
                )
                continue
            report["failed"] += 1
            report["ok"] = False
            report["errors"].extend(
                errs
                or [
                    f"ERROR: Architecture ledger artifact verification failed for {pid}|{node_id} "
                    f"(status={status})."
                ]
            )
            continue

        # No ledger match — local ComfyUI output required to establish SHA.
        local = resolve(
            Path(comfy_output_dir),
            filename=str(meta.get("filename") or ""),
            subfolder=str(meta.get("subfolder") or ""),
        )
        if not Path(local).is_file():
            report["failed"] += 1
            report["errors"].append(
                f"ERROR: Architecture execution {pid}|{node_id} is uncaptured and local "
                f"ComfyUI output is missing: {local}"
            )
            report["ok"] = False
            continue
        try:
            sha = file_sha256(Path(local)).lower()
        except OSError as exc:
            report["failed"] += 1
            report["errors"].append(str(exc))
            report["ok"] = False
            continue

        cap = capture_identity_architecture_execution(
            drive_root=drive_root,
            ledger_path=ledger,
            prompt_id=pid,
            output_node_id=node_id,
            output_path=Path(local),
            output_sha256=sha,
            provenance=provenance,
            ui_workflow=ui_workflow,
            local_path=str(local),
            ensure_durable=True,
            drive_output_dir=out_dir,
            evidence_path=ev_path,
            created_by="architecture_recovery",
        )
        if not cap.ok:
            report["failed"] += 1
            report["errors"].extend(cap.errors)
            report["ok"] = False
            continue
        if cap.skipped_duplicate:
            report["duplicates"] += 1
        else:
            report["captured"] += 1
            report["captures"].append(cap.to_dict())

    after_rows = len(load_architecture_benchmark_records(ledger))
    after_drive_files = (
        len(list(out_dir.glob("identity_architecture_benchmark_*"))) if out_dir.is_dir() else 0
    )
    report["new_architecture_rows"] = max(0, after_rows - before_rows)
    report["new_drive_files"] = max(0, after_drive_files - before_drive_files)
    report["messages"].append(
        f"Architecture recovery: examined={report['examined']} "
        f"captured={report['captured']} duplicates={report['duplicates']} "
        f"failed={report['failed']} new_rows={report['new_architecture_rows']} "
        f"new_drive_files={report['new_drive_files']}"
    )
    return report
