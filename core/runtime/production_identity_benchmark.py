"""Production-facing InstantID identity benchmark orchestrator (Package 4.12.3 UX).

Thin wrapper over existing prepare / execute / capture / QA / report primitives.
Does not change InstantID thresholds, license/hash gates, or promotion rules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .character_identity import list_characters, load_character, verify_character_face
from .comfyui_userdata import DEFAULT_COMFY_BASE_URL, comfyui_reachable
from .generation_evidence_ledger import file_sha256
from .identity_architecture_benchmark import (
    INSTANTID_REQUIRED_GRAPH_NODES,
    assess_instantid_asset_readiness,
    assess_instantid_license_gate,
    assess_instantid_structural_readiness,
    architecture_ledger_path,
    format_architecture_benchmark_report,
    load_architecture_benchmark_records,
)
from .identity_architecture_execution import (
    execute_architecture_scenario,
    should_fail_fast,
)
from .identity_benchmark import SCENARIO_IDS, normalize_scenario_id
from .package4123_qa import run_consolidated_package4123_qa
from .registry_loader import RegistryLoader
from .runtime_health import HealthStatus, check_output_watcher

STATUS_COMPLETE = "COMPLETE"
STATUS_HUMAN_REVIEW = "HUMAN_REVIEW_REQUIRED"
STATUS_FAILED = "FAILED"

_REVIEW_QA = frozenset({"inconclusive", "provisional_pass"})

# Live InstantID node types that must appear in ComfyUI /object_info.
_INSTANTID_LIVE_NODE_TYPES = tuple(
    sorted(
        t
        for t in INSTANTID_REQUIRED_GRAPH_NODES
        if t
        in {
            "InstantIDModelLoader",
            "InstantIDFaceAnalysis",
            "ApplyInstantIDAdvanced",
        }
    )
)


@dataclass
class CharacterResolveResult:
    ok: bool
    character_id: str = ""
    display_name: str = ""
    auto_selected: bool = False
    selection_required: bool = False
    candidates: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "character_id": self.character_id,
            "display_name": self.display_name,
            "auto_selected": self.auto_selected,
            "selection_required": self.selection_required,
            "candidates": list(self.candidates),
            "errors": list(self.errors),
            "messages": list(self.messages),
        }


def _valid_characters(drive_root: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for record in list_characters(drive_root):
        ok, _ = verify_character_face(drive_root, record)
        if not ok:
            continue
        rows.append((record.character_id, record.display_name or record.character_id))
    return rows


def resolve_production_character(
    drive_root: Path,
    *,
    character_id: str | None = None,
    interactive: bool = True,
    input_fn: Callable[[str], str] | None = None,
) -> CharacterResolveResult:
    """Resolve character without inventing a new schema.

    Priority: explicit ID → single valid character → interactive numbered pick → fail.
    """
    result = CharacterResolveResult(ok=False)
    ask = input_fn or input
    explicit = str(character_id or "").strip()
    if explicit:
        record = load_character(drive_root, explicit)
        if record is None:
            result.errors.append(f"ERROR: Character not found: {explicit}")
            result.errors.append(
                "Register a character via Characters → Register character "
                "(or core/scripts/register_character.py)."
            )
            return result
        ok, err = verify_character_face(drive_root, record)
        if not ok:
            result.errors.append(err or f"ERROR: Character face verification failed: {explicit}")
            return result
        result.ok = True
        result.character_id = record.character_id
        result.display_name = record.display_name or record.character_id
        result.messages.append(f"Using character: {result.display_name} ({result.character_id})")
        return result

    valid = _valid_characters(drive_root)
    result.candidates = [{"character_id": cid, "display_name": name} for cid, name in valid]
    if not valid:
        result.errors.append("ERROR: No valid registered characters available.")
        result.errors.append(
            "Register a character via Characters → Register character "
            "(or core/scripts/register_character.py), then retry."
        )
        return result
    if len(valid) == 1:
        cid, name = valid[0]
        result.ok = True
        result.character_id = cid
        result.display_name = name
        result.auto_selected = True
        result.messages.append(f"Auto-selected sole valid character: {name} ({cid})")
        return result

    result.selection_required = True
    if not interactive:
        result.errors.append(
            "ERROR: Multiple characters available; pass --character-id "
            "or run interactively to select."
        )
        for i, (cid, name) in enumerate(valid, start=1):
            result.messages.append(f"  {i}. {name} ({cid})")
        return result

    print("Multiple characters available — select one:")
    for i, (cid, name) in enumerate(valid, start=1):
        print(f"  {i}. {name} ({cid})")
    raw = ask("Select number: ").strip()
    try:
        idx = int(raw)
    except ValueError:
        result.errors.append("ERROR: Invalid character selection.")
        return result
    if idx < 1 or idx > len(valid):
        result.errors.append("ERROR: Character selection out of range.")
        return result
    cid, name = valid[idx - 1]
    result.ok = True
    result.character_id = cid
    result.display_name = name
    result.messages.append(f"Selected character: {name} ({cid})")
    return result


def parse_production_scenarios(raw: str | None = None) -> list[str]:
    text = str(raw or "S1-S4").strip().lower()
    if not text or text in {"all", "s1-s4", "s1–s4"}:
        return list(SCENARIO_IDS)
    parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
    out: list[str] = []
    for part in parts:
        canonical = normalize_scenario_id(part)
        if canonical is None:
            raise ValueError(part)
        if canonical not in out:
            out.append(canonical)
    return out


def find_reusable_scenario_row(
    ledger_path: Path,
    *,
    character_id: str,
    scenario: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return (row, ambiguity_error).

    Reuse when durable artifact exists and SHA matches.
    Fail closed on SHA mismatch or missing required durable path with ledger claim.
    """
    matches: list[dict[str, Any]] = []
    for row in load_architecture_benchmark_records(ledger_path):
        if str(row.get("character_id") or "") != character_id:
            continue
        if str(row.get("scenario") or "") != scenario:
            continue
        matches.append(row)
    if not matches:
        return None, None

    # Prefer newest matching row.
    row = matches[-1]
    path_s = str(row.get("output_path") or "").strip()
    expected = str(row.get("output_sha256") or "").strip().lower()
    if not path_s or not expected:
        return None, (
            f"Ambiguous recovery for {scenario}: ledger row missing output_path/SHA "
            f"(prompt_id={row.get('prompt_id') or '-'})."
        )
    path = Path(path_s)
    if not path.is_file():
        return None, (
            f"Ambiguous recovery for {scenario}: durable artifact missing at {path_s} "
            f"(SHA claimed {expected})."
        )
    try:
        actual = file_sha256(path).lower()
    except OSError as exc:
        return None, f"Ambiguous recovery for {scenario}: cannot hash durable artifact: {exc}"
    if actual != expected:
        return None, (
            f"SHA mismatch for {scenario}: ledger={expected} file={actual} path={path_s}"
        )
    return row, None


def _qa_status(row: dict[str, Any]) -> str:
    qa = row.get("automated_qa") if isinstance(row.get("automated_qa"), dict) else {}
    if not qa and isinstance(row.get("qa"), dict):
        qa = row["qa"]
    return str(qa.get("automated_quality_status") or row.get("automated_quality_status") or "")


def derive_workflow_status(
    *,
    scenario_rows: list[dict[str, Any]],
    scenarios_requested: list[str],
    hard_failure: str | None = None,
) -> tuple[str, bool, str | None]:
    """Map scenario outcomes → COMPLETE | HUMAN_REVIEW_REQUIRED | FAILED."""
    if hard_failure:
        return STATUS_FAILED, False, hard_failure

    if not scenario_rows:
        return STATUS_FAILED, False, "No scenario results."

    review_needed = False
    failure_reason: str | None = None
    completed_ids = [str(r.get("scenario") or "") for r in scenario_rows]

    for row in scenario_rows:
        scenario = str(row.get("scenario") or "")
        if row.get("ok") is False and not row.get("reused"):
            # Infrastructure / capture / hard QA fail
            qa = _qa_status(row)
            if qa == "fail" or row.get("execution_failed"):
                failure_reason = failure_reason or (
                    f"{scenario}: " + ("; ".join(row.get("errors") or []) or "execution/QA failed")
                )
            elif qa in _REVIEW_QA:
                review_needed = True
            else:
                failure_reason = failure_reason or (
                    f"{scenario}: " + ("; ".join(row.get("errors") or []) or "failed")
                )
            continue
        qa = _qa_status(row)
        if qa == "fail":
            failure_reason = failure_reason or f"{scenario}: automated QA fail"
        elif qa in _REVIEW_QA:
            review_needed = True
        elif not qa and row.get("human_review_required"):
            review_needed = True

    if failure_reason:
        return STATUS_FAILED, False, failure_reason

    missing = [s for s in scenarios_requested if s not in completed_ids]
    if missing and not review_needed:
        # Stopped early without completing all — treat incomplete as fail unless review pause.
        return STATUS_FAILED, False, f"Incomplete scenarios: {', '.join(missing)}"

    if review_needed or missing:
        # incompleteness after inconclusive pause still surfaces as human review
        return STATUS_HUMAN_REVIEW, True, None

    return STATUS_COMPLETE, False, None


def confirm_gpu_execution(
    *,
    user_confirmed: bool = False,
    operator_live_intent: bool = False,
    interactive: bool = True,
    input_fn: Callable[[str], str] | None = None,
) -> tuple[bool, str]:
    """Wrapper intent gate. Does not weaken lower-level runner ack flags."""
    if operator_live_intent:
        return True, "Operator live-run intent satisfied routine benchmark confirmation."
    if user_confirmed:
        return True, "User confirmed GPU benchmark execution."
    if not interactive:
        return False, (
            "GPU confirmation required: pass --user-confirmed-gpu-run "
            "or --operator-live-intent, or run interactively."
        )
    ask = input_fn or input
    raw = ask(
        "Run the full S1-S4 production identity benchmark now? "
        "This will use the active GPU runtime. [y/N]: "
    ).strip().lower()
    if raw in {"y", "yes"}:
        return True, "Interactive user confirmed GPU benchmark execution."
    return False, "Cancelled — no GPU execution (confirmation declined)."


def may_satisfy_benchmark_confirmation(*, explicit_live_run_request: bool) -> bool:
    """Cursor may auto-satisfy routine confirmation only on explicit live-run requests."""
    return bool(explicit_live_run_request)


def run_production_runtime_preflight(
    repo_root: Path,
    bundle: Any,
    *,
    allow_missing_models: bool = False,
    allow_missing_nodes: bool = False,
    allow_unverified_assets: bool = False,
    base_url: str | None = None,
    comfy_reachable_fn: Callable[..., bool] | None = None,
    object_info_fn: Callable[..., tuple[str, dict[str, Any] | None, str, list]] | None = None,
    watcher_check_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Verify production runtime readiness before GPU scenarios.

    Sequence:
      1. ComfyUI reachable
      2. InstantID node types live in /object_info
      3. InstantID structural node/model registry readiness
      4. InstantID asset hash/verification readiness
      5. License gate evaluation (existing semantics; does not alone block investigation)
      6. OutputWatcher healthy for current runtime
    """
    from .identity_benchmark import _fetch_comfy_object_info

    drive_root = bundle.path("drive_root")
    comfy_runtime = bundle.path("comfyui_runtime")
    base = base_url or DEFAULT_COMFY_BASE_URL
    steps: list[dict[str, Any]] = []
    errors: list[str] = []
    messages: list[str] = []
    warnings: list[str] = []

    reachable_fn = comfy_reachable_fn or comfyui_reachable
    reachable = bool(reachable_fn(base))
    steps.append({"step": "comfyui_reachable", "ok": reachable, "base_url": base})
    if not reachable:
        errors.append(
            f"ERROR: ComfyUI is not reachable at {base}. "
            "Full Launch (control panel → 1 → full) and confirm ComfyUI is running, then retry."
        )

    oi_status = "unchecked"
    oi_notes = ""
    missing_live: list[str] = []
    if reachable:
        fetch = object_info_fn or _fetch_comfy_object_info
        oi_status, oi_payload, oi_notes, _attempts = fetch(base)
        keys = set(oi_payload.keys()) if isinstance(oi_payload, dict) else set()
        missing_live = [t for t in _INSTANTID_LIVE_NODE_TYPES if t not in keys]
        live_ok = oi_status == "ok" and not missing_live
        steps.append(
            {
                "step": "instantid_live_nodes",
                "ok": live_ok,
                "object_info_status": oi_status,
                "notes": oi_notes,
                "required": list(_INSTANTID_LIVE_NODE_TYPES),
                "missing": missing_live,
            }
        )
        if oi_status != "ok":
            errors.append(
                f"ERROR: ComfyUI /object_info status={oi_status} ({oi_notes}). "
                "Confirm Full Launch completed and InstantID custom nodes imported."
            )
        elif missing_live:
            errors.append(
                "ERROR: Required InstantID node types not live in ComfyUI object_info: "
                + ", ".join(missing_live)
                + ". Full Launch / install_nodes, then restart ComfyUI if needed."
            )
    else:
        steps.append(
            {
                "step": "instantid_live_nodes",
                "ok": False,
                "object_info_status": "skipped",
                "notes": "skipped — ComfyUI unreachable",
                "required": list(_INSTANTID_LIVE_NODE_TYPES),
                "missing": list(_INSTANTID_LIVE_NODE_TYPES),
            }
        )

    structural = assess_instantid_structural_readiness(
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
            warnings.append(
                "WARN: allow_missing_models — structural model gaps ignored for investigation."
            )
        if allow_missing_nodes:
            warnings.append(
                "WARN: allow_missing_nodes — structural node gaps ignored for investigation."
            )
    steps.append({"step": "instantid_structural", "ok": structural_ok, "detail": structural})
    if not structural_ok:
        missing_m = structural.get("models_missing") or []
        missing_n = structural.get("nodes_missing") or []
        errors.append(
            "ERROR: InstantID structural readiness failed "
            f"(models_missing={missing_m}; nodes_missing={missing_n}). "
            "Run Full Launch and place required InstantID assets; see Characters → Advanced → Dependency diagnostics."
        )

    assets = assess_instantid_asset_readiness(
        drive_root=drive_root,
        bundle_models=list(bundle.models),
        comfyui_runtime=comfy_runtime,
    )
    assets_ok = bool(assets.get("ready")) or allow_unverified_assets
    if allow_unverified_assets and not assets.get("ready"):
        warnings.append(
            "WARN: allow_unverified_assets — InstantID hash gate overridden for investigation only; "
            "promotion remains blocked."
        )
    steps.append({"step": "instantid_assets", "ok": assets_ok, "detail": assets})
    if not assets_ok:
        for err in assets.get("errors") or ["ERROR: InstantID assets not verified."]:
            errors.append(str(err))
        errors.append(
            "ACTION: Verify InstantID model hashes on Drive / run Full Launch asset bridge; "
            "do not use --allow-unverified-assets for production claims."
        )

    license_gate = assess_instantid_license_gate(repo_root)
    steps.append(
        {
            "step": "license_gate",
            "ok": True,  # evaluated; does not alone fail investigation preflight
            "detail": license_gate,
            "promotion_allowed": bool(license_gate.get("promotion_allowed")),
        }
    )
    messages.append(
        "License gate evaluated "
        f"(status={license_gate.get('overall_status')}; "
        f"promotion_allowed={license_gate.get('promotion_allowed')})."
    )

    watcher_fn = watcher_check_fn or check_output_watcher
    watcher = watcher_fn(bundle)
    watcher_status = getattr(watcher, "status", None)
    watcher_details = getattr(watcher, "details", {}) or {}
    ownership = str(watcher_details.get("ownership_state") or "")
    watcher_ok = watcher_status == HealthStatus.OK and ownership in {"", "current_runtime"}
    if watcher_status == HealthStatus.OK:
        watcher_ok = True
    elif watcher_status == HealthStatus.WARN and ownership == "current_runtime":
        watcher_ok = True
        warnings.append(f"WARN: OutputWatcher WARN but current-runtime: {getattr(watcher, 'message', '')}")
    else:
        watcher_ok = False
    steps.append(
        {
            "step": "output_watcher",
            "ok": watcher_ok,
            "status": str(watcher_status.value if hasattr(watcher_status, "value") else watcher_status),
            "message": getattr(watcher, "message", ""),
            "ownership_state": ownership,
        }
    )
    if not watcher_ok:
        errors.append(
            "ERROR: OutputWatcher is not healthy for the current runtime "
            f"(status={watcher_status}; ownership={ownership or 'absent'}). "
            f"{getattr(watcher, 'message', '')} "
            "ACTION: Complete Full Launch so OutputWatcher is running for this runtime "
            "(non-destructive); do not Full Reset."
        )

    ok = not errors
    return {
        "ok": ok,
        "steps": steps,
        "errors": errors,
        "messages": messages,
        "warnings": warnings,
        "license_gate": license_gate,
        "preflight_sequence": [
            "comfyui_reachable",
            "instantid_live_nodes",
            "instantid_structural",
            "instantid_assets",
            "license_gate",
            "output_watcher",
        ],
    }


def apply_consolidated_qa_to_status(
    status: str,
    *,
    consolidated_ok: bool | None,
    consolidated_ran: bool,
) -> tuple[str, str | None]:
    """Consolidate QA failure forces FAILED; never COMPLETE on consolidated fail."""
    if not consolidated_ran:
        return status, None
    if consolidated_ok is False:
        return STATUS_FAILED, "Package 4.12.3 consolidated QA failed."
    return status, None


def run_production_identity_benchmark(
    repo_root: Path,
    *,
    character_id: str | None = None,
    scenarios: list[str] | None = None,
    user_confirmed_gpu_run: bool = False,
    operator_live_intent: bool = False,
    interactive: bool = True,
    input_fn: Callable[[str], str] | None = None,
    continue_after_fail: bool = False,
    completion_timeout_seconds: float = 600.0,
    allow_missing_models: bool = False,
    allow_missing_nodes: bool = False,
    allow_unverified_assets: bool = False,
    seed: int | None = None,
    execute_fn: Callable[..., Any] | None = None,
    skip_gpu_confirmation: bool = False,
    skip_preflight: bool = False,
    preflight_fn: Callable[..., dict[str, Any]] | None = None,
    consolidated_qa_fn: Callable[..., dict[str, Any]] | None = None,
    skip_consolidated_qa: bool = False,
    allow_blocked_instantid: bool = False,
) -> dict[str, Any]:
    """One-action production identity benchmark (default S1–S4).

    InstantID production / Characters option 11 is blocked while the InstantID
    license gate remains BLOCKED_FOR_COMMERCIAL (InsightFace). Tests may pass
    allow_blocked_instantid=True to exercise orchestration plumbing only.
    """
    from .identity_architecture_plugin import is_instantid_production_blocked

    bundle = RegistryLoader(repo_root).load_all()
    drive_root = bundle.path("drive_root")
    comfy_runtime = bundle.path("comfyui_runtime")
    ledger = architecture_ledger_path(drive_root)
    requested = list(scenarios) if scenarios is not None else list(SCENARIO_IDS)

    payload: dict[str, Any] = {
        "status": STATUS_FAILED,
        "character_id": "",
        "display_name": "",
        "scenarios_requested": requested,
        "scenarios_completed": [],
        "scenarios_skipped_reuse": [],
        "prompt_ids": [],
        "durable_artifact_paths": [],
        "ledger_path": str(ledger),
        "report_paths": [],
        "report_text_path": "",
        "automated_qa_summary": {},
        "human_review_required": False,
        "human_review_instructions": "",
        "failure_reason": None,
        "results": [],
        "ok": False,
        "execute_benchmark": True,
        "browser_required": False,
        "preflight": None,
        "consolidated_qa_ran": False,
        "consolidated_qa_status": None,
        "consolidated_qa_report_path": None,
        "consolidated_qa_failures": [],
        "architecture_id": "instantid_sdxl",
        "option_11_blocked": False,
    }

    blocked, license_gate = is_instantid_production_blocked(repo_root)
    payload["instantid_license_gate"] = license_gate
    if blocked and not allow_blocked_instantid:
        payload["option_11_blocked"] = True
        payload["failure_reason"] = (
            "BLOCKED: InstantID production identity path is BLOCKED_FOR_COMMERCIAL "
            f"(status={license_gate.get('overall_status')}; "
            f"promotion_allowed={license_gate.get('promotion_allowed')}). "
            "Characters option 11 refused. Prototype path: ipadapter_plus_face_sdxl "
            "(PATH C). Do not weaken InstantID gates."
        )
        payload["status"] = STATUS_FAILED
        print(payload["failure_reason"])
        return payload

    resolve = resolve_production_character(
        drive_root,
        character_id=character_id,
        interactive=interactive,
        input_fn=input_fn,
    )
    payload["character_resolve"] = resolve.to_dict()
    for msg in resolve.messages:
        print(msg)
    if not resolve.ok:
        payload["failure_reason"] = "; ".join(resolve.errors) or "Character resolution failed."
        payload["status"] = STATUS_FAILED
        for err in resolve.errors:
            print(err)
        return payload

    payload["character_id"] = resolve.character_id
    payload["display_name"] = resolve.display_name

    if not skip_gpu_confirmation:
        confirmed, confirm_msg = confirm_gpu_execution(
            user_confirmed=user_confirmed_gpu_run,
            operator_live_intent=operator_live_intent,
            interactive=interactive,
            input_fn=input_fn,
        )
        payload["gpu_confirmation"] = confirm_msg
        print(confirm_msg)
        if not confirmed:
            payload["failure_reason"] = confirm_msg
            payload["status"] = STATUS_FAILED
            return payload
        payload["ack_flags_satisfied_by_wrapper"] = [
            "--execute-benchmark",
            "--allow-benchmark",
            "--i-acknowledge-gpu-cost",
        ]
        print(
            "Wrapper confirmation satisfies controlled invoke of live InstantID execution "
            "(lower-level runner ack semantics preserved; flags not typed by the user)."
        )

    if not skip_preflight:
        print("\n--- Production runtime preflight ---")
        preflight = (preflight_fn or run_production_runtime_preflight)(
            repo_root,
            bundle,
            allow_missing_models=allow_missing_models,
            allow_missing_nodes=allow_missing_nodes,
            allow_unverified_assets=allow_unverified_assets,
        )
        payload["preflight"] = preflight
        for msg in preflight.get("messages") or []:
            print(f"- {msg}")
        for warn in preflight.get("warnings") or []:
            print(warn)
        for err in preflight.get("errors") or []:
            print(err)
        if not preflight.get("ok"):
            payload["failure_reason"] = "; ".join(preflight.get("errors") or []) or "Runtime preflight failed."
            payload["status"] = STATUS_FAILED
            print(f"\nstatus={payload['status']}")
            return payload
        print("Preflight OK — proceeding to S1–S4.")

    runner = execute_fn or execute_architecture_scenario
    scenario_rows: list[dict[str, Any]] = []
    stopped = False
    hard_failure: str | None = None

    for scenario in requested:
        reused, ambiguity = find_reusable_scenario_row(
            ledger,
            character_id=resolve.character_id,
            scenario=scenario,
        )
        if ambiguity:
            hard_failure = ambiguity
            print(f"ERROR: {ambiguity}")
            stopped = True
            break

        if reused is not None:
            qa = reused.get("automated_qa") if isinstance(reused.get("automated_qa"), dict) else {}
            row = {
                "ok": True,
                "reused": True,
                "scenario": scenario,
                "prompt_id": reused.get("prompt_id") or "",
                "output_path": reused.get("output_path") or "",
                "output_sha256": reused.get("output_sha256") or "",
                "preparation_id": reused.get("preparation_id") or "",
                "automated_qa": qa,
                "queue_status": "reused_durable",
                "capture_status": "reused",
                "messages": [
                    f"Reused durable evidence for {scenario} "
                    f"(prompt_id={reused.get('prompt_id') or '-'}; no duplicate capture)."
                ],
                "errors": [],
            }
            print(row["messages"][0])
            scenario_rows.append(row)
            payload["scenarios_skipped_reuse"].append(scenario)
            auto_status = _qa_status(row)
            if auto_status == "inconclusive":
                stopped = True
                break
            if should_fail_fast(scenario, qa, continue_after_fail=continue_after_fail):
                if auto_status == "fail":
                    hard_failure = f"{scenario}: automated QA fail (reused durable evidence)"
                stopped = True
                break
            continue

        print(f"\n--- Executing {scenario} via ComfyUI /prompt ---")
        exec_result = runner(
            repo_root=repo_root,
            drive_root=drive_root,
            character_id=resolve.character_id,
            scenario=scenario,
            bundle_models=list(bundle.models),
            bundle_nodes=list(bundle.nodes),
            runtime_prepared_root=bundle.path("runtime_root") / "prepared_workflows",
            comfyui_input_dir=comfy_runtime / "input",
            comfyui_runtime=comfy_runtime,
            comfyui_output_dir=comfy_runtime / "output",
            drive_prepared_root=bundle.path("drive_workflows") / "prepared",
            seed=seed,
            completion_timeout_seconds=completion_timeout_seconds,
            require_models=not allow_missing_models,
            require_nodes=not allow_missing_nodes,
            require_verified_assets=not allow_unverified_assets,
            asset_verification_override=bool(allow_unverified_assets),
        )
        if hasattr(exec_result, "to_dict"):
            row = exec_result.to_dict()
        else:
            row = dict(exec_result)
        row["reused"] = False
        scenario_rows.append(row)
        for message in row.get("messages") or []:
            print(f"- {message}")
        for error in row.get("errors") or []:
            print(error)

        qa = row.get("automated_qa") or {}
        auto_status = str(qa.get("automated_quality_status") or "")
        if auto_status == "inconclusive":
            stopped = True
            break
        if should_fail_fast(scenario, qa, continue_after_fail=continue_after_fail):
            stopped = True
            if auto_status == "fail":
                hard_failure = hard_failure or f"{scenario}: automated QA fail"
            break
        if not row.get("ok"):
            hard_failure = hard_failure or (
                f"{scenario}: " + ("; ".join(row.get("errors") or []) or "execution failed")
            )
            stopped = True
            break

    payload["results"] = scenario_rows
    payload["scenarios_completed"] = [str(r.get("scenario") or "") for r in scenario_rows]
    payload["prompt_ids"] = [str(r.get("prompt_id") or "") for r in scenario_rows if r.get("prompt_id")]
    payload["durable_artifact_paths"] = [
        str(r.get("output_path") or "") for r in scenario_rows if r.get("output_path")
    ]
    payload["stopped_fail_fast"] = stopped

    status, human_review, failure_reason = derive_workflow_status(
        scenario_rows=scenario_rows,
        scenarios_requested=requested,
        hard_failure=hard_failure,
    )
    # If stopped on inconclusive without hard_failure, force human review.
    if stopped and not hard_failure:
        for r in scenario_rows:
            if _qa_status(r) in _REVIEW_QA:
                status = STATUS_HUMAN_REVIEW
                human_review = True
                failure_reason = None
                break

    # Consolidated Package 4.12.3 QA after scenario/capture stage.
    if not skip_consolidated_qa:
        print("\n--- Package 4.12.3 consolidated QA ---")
        qa_runner = consolidated_qa_fn or run_consolidated_package4123_qa
        try:
            cqa = qa_runner(repo_root, print_summary=True, write_reports=True)
        except TypeError:
            # Allow simple test doubles: fn(repo_root) -> dict
            cqa = qa_runner(repo_root)
        payload["consolidated_qa_ran"] = True
        payload["consolidated_qa_status"] = (
            "PASS" if cqa.get("ok") or cqa.get("all_required_suites_pass") else "FAIL"
        )
        payload["consolidated_qa_report_path"] = (
            cqa.get("report_path")
            or (cqa.get("report_paths") or [None])[0]
            or None
        )
        failures = []
        for suite in cqa.get("suites") or []:
            if not suite.get("ok"):
                failures.append(
                    f"{suite.get('name')}: failed={suite.get('failed')} "
                    f"exit={suite.get('exit_code')}"
                )
        tz = cqa.get("timezone_checks") or {}
        if tz and not tz.get("ok") and not tz.get("skipped_by_caller"):
            failures.append("timezone_inline: FAIL")
        payload["consolidated_qa_failures"] = failures
        payload["consolidated_qa"] = {
            "ok": bool(cqa.get("ok") or cqa.get("all_required_suites_pass")),
            "totals": cqa.get("totals"),
            "report_path": payload["consolidated_qa_report_path"],
        }
        status, cqa_fail = apply_consolidated_qa_to_status(
            status,
            consolidated_ok=payload["consolidated_qa"]["ok"],
            consolidated_ran=True,
        )
        if cqa_fail:
            failure_reason = cqa_fail
            human_review = False
            print(f"ERROR: {cqa_fail}")
    else:
        payload["consolidated_qa_ran"] = False
        payload["consolidated_qa_status"] = "SKIPPED"

    payload["status"] = status
    payload["human_review_required"] = human_review or status == STATUS_HUMAN_REVIEW
    payload["failure_reason"] = failure_reason
    payload["ok"] = status == STATUS_COMPLETE

    qa_by_scenario = {
        str(r.get("scenario") or ""): _qa_status(r) for r in scenario_rows
    }
    payload["automated_qa_summary"] = qa_by_scenario

    if payload["human_review_required"]:
        instructions = [
            "HUMAN_REVIEW_REQUIRED — do not promote InstantID automatically.",
            "Review the durable benchmark outputs and automated measurements below.",
            "Judgment needed: visual identity match + scenario adherence for listed scenarios.",
        ]
        for r in scenario_rows:
            qa = r.get("automated_qa") or {}
            if _qa_status(r) not in _REVIEW_QA and not r.get("human_review_required"):
                continue
            instructions.append(
                f"- {r.get('scenario')}: qa={_qa_status(r) or 'n/a'}; "
                f"prompt_id={r.get('prompt_id') or '-'}; "
                f"artifact={r.get('output_path') or '-'}; "
                f"identity={qa.get('identity_gate')}; "
                f"adherence={qa.get('scenario_adherence_gate')}"
            )
        payload["human_review_instructions"] = "\n".join(instructions)
        print("\n" + payload["human_review_instructions"])

    # Persist a concise status/report artifact for operator collection.
    logs_dir = Path(drive_root) / "logs" / "qa"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        stamp = resolve.character_id[-8:]
        report_json = logs_dir / f"production_identity_benchmark_{stamp}.json"
        report_txt = logs_dir / f"production_identity_benchmark_{stamp}.txt"
        report_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        text_lines = [
            "AI Studio — Production Identity Benchmark (one-action)",
            "=" * 50,
            f"status: {payload['status']}",
            f"character: {payload['display_name']} ({payload['character_id']})",
            f"scenarios: {', '.join(requested)}",
            f"completed: {', '.join(payload['scenarios_completed']) or '-'}",
            f"reused: {', '.join(payload['scenarios_skipped_reuse']) or '-'}",
            f"ledger: {ledger}",
            f"consolidated_qa_ran: {payload.get('consolidated_qa_ran')}",
            f"consolidated_qa_status: {payload.get('consolidated_qa_status')}",
            f"consolidated_qa_report: {payload.get('consolidated_qa_report_path') or '-'}",
            "",
            format_architecture_benchmark_report(load_architecture_benchmark_records(ledger)),
        ]
        if payload.get("human_review_instructions"):
            text_lines.extend(["", payload["human_review_instructions"]])
        if payload.get("failure_reason"):
            text_lines.extend(["", f"failure_reason: {payload['failure_reason']}"])
        report_txt.write_text("\n".join(text_lines), encoding="utf-8")
        payload["report_paths"] = [str(report_json), str(report_txt)]
        payload["report_text_path"] = str(report_txt)
        print(f"\nStatus report: {report_json}")
        print(f"Human report:  {report_txt}")
    except OSError as exc:
        payload.setdefault("messages", [])
        if isinstance(payload["messages"], list):
            payload["messages"].append(f"WARN: Could not write status report: {exc}")

    print(f"\nstatus={payload['status']}")
    return payload
