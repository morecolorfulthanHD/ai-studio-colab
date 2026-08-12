#!/usr/bin/env python3
"""Read-only diagnostic for prepared-workflow execution Drive autosync (Package 4.8.5).

Does not queue /prompt, copy files, mutate archives, or start/stop the watcher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.comfyui_events import (
    DEFAULT_COMFY_BASE,
    collect_named_file_mentions,
    describe_history_output_shape,
    extract_output_files,
    fetch_history,
    history_entry_completed,
    history_prompt_has_save_image,
)
from core.runtime.generation_evidence_ledger import EvidenceLedger
from core.runtime.output_autosync import (
    AMBIGUOUS_PREFIX_RECOVERY,
    OutputAutoSyncService,
)
from core.runtime.output_evidence import is_eligible_output
from core.runtime.prepared_workflow_index import find_by_preparation_id, preparations_log_path
from core.runtime.preparation_identity import InvalidPreparationIdError, normalize_preparation_id
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.runtime_identity import watcher_status_path
from core.runtime.workflow_provenance import (
    extract_ai_studio_extra,
    extract_ui_workflow_from_history,
)
from core.scripts.run_output_watcher import _ownership_snapshot


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _describe_local(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "filename": path.name,
        "path": str(path),
        "size_bytes": stat.st_size,
        "mtime": stat.st_mtime,
        "sha256": _sha256(path),
    }


def _history_mentions_prep(entry: dict, preparation_id: str) -> bool:
    ui = extract_ui_workflow_from_history(entry)
    meta = extract_ai_studio_extra(ui)
    if str(meta.get("preparation_id") or "") == preparation_id:
        return True
    dumped = json.dumps(entry, default=str)
    return preparation_id in dumped


def diagnose(
    *,
    repo_root: Path,
    preparation_id: str | None,
    comfy_base_url: str,
) -> dict[str, object]:
    bundle = RegistryLoader(repo_root).load_all()
    drive_root = bundle.path("drive_root")
    comfy_out = bundle.path("comfyui_output")
    drive_out = bundle.path("drive_outputs")
    evidence_path = bundle.path("drive_logs") / "generation_evidence.jsonl"
    processed_path = bundle.path("drive_logs") / "autosync" / "output_watcher_processed.json"
    status_path = watcher_status_path(bundle)
    workspace = ProjectWorkspace(drive_root)
    active = workspace.get_active_project()
    from core.runtime.runtime_identity import read_runtime_identity, runtime_identity_path, watcher_lock_path

    runtime = read_runtime_identity(runtime_identity_path(bundle))
    ownership = _ownership_snapshot(
        lock_path=watcher_lock_path(bundle),
        status_path=status_path,
        runtime=runtime,
        repo_root=repo_root,
    )

    prep_record = None
    if preparation_id:
        prep_record = find_by_preparation_id(preparations_log_path(drive_root), preparation_id)

    history: dict = {}
    history_error = ""
    history_reachable = False
    try:
        history = fetch_history(base_url=comfy_base_url)
        history_reachable = True
    except RuntimeError as exc:
        history_error = str(exc)

    rows = EvidenceLedger(evidence_path).read_all() if evidence_path.is_file() else []
    verified_prompt_ids = {
        str(row.get("prompt_id") or "")
        for row in rows
        if str(row.get("sync_status") or "") == "verified"
    }

    analyzer = OutputAutoSyncService(
        comfy_output_dir=comfy_out,
        drive_output_dir=drive_out,
        evidence_path=evidence_path,
        index_path=processed_path,
        status_path=status_path,
        base_url=comfy_base_url,
        sleep_fn=lambda _s: None,
    )

    related: list[dict[str, object]] = []
    for prompt_id, entry in history.items():
        if not isinstance(entry, dict):
            continue
        if preparation_id and not _history_mentions_prep(entry, preparation_id):
            continue
        if not preparation_id and not extract_ai_studio_extra(extract_ui_workflow_from_history(entry)):
            continue
        shape = describe_history_output_shape(entry)
        analysis = analyzer.analyze_saveimage_prefix_recovery(entry, prompt_id=str(prompt_id))
        ui = extract_ui_workflow_from_history(entry)
        meta = extract_ai_studio_extra(ui)
        related.append(
            {
                "prompt_id": str(prompt_id),
                "prompt_present_in_history": True,
                "prompt_completed": history_entry_completed(entry),
                "has_save_image": history_prompt_has_save_image(entry),
                "output_metadata_shape": shape,
                "flattened_images_found": shape["flattened_images_found"],
                "nested_ui_images_found": shape["nested_ui_images_found"],
                "nested_output_images_found": shape["nested_output_images_found"],
                "saveimage_prefix": analysis.get("saveimage_prefix") or "",
                "prefix_recovery_candidate_count": analysis.get("prefix_candidate_count") or 0,
                "prefix_candidate_count": analysis.get("prefix_candidate_count") or 0,
                "exact_history_file_count": analysis.get("exact_history_file_count") or 0,
                "execution_timestamp_available": bool(analysis.get("execution_timestamp_available")),
                "timestamp_window_candidate_count": analysis.get("timestamp_window_candidate_count") or 0,
                "competitor_check_available": bool(analysis.get("competitor_check_available")),
                "competitor_check_status": analysis.get("competitor_check_status") or "unavailable",
                "prefix_recovery_ambiguous": bool(analysis.get("prefix_recovery_ambiguous")),
                "competing_unresolved_prompt_ids": analysis.get("competing_unresolved_prompt_ids") or [],
                "attribution_reason": analysis.get("attribution_reason") or "",
                "named_file_mentions": collect_named_file_mentions(entry),
                "extractable_outputs": extract_output_files(entry),
                "status": entry.get("status"),
                "preparation_id": meta.get("preparation_id"),
                "workflow_identifier": meta.get("workflow_identifier"),
                "prepared_workflow_hash": meta.get("prepared_workflow_hash"),
                "comfyui_load_workflow_hash": meta.get("comfyui_load_workflow_hash"),
                "canonical_workflow_identifier": meta.get("workflow_identifier"),
            }
        )

    local_outputs = []
    if comfy_out.is_dir():
        candidates = [p for p in comfy_out.rglob("*") if is_eligible_output(p)]
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        local_outputs = [_describe_local(p) for p in candidates[:20]]

    related_ids = {str(item["prompt_id"]) for item in related}
    evidence_rows = [
        row
        for row in rows
        if str(row.get("prompt_id") or "") in related_ids
        or (preparation_id and str(row.get("preparation_id") or "") == preparation_id)
    ]

    processed = []
    if processed_path.is_file():
        try:
            payload = json.loads(processed_path.read_text(encoding="utf-8"))
            processed = list(payload) if isinstance(payload, list) else list(payload.get("keys") or [])
        except (OSError, json.JSONDecodeError):
            processed = []

    snapshots = []
    if active is not None:
        gen_root = Path(active.outputs_dir).parent / "generations"
        if gen_root.is_dir():
            for child in sorted(gen_root.iterdir()):
                if not child.is_dir() or not child.name.startswith("gen_"):
                    continue
                meta_path = child / "metadata.json"
                meta = {}
                if meta_path.is_file():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        meta = {}
                if preparation_id and str(meta.get("preparation_id") or "") != preparation_id:
                    continue
                snapshots.append(
                    {
                        "generation_id": child.name,
                        "path": str(child),
                        "has_manifest": (child / "manifest.json").is_file(),
                        "has_workflow": (child / "workflow.json").is_file(),
                        "canonical_output_path": meta.get("canonical_output_path"),
                        "preparation_id": meta.get("preparation_id"),
                    }
                )

    evidence_statuses = [str(row.get("sync_status") or "") for row in evidence_rows]
    global_copy_exists = any(
        str(row.get("sync_status") or "") == "verified" and bool(row.get("drive_path"))
        for row in evidence_rows
    )
    project_mirror_exists = any(bool(row.get("project_output_path")) for row in evidence_rows)
    recoverable = []
    for item in related:
        pid = str(item["prompt_id"])
        if pid in verified_prompt_ids:
            continue
        if item.get("extractable_outputs"):
            recoverable.append(pid)
            continue
        if item.get("attribution_reason") == "exact_history_filename":
            recoverable.append(pid)
            continue
        if (
            item.get("prompt_completed")
            and item.get("has_save_image")
            and item.get("attribution_reason") == "unique_prefix_and_execution_timestamp"
            and item.get("execution_timestamp_available")
            and item.get("competitor_check_available")
            and int(item.get("timestamp_window_candidate_count") or 0) == 1
            and not item.get("prefix_recovery_ambiguous")
        ):
            recoverable.append(pid)

    first = related[0] if related else {}

    return {
        "diagnostic_mode": "read_only",
        "package_version": "4.8.5",
        "preparation_id": preparation_id,
        "preparation_record_found": prep_record is not None,
        "preparation_record": {
            "workflow_identifier": (prep_record or {}).get("workflow_identifier"),
            "prepared_workflow_hash": (prep_record or {}).get("prepared_workflow_hash"),
            "project_slug": (prep_record or {}).get("project_slug"),
        }
        if prep_record
        else None,
        "watcher_current_runtime": ownership.get("ownership_state") == "current_runtime",
        "watcher_process_alive": bool(ownership.get("process_alive")),
        "heartbeat_fresh": bool(ownership.get("heartbeat_fresh")),
        "history_reachable": history_reachable,
        "watcher": ownership,
        "watcher_status_path": str(status_path),
        "history_error": history_error,
        "prompt_present_in_history": bool(related),
        "related_prompt_ids": [item["prompt_id"] for item in related],
        "related_prompts": related,
        "local_output_candidates": local_outputs,
        "evidence_status": evidence_statuses[-1] if evidence_statuses else "none",
        "evidence_rows": evidence_rows,
        "processed_index_status": {
            "path": str(processed_path),
            "exists": processed_path.is_file(),
            "key_count": len(processed),
        },
        "global_drive_copy_exists": global_copy_exists,
        "active_project": active.to_dict() if active else None,
        "project_mirror_exists": project_mirror_exists,
        "generation_snapshot_exists": bool(snapshots),
        "generation_snapshots": snapshots,
        "preparation_linkage": {
            "preparation_id": preparation_id,
            "related_preparation_ids": sorted(
                {
                    str(item.get("preparation_id") or "")
                    for item in related
                    if item.get("preparation_id")
                }
            ),
        },
        "expected_global_outputs_dir": str(drive_out),
        "expected_project_outputs_dir": str(Path(active.outputs_dir)) if active else None,
        "execution_timestamp_available": bool(first.get("execution_timestamp_available")),
        "competitor_check_available": (
            bool(first.get("competitor_check_available")) if related else history_reachable
        ),
        "timestamp_window_candidate_count": int(first.get("timestamp_window_candidate_count") or 0),
        "attribution_reason": str(first.get("attribution_reason") or ""),
        "recovery_possible_prompt_ids": recoverable,
        "recovery_possible": bool(recoverable),
        "ambiguous_recovery_token": AMBIGUOUS_PREFIX_RECOVERY,
        "notes": [
            "Watcher is not a directory scanner; it reconciles ComfyUI /history.",
            "The live symptom is consistent with a dead watcher or an unresolved "
            "completed-history output. Live Colab acceptance is required to identify "
            "which path caused the observed run.",
            "Prefix recovery is fail-closed: never newest-alone, never unique-prefix-alone.",
            "Does not claim browser or live Drive success.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only prepared execution autosync diagnostic (Package 4.8.5)."
    )
    parser.add_argument("--preparation-id", default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--comfy-base-url", default=DEFAULT_COMFY_BASE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    prep_id = None
    if args.preparation_id:
        try:
            prep_id = normalize_preparation_id(args.preparation_id)
        except InvalidPreparationIdError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    payload = diagnose(
        repo_root=repo_root,
        preparation_id=prep_id,
        comfy_base_url=args.comfy_base_url,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
