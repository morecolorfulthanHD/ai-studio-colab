#!/usr/bin/env python3
"""Live InstantID architecture benchmark execution (Package 4.12.3).

Requires explicit --execute-benchmark + cost acknowledgement at the CLI layer.
Durable Drive capture via capture_identity_architecture_execution (shared with autosync).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .character_identity import load_character, resolve_primary_face_path
from .comfyui_events import DEFAULT_COMFY_BASE
from .comfyui_prompt_queue import (
    first_output_meta,
    queue_prompt,
    ui_workflow_to_api_prompt,
    wait_for_prompt_completion,
)
from .comfyui_workflow_loading import open_prepared_workflow_for_comfyui
from .generation_evidence_ledger import file_sha256
from .identity_architecture_benchmark import (
    CANDIDATE_INSTANTID,
    PREPARATION_KIND,
    assess_instantid_asset_readiness,
    assess_instantid_license_gate,
    prepare_identity_architecture_benchmark,
)
from .identity_architecture_capture import capture_identity_architecture_execution
from .identity_visual_qa import evaluate_scenario_qa, load_qa_config
from .output_autosync import resolve_comfy_output_path, wait_until_stable
from .workflow_provenance import ExecutionProvenance


@dataclass
class ArchitectureExecutionResult:
    ok: bool
    scenario: str = ""
    preparation_id: str = ""
    prompt_id: str = ""
    output_path: str = ""
    local_path: str = ""
    output_sha256: str = ""
    automated_qa: dict[str, Any] = field(default_factory=dict)
    stopped_fail_fast: bool = False
    queue_status: str = ""
    capture_status: str = ""
    skipped_duplicate: bool = False
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _wait_for_local_output(
    *,
    local_path: Path,
    timeout_seconds: float = 120.0,
    sleep_fn=time.sleep,
) -> Path | None:
    """Wait until the ephemeral ComfyUI output exists and is size-stable."""
    if local_path.is_file():
        wait_until_stable(local_path, timeout_seconds=min(30.0, timeout_seconds))
        return local_path
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if local_path.is_file():
            wait_until_stable(local_path, timeout_seconds=10.0)
            return local_path
        sleep_fn(1.0)
    return local_path if local_path.is_file() else None


def execute_architecture_scenario(
    *,
    repo_root: Path,
    drive_root: Path,
    character_id: str,
    scenario: str,
    bundle_models: list[dict[str, Any]],
    bundle_nodes: list[dict[str, Any]],
    runtime_prepared_root: Path,
    comfyui_input_dir: Path,
    comfyui_runtime: Path,
    comfyui_output_dir: Path,
    drive_prepared_root: Path | None = None,
    seed: int | None = None,
    base_url: str = DEFAULT_COMFY_BASE,
    completion_timeout_seconds: float = 600.0,
    poll_interval_seconds: float = 2.0,
    require_models: bool = True,
    require_nodes: bool = True,
    require_verified_assets: bool = True,
    asset_verification_override: bool = False,
    queue_prompt_fn: Callable[..., Any] | None = None,
    wait_history_fn: Callable[..., Any] | None = None,
    sleep_fn=time.sleep,
) -> ArchitectureExecutionResult:
    """Prepare → register → /prompt → wait → durable Drive capture → QA → ledger."""
    result = ArchitectureExecutionResult(ok=False, scenario=scenario)

    license_gate = assess_instantid_license_gate(repo_root)
    if not license_gate.get("promotion_allowed"):
        result.messages.append(
            "License gate: promotion blocked "
            f"(status={license_gate.get('overall_status')}). Execution may still run for investigation."
        )

    asset_ready: dict[str, Any] = {}
    if require_verified_assets:
        asset_ready = assess_instantid_asset_readiness(
            drive_root=drive_root,
            bundle_models=bundle_models,
            comfyui_runtime=comfyui_runtime,
        )
        if not asset_ready.get("ready"):
            if asset_verification_override:
                result.messages.append(
                    "INVESTIGATION OVERRIDE: --allow-unverified-assets "
                    "(asset_verification_override=true); promotion remains blocked."
                )
            else:
                result.errors.extend(
                    asset_ready.get("errors") or ["ERROR: InstantID assets not verified."]
                )
                return result
    elif asset_verification_override:
        result.messages.append(
            "INVESTIGATION OVERRIDE: --allow-unverified-assets "
            "(asset_verification_override=true); promotion remains blocked."
        )

    prep = prepare_identity_architecture_benchmark(
        repo_root,
        drive_root=drive_root,
        scenario=scenario,
        character_id=character_id,
        runtime_prepared_root=runtime_prepared_root,
        drive_prepared_root=drive_prepared_root,
        comfyui_input_dir=comfyui_input_dir,
        bundle_models=bundle_models,
        bundle_nodes=bundle_nodes,
        comfyui_custom_nodes=Path(comfyui_runtime) / "custom_nodes",
        seed=seed,
        require_models=require_models,
        require_nodes=require_nodes,
        dry_run=False,
        allow_benchmark=True,
        candidate=CANDIDATE_INSTANTID,
    )
    if not prep.ok:
        result.errors.extend(prep.errors)
        return result
    result.preparation_id = prep.preparation_id
    result.messages.extend(prep.messages)

    prepared_dir = Path(prep.runtime_prepared_dir or prep.prepared_dir)
    workflow_path = prepared_dir / f"{prep.preparation_id}.workflow.json"
    try:
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.errors.append(f"ERROR: Unable to read prepared workflow: {exc}")
        return result

    open_result = open_prepared_workflow_for_comfyui(
        preparation_id=prep.preparation_id,
        source_workflow_path=workflow_path,
        comfyui_runtime=Path(comfyui_runtime),
        base_url=base_url,
        dry_run=False,
    )
    if not open_result.ok and not open_result.filesystem_destination:
        result.errors.append("ERROR: Failed to register prepared workflow with ComfyUI.")
        result.errors.extend(list(open_result.errors or []))
        return result
    result.messages.append(
        "Prepared workflow registered (filesystem/userdata); no browser click required for /prompt."
    )
    result.messages.extend(list(open_result.messages or [])[:3])

    api_prompt = ui_workflow_to_api_prompt(workflow)
    if not api_prompt:
        result.errors.append("ERROR: UI→API prompt conversion produced empty prompt.")
        return result

    extra = {}
    if isinstance(workflow.get("extra"), dict):
        extra = {"extra_pnginfo": {"workflow": workflow}}
    queue_fn = queue_prompt_fn or queue_prompt
    queued = queue_fn(
        api_prompt,
        base_url=base_url,
        extra_data=extra or None,
    )
    if not queued.ok:
        result.queue_status = "failed"
        result.errors.extend(queued.errors)
        return result
    result.prompt_id = queued.prompt_id
    result.queue_status = "queued"
    result.messages.extend(queued.messages)

    wait_fn = wait_history_fn or wait_for_prompt_completion
    waited = wait_fn(
        queued.prompt_id,
        base_url=base_url,
        timeout_seconds=completion_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        sleep_fn=sleep_fn,
    )
    if not waited.ok:
        result.queue_status = "timeout" if waited.timed_out else "failed"
        result.errors.extend(waited.errors)
        return result
    result.queue_status = "completed"
    entry = waited.entry or {}
    meta = first_output_meta(entry)
    if meta is None:
        result.errors.append("ERROR: Completed history has no SaveImage output files.")
        return result

    local_path = resolve_comfy_output_path(
        Path(comfyui_output_dir),
        filename=str(meta.get("filename") or ""),
        subfolder=str(meta.get("subfolder") or ""),
    )
    local = _wait_for_local_output(
        local_path=local_path,
        timeout_seconds=120.0,
        sleep_fn=sleep_fn,
    )
    if local is None or not Path(local).is_file():
        result.errors.append(f"ERROR: Local ComfyUI output missing after completion: {local_path}")
        return result
    local_file = Path(local)
    try:
        local_sha = file_sha256(local_file).lower()
    except OSError as exc:
        result.errors.append(f"ERROR: Unable to hash local output: {exc}")
        return result
    result.local_path = str(local_file)

    character = load_character(drive_root, character_id)
    ref_face = resolve_primary_face_path(drive_root, character) if character else None
    if ref_face is None:
        result.errors.append("ERROR: Character primary face missing for automated QA.")
        return result

    qa_cfg = load_qa_config(repo_root)

    def _qa_on_drive(drive_path: Path) -> dict[str, Any]:
        return evaluate_scenario_qa(
            scenario,
            ref_face,
            drive_path,
            qa_cfg,
            requested_yaw_direction="right",
            repo_root=repo_root,
        )

    provenance = ExecutionProvenance(
        preparation_id=prep.preparation_id,
        preparation_kind=PREPARATION_KIND,
        capability="identity_architecture_benchmark",
        workflow_identifier=str(prep.workflow_identifier or ""),
        prepared_workflow_hash=str(prep.prepared_workflow_hash or ""),
        seed=prep.seed,
        width=prep.width,
        height=prep.height,
    )
    capture = capture_identity_architecture_execution(
        drive_root=drive_root,
        prompt_id=queued.prompt_id,
        output_node_id=str(meta.get("node_id") or ""),
        output_path=local_file,
        output_sha256=local_sha,
        provenance=provenance,
        ui_workflow=workflow,
        local_path=str(local_file),
        ensure_durable=True,
        drive_output_dir=Path(drive_root) / "outputs",
        evidence_path=Path(drive_root) / "logs" / "autosync" / "evidence.jsonl",
        compute_qa_fn=_qa_on_drive,
        license_gate=license_gate,
        asset_verification=asset_ready or {},
        asset_verification_override=bool(asset_verification_override),
        preparation_id=prep.preparation_id,
        scenario=str(prep.scenario or scenario),
        character_id=character_id,
        seed=prep.seed,
        repo_root=repo_root,
        created_by="architecture_runner",
    )
    result.messages.extend(capture.messages)
    result.capture_status = capture.status
    result.skipped_duplicate = capture.skipped_duplicate
    if not capture.ok:
        result.errors.extend(capture.errors)
        return result

    result.output_path = capture.drive_path
    result.output_sha256 = capture.output_sha256
    result.automated_qa = capture.automated_qa or {}

    # Contract: durable Drive path, SHA equality.
    drive_out = Path(capture.drive_path) if capture.drive_path else None
    if drive_out is None or not drive_out.is_file():
        result.errors.append("ERROR: Capture succeeded but durable Drive output_path missing.")
        result.ok = False
        return result
    try:
        drive_sha = file_sha256(drive_out).lower()
    except OSError as exc:
        result.errors.append(f"ERROR: Unable to verify Drive artifact SHA: {exc}")
        return result
    if drive_sha != local_sha or drive_sha != str(capture.output_sha256 or "").lower():
        result.errors.append(
            f"ERROR: SHA contract failed local={local_sha} drive={drive_sha} "
            f"ledger={capture.output_sha256}"
        )
        return result
    if "/content/" in str(drive_out).replace("\\", "/").lower() and "drive" not in str(
        drive_out
    ).replace("\\", "/").lower():
        # Heuristic for Colab ephemeral paths — still allow Windows temp drives in sims.
        if "ComfyUI/output" in str(drive_out).replace("\\", "/"):
            result.errors.append(
                f"ERROR: Ledger output_path must be durable Drive, not ephemeral Comfy output: {drive_out}"
            )
            return result

    auto_status = str(result.automated_qa.get("automated_quality_status") or "")
    if auto_status == "fail":
        result.ok = False
        result.errors.append(
            f"ERROR: Automated QA FAIL for {scenario} "
            f"(identity={result.automated_qa.get('identity_gate')}, "
            f"adherence={result.automated_qa.get('scenario_adherence_gate')})."
        )
        return result

    result.ok = True
    if auto_status in {"inconclusive", "provisional_pass"}:
        result.messages.append(
            f"Automated QA {auto_status} — HUMAN_REVIEW_REQUIRED before promotion."
        )
    return result


def should_fail_fast(
    scenario: str,
    qa: dict[str, Any],
    *,
    continue_after_fail: bool,
) -> bool:
    """Return True when runner must stop subsequent scenarios."""
    status = str(qa.get("automated_quality_status") or "")
    if status == "inconclusive":
        return True  # pause for human review
    if status != "fail":
        return False
    if scenario in {"S2_head_angle_pose", "S3_expression_change"} and continue_after_fail:
        return False
    return True
