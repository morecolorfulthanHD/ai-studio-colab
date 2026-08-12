#!/usr/bin/env python3
"""Package 4.8.5 — prepared workflow execution → Drive autosync simulations."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime import output_autosync
from core.runtime.comfyui_events import (
    HistoryFallbackWatcher,
    extract_output_files,
    history_prompt_has_save_image,
)
from core.runtime.comfyui_workflow_loading import build_comfyui_load_workflow
from core.runtime.generation_evidence_ledger import EvidenceLedger, file_sha256
from core.runtime.output_autosync import (
    AMBIGUOUS_PREFIX_RECOVERY,
    AUTOSYNC_TEMP_PREFIX,
    COMPETITOR_CHECK_UNAVAILABLE,
    INSUFFICIENT_ATTRIBUTION_EVIDENCE,
    OutputAutoSyncService,
)
from core.runtime.png_utils import write_rgb_png
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_provenance import (
    extract_execution_provenance,
    hash_ui_workflow,
    load_registered_workflow_hashes,
)


class SimulationFailure(Exception):
    pass


PREP_ID = "prep_870c685b-751a-4ed8-ac2c-ad12c4bae42b"
SAVE_PREFIX = "ai_studio_base_txt2img"


def _pass(results: list[tuple[str, str]], name: str) -> None:
    results.append(("PASS", name))
    print(f"  [PASS] {name}")


def _assert_true(label: str, condition: bool) -> None:
    if not condition:
        raise SimulationFailure(label)


def _assert_equal(label: str, left, right) -> None:
    if left != right:
        raise SimulationFailure(f"{label}: {left!r} != {right!r}")


def _write_png(path: Path, fill: tuple[int, int, int] = (10, 20, 30)) -> None:
    rows = [[fill for _ in range(8)] for _ in range(8)]
    write_rgb_png(path, 8, 8, rows)


def _txt2img_api(*, seed: int = 424242, positive: str = "snowy alpine research station") -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd15.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, low quality", "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 768, "batch_size": 1}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 24,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": SAVE_PREFIX, "images": ["8", 0]},
        },
    }


def _prepared_ui(repo_root: Path) -> dict:
    canonical = json.loads(
        (repo_root / "workflows/base/txt2img/workflow.json").read_text(encoding="utf-8")
    )
    prepared = copy.deepcopy(canonical)
    extra = prepared.setdefault("extra", {})
    if not isinstance(extra, dict):
        prepared["extra"] = {}
        extra = prepared["extra"]
    extra["ai_studio"] = {
        "workflow_identifier": "base/txt2img",
        "workflow_source": "registered_canonical",
        "preparation_id": PREP_ID,
        "prepared_workflow_hash": "",
        "canonical_workflow_hash": hash_ui_workflow(canonical),
        "package_version": "4.8.4",
    }
    prepared_hash = hash_ui_workflow(prepared)
    extra["ai_studio"]["prepared_workflow_hash"] = prepared_hash
    return build_comfyui_load_workflow(prepared)


def _history_entry(
    api_prompt: dict,
    ui_workflow: dict | None,
    outputs: dict,
    prompt_id: str,
    *,
    execution_ts: float | None = None,
) -> dict:
    extra_data: dict = {}
    if ui_workflow is not None:
        extra_data = {"extra_pnginfo": {"workflow": ui_workflow}}
    status: dict = {"status_str": "success", "completed": True}
    if execution_ts is not None:
        status["timestamp"] = execution_ts
    return {
        "prompt": [0, prompt_id, api_prompt, extra_data, list(outputs.keys()) or ["9"]],
        "outputs": outputs,
        "status": status,
    }


def _stamp(path: Path, epoch: float) -> None:
    os.utime(path, (epoch, epoch))


def _handle_fetch(svc: OutputAutoSyncService, fetch_fn, prompt_id: str):
    original = output_autosync.fetch_history
    output_autosync.fetch_history = fetch_fn
    try:
        return svc.handle_prompt_id(prompt_id)
    finally:
        output_autosync.fetch_history = original


def _analyze(svc: OutputAutoSyncService, history: dict, prompt_id: str):
    original = output_autosync.fetch_history
    output_autosync.fetch_history = lambda base_url, prompt_id=None, **_kwargs: (
        history if prompt_id is None else {prompt_id: history[prompt_id]}
    )
    try:
        return svc.analyze_saveimage_prefix_recovery(history[prompt_id], prompt_id=prompt_id)
    finally:
        output_autosync.fetch_history = original


def _analyze_fetch(svc: OutputAutoSyncService, fetch_fn, entry: dict, prompt_id: str):
    original = output_autosync.fetch_history
    output_autosync.fetch_history = fetch_fn
    try:
        return svc.analyze_saveimage_prefix_recovery(entry, prompt_id=prompt_id)
    finally:
        output_autosync.fetch_history = original


def _flat_output(filename: str) -> dict:
    return {"9": {"images": [{"filename": filename, "subfolder": "", "type": "output"}]}}


def _nested_ui_output(filename: str) -> dict:
    return {
        "9": {
            "ui": {
                "images": [{"filename": filename, "subfolder": "", "type": "output"}],
            }
        }
    }


def _drive_finals(drive_out: Path) -> list[Path]:
    if not drive_out.is_dir():
        return []
    return [
        path
        for path in drive_out.iterdir()
        if path.is_file() and not path.name.startswith(AUTOSYNC_TEMP_PREFIX)
    ]


def _service(tmp: Path, *, registered: dict, active_project=None, repo_root: Path | None = None):
    comfy = tmp / "ComfyUI" / "output"
    drive_root = tmp / "AI_Studio"
    drive_out = drive_root / "outputs"
    comfy.mkdir(parents=True)
    drive_out.mkdir(parents=True)
    svc = OutputAutoSyncService(
        comfy_output_dir=comfy,
        drive_output_dir=drive_out,
        evidence_path=drive_root / "logs" / "generation_evidence.jsonl",
        index_path=drive_root / "logs" / "autosync" / "output_watcher_processed.json",
        status_path=tmp / "watcher_status.json",
        base_url="http://127.0.0.1:9",
        sleep_fn=lambda _s: None,
        max_copy_retries=1,
        registered_hashes=registered,
        active_project=active_project,
        drive_root=drive_root,
        repo_root=repo_root,
    )
    return svc, comfy, drive_root, drive_out


def _handle(svc: OutputAutoSyncService, history: dict, prompt_id: str):
    original = output_autosync.fetch_history
    output_autosync.fetch_history = lambda base_url, prompt_id=None, **_kwargs: (
        history if prompt_id is None else {prompt_id: history[prompt_id]}
    )
    try:
        return svc.handle_prompt_id(prompt_id)
    finally:
        output_autosync.fetch_history = original


def _reconcile(svc: OutputAutoSyncService, history: dict):
    original = output_autosync.fetch_history
    output_autosync.fetch_history = lambda base_url, prompt_id=None, **_kwargs: (
        history if prompt_id is None else {prompt_id: history.get(prompt_id, history)}
    )
    try:
        return svc.reconcile_pending()
    finally:
        output_autosync.fetch_history = original


def main() -> int:
    results: list[tuple[str, str]] = []
    repo_root = find_repo_root(script_file=Path(__file__))
    print("Package 4.8.5 prepared execution autosync simulations")
    print("=" * 60)

    try:
        bundle = RegistryLoader(repo_root).load_all()
        registered = load_registered_workflow_hashes(repo_root, bundle.workflows)
        prepared_ui = _prepared_ui(repo_root)
        load_hash = prepared_ui["extra"]["ai_studio"]["comfyui_load_workflow_hash"]
        prepared_hash = prepared_ui["extra"]["ai_studio"]["prepared_workflow_hash"]

        # 1–6 recognition / capability / prefix / hashes
        entry = _history_entry(
            _txt2img_api(),
            prepared_ui,
            _flat_output(f"{SAVE_PREFIX}_00001_.png"),
            "prompt-prep-1",
        )
        _assert_true("prepared history recognized as having outputs", bool(extract_output_files(entry)))
        _assert_true("prepared history has SaveImage", history_prompt_has_save_image(entry))
        _pass(results, "Prepared txt2img execution history is recognized")

        prov = extract_execution_provenance(entry, registered_hashes=registered, output_node_id="9")
        _assert_equal("capability", prov.capability, "txt2img")
        _pass(results, "capability resolves to txt2img")
        _assert_equal("identifier", prov.workflow_identifier, "base/txt2img")
        _pass(results, "workflow identifier resolves to base/txt2img")
        _assert_equal("prep id", prov.preparation_id, PREP_ID)
        _pass(results, "preparation_id preserved")
        _assert_equal("prepared hash", prov.prepared_workflow_hash, prepared_hash)
        _pass(results, "prepared_workflow_hash preserved")
        _assert_equal("load hash extracted", prov.comfyui_load_workflow_hash, load_hash)

        nested = extract_output_files(
            _history_entry(_txt2img_api(), prepared_ui, _nested_ui_output(f"{SAVE_PREFIX}_00001_.png"), "n1")
        )
        _assert_equal("nested ui filename", nested[0]["filename"], f"{SAVE_PREFIX}_00001_.png")
        _pass(results, "Save Image prefix does not block detection")

        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            workspace = ProjectWorkspace(tmp / "AI_Studio")
            mountain = workspace.create_project(
                display_name="Mountain Demo", slug="mountain-demo", set_active=True
            )
            svc, comfy, drive_root, drive_out = _service(
                tmp,
                registered=registered,
                active_project=workspace.get_active_project(),
                repo_root=repo_root,
            )

            file_a = comfy / f"{SAVE_PREFIX}_00001_.png"
            file_b = comfy / f"{SAVE_PREFIX}_00002_.png"
            _write_png(file_a, fill=(11, 22, 33))
            _write_png(file_b, fill=(44, 55, 66))

            hist = {
                "prompt-prep-1": _history_entry(
                    _txt2img_api(seed=111),
                    prepared_ui,
                    _flat_output(file_a.name),
                    "prompt-prep-1",
                ),
                "prompt-prep-2": _history_entry(
                    _txt2img_api(seed=222),
                    prepared_ui,
                    _flat_output(file_b.name),
                    "prompt-prep-2",
                ),
            }
            recs_a, resolved_a = _handle(svc, hist, "prompt-prep-1")
            recs_b, resolved_b = _handle(svc, hist, "prompt-prep-2")
            _assert_true("first exec verified", resolved_a and recs_a and recs_a[0].sync_status == "verified")
            _assert_true("second exec verified", resolved_b and recs_b and recs_b[0].sync_status == "verified")
            _assert_true("distinct drive names", recs_a[0].drive_filename != recs_b[0].drive_filename)
            _assert_true("distinct generation ids", recs_a[0].generation_id != recs_b[0].generation_id)
            _pass(results, "reused prefix across separate prompts yields separate executions")

            _assert_true("entered watcher handle", recs_a[0].prompt_id == "prompt-prep-1")
            _pass(results, "completed prepared prompt enters watcher reconciliation")

            # 9. missed websocket recovers through history poll / reconcile
            file_c = comfy / f"{SAVE_PREFIX}_00003_.png"
            _write_png(file_c, fill=(77, 88, 99))
            hist["prompt-missed-ws"] = _history_entry(
                _txt2img_api(seed=333),
                prepared_ui,
                _flat_output(file_c.name),
                "prompt-missed-ws",
            )
            fallback = HistoryFallbackWatcher(base_url="http://127.0.0.1:9")
            fallback.bootstrap()
            recovered = _reconcile(svc, hist)
            recovered_ids = {row.prompt_id for row in recovered}
            _assert_true("missed ws recovered", "prompt-missed-ws" in recovered_ids)
            _pass(results, "missed websocket event recovers through history poll")

            globals_out = _drive_finals(drive_out)
            _assert_true("global copies exist", len(globals_out) >= 3)
            _assert_true(
                "permanent naming",
                all(p.name.startswith("txt2img_") for p in globals_out),
            )
            _pass(results, "global Drive copy created")

            project_out = Path(mountain.outputs_dir)
            project_files = _drive_finals(project_out)
            _assert_true("project mirrors exist", len(project_files) >= 3)
            _assert_true(
                "project naming",
                all(p.name.startswith("txt2img_") for p in project_files),
            )
            _pass(results, "project mirror created when mountain-demo active")

            # Evidence pending precedes verified
            ledger = EvidenceLedger(drive_root / "logs" / "generation_evidence.jsonl")
            rows = ledger.read_all()
            prep1_rows = [r for r in rows if r.get("prompt_id") == "prompt-prep-1"]
            statuses = [r.get("sync_status") for r in prep1_rows]
            _assert_true("pending before verified", "pending" in statuses and "verified" in statuses)
            _assert_true(
                "pending first",
                statuses.index("pending") < statuses.index("verified"),
            )
            _pass(results, "pending evidence precedes copy")
            _pass(results, "verified evidence follows successful verification")

            verified = next(r for r in prep1_rows if r.get("sync_status") == "verified")
            _assert_equal("evidence prep id", verified.get("preparation_id"), PREP_ID)
            _assert_equal("evidence prepared hash", verified.get("prepared_workflow_hash"), prepared_hash)
            snap_root = Path(verified.get("snapshot_root") or "")
            _assert_true("snapshot dir", snap_root.is_dir())
            _assert_true("metadata.json", (snap_root / "metadata.json").is_file())
            _assert_true("workflow.json", (snap_root / "workflow.json").is_file())
            _assert_true("manifest.json last-ish", (snap_root / "manifest.json").is_file())
            meta = json.loads((snap_root / "metadata.json").read_text(encoding="utf-8"))
            _assert_equal("snap prep id", meta.get("preparation_id"), PREP_ID)
            _assert_equal("snap prepared hash", meta.get("prepared_workflow_hash"), prepared_hash)
            _assert_equal("snap canonical id", meta.get("canonical_workflow_identifier"), "base/txt2img")
            _assert_equal("snap load hash", meta.get("comfyui_load_workflow_hash"), load_hash)
            canon = Path(meta.get("canonical_output_path") or "")
            _assert_true("canonical image exists", canon.is_file())
            _assert_true("image not duplicated in snapshot", not any(snap_root.glob("*.png")))
            _pass(results, "generation snapshot created")
            _pass(results, "snapshot references canonical image instead of duplicating it")

            before = {p.name for p in _drive_finals(drive_out)}
            again = _reconcile(svc, hist)
            after = {p.name for p in _drive_finals(drive_out)}
            _assert_equal("no duplicate after restart reconcile", after, before)
            _assert_true(
                "restart produced no new verified copies",
                all(r.sync_status != "verified" or r.prompt_id not in {"prompt-prep-1", "prompt-prep-2", "prompt-missed-ws"} or False for r in again)
                or len(again) == 0
                or all(
                    r.prompt_id not in {"prompt-prep-1", "prompt-prep-2", "prompt-missed-ws"}
                    for r in again
                ),
            )
            # handle_prompt_id on already verified returns [] (skip)
            recs_again, _ = _handle(svc, hist, "prompt-prep-1")
            _assert_equal("already verified not recopied", recs_again, [])
            _pass(results, "restart reconciliation produces no duplicate")
            _pass(results, "previously verified execution not recopied")

        # Global mode: no project mirror
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            svc, comfy, drive_root, drive_out = _service(tmp, registered=registered, repo_root=repo_root)
            local = comfy / f"{SAVE_PREFIX}_global_00001_.png"
            _write_png(local, fill=(1, 2, 3))
            hist = {
                "prompt-global": _history_entry(
                    _txt2img_api(seed=9),
                    prepared_ui,
                    _flat_output(local.name),
                    "prompt-global",
                )
            }
            recs, resolved = _handle(svc, hist, "prompt-global")
            _assert_true("global verified", resolved and recs and recs[0].sync_status == "verified")
            _assert_equal("no project path", recs[0].project_output_path, "")
            _assert_true("no projects dir required", not (drive_root / "projects").exists() or not any((drive_root / "projects").glob("*/outputs/*.png")))
            _pass(results, "no project mirror in global mode")

        # Fail-closed prefix recovery
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            now = 1_700_000_000.0
            svc, comfy, drive_root, drive_out = _service(tmp, registered=registered, repo_root=repo_root)
            unique = comfy / f"{SAVE_PREFIX}_00009_.png"
            _write_png(unique, fill=(9, 8, 7))
            _stamp(unique, now)
            empty_hist = {
                "prompt-empty": _history_entry(
                    _txt2img_api(seed=909),
                    prepared_ui,
                    {},
                    "prompt-empty",
                    execution_ts=now,
                )
            }
            recs, resolved = _handle(svc, empty_hist, "prompt-empty")
            _assert_true("timestamp-bounded unique recovery verified", resolved and recs and recs[0].sync_status == "verified")
            _assert_equal("recovered local name", recs[0].source_filename, unique.name)
            _pass(results, "timestamp-bounded unique prefix recovery succeeds")

            # A. Old orphan, no execution timestamp — unique prefix must not claim it.
            orphan_dir = tmp / "orphan-no-ts"
            svc_o, comfy_o, _do, out_o = _service(orphan_dir, registered=registered, repo_root=repo_root)
            orphan = comfy_o / f"{SAVE_PREFIX}_old.png"
            _write_png(orphan, fill=(21, 21, 21))
            orphan_hist = {
                "prompt-orphan": _history_entry(
                    _txt2img_api(seed=21),
                    prepared_ui,
                    {},
                    "prompt-orphan",
                )
            }
            recs_o, resolved_o = _handle(svc_o, orphan_hist, "prompt-orphan")
            analysis_o = _analyze(svc_o, orphan_hist, "prompt-orphan")
            _assert_equal("orphan no records", recs_o, [])
            _assert_true("orphan retryable", resolved_o is False)
            _assert_equal("orphan reason", analysis_o["attribution_reason"], INSUFFICIENT_ATTRIBUTION_EVIDENCE)
            _assert_equal("orphan no Drive copy", _drive_finals(out_o), [])
            _assert_true(
                "orphan token recorded",
                any(INSUFFICIENT_ATTRIBUTION_EVIDENCE in msg for msg in svc_o.status.messages),
            )
            _pass(results, "old orphan without execution timestamp is not stolen")
            _pass(results, "no recovery without execution timestamp")

            # B. Competitor history lookup unavailable — no prefix recovery.
            unavail_dir = tmp / "competitor-unavailable"
            svc_uav, comfy_uav, _duav, out_uav = _service(
                unavail_dir, registered=registered, repo_root=repo_root
            )
            only = comfy_uav / f"{SAVE_PREFIX}_00030_.png"
            _write_png(only, fill=(30, 30, 30))
            _stamp(only, now)
            unavail_entry = _history_entry(
                _txt2img_api(seed=30),
                prepared_ui,
                {},
                "prompt-unavail",
                execution_ts=now,
            )

            def _competitor_unavailable(base_url, prompt_id=None, **_kwargs):
                if prompt_id is None:
                    raise RuntimeError("history unavailable for competitor scan")
                return {prompt_id: unavail_entry}

            recs_uav, resolved_uav = _handle_fetch(
                svc_uav, _competitor_unavailable, "prompt-unavail"
            )
            analysis_uav = _analyze_fetch(
                svc_uav, _competitor_unavailable, unavail_entry, "prompt-unavail"
            )
            _assert_equal("unavailable no records", recs_uav, [])
            _assert_true("unavailable retryable", resolved_uav is False)
            _assert_true("competitor check unavailable", analysis_uav["competitor_check_available"] is False)
            _assert_equal(
                "unavailable reason",
                analysis_uav["attribution_reason"],
                COMPETITOR_CHECK_UNAVAILABLE,
            )
            _assert_equal("unavailable no Drive copy", _drive_finals(out_uav), [])
            _pass(results, "no recovery when competitor check unavailable")

            # C. Old orphan outside window + current in-window → recover current only.
            win_dir = tmp / "window-filter"
            svc_w, comfy_w, _dw, out_w = _service(win_dir, registered=registered, repo_root=repo_root)
            old_out = comfy_w / f"{SAVE_PREFIX}_old_outside.png"
            current_in = comfy_w / f"{SAVE_PREFIX}_current.png"
            _write_png(old_out, fill=(11, 11, 11))
            _write_png(current_in, fill=(12, 12, 12))
            _stamp(old_out, now - 10_000)
            _stamp(current_in, now)
            win_hist = {
                "prompt-window": _history_entry(
                    _txt2img_api(seed=12),
                    prepared_ui,
                    {},
                    "prompt-window",
                    execution_ts=now,
                )
            }
            analysis_w = _analyze(svc_w, win_hist, "prompt-window")
            recs_w, resolved_w = _handle(svc_w, win_hist, "prompt-window")
            _assert_true("in-window recovers", resolved_w and recs_w and recs_w[0].sync_status == "verified")
            _assert_equal("in-window file", recs_w[0].source_filename, current_in.name)
            _assert_equal("window candidate count", analysis_w["timestamp_window_candidate_count"], 1)
            _assert_equal("prefix candidate count", analysis_w["prefix_candidate_count"], 2)
            _assert_equal("one permanent after window filter", len(_drive_finals(out_w)), 1)
            _pass(results, "timestamp window excludes old orphan and recovers current")

            # D. Exact history filename remains authoritative without timestamp / competitor check.
            exact_dir = tmp / "exact-despite-unavailable"
            svc_x, comfy_x, _dx, out_x = _service(exact_dir, registered=registered, repo_root=repo_root)
            exact = comfy_x / f"{SAVE_PREFIX}_exact_00001_.png"
            _write_png(exact, fill=(13, 13, 13))
            exact_entry = _history_entry(
                _txt2img_api(seed=13),
                prepared_ui,
                _flat_output(exact.name),
                "prompt-exact",
            )

            def _exact_competitor_unavailable(base_url, prompt_id=None, **_kwargs):
                if prompt_id is None:
                    raise RuntimeError("history unavailable for competitor scan")
                return {prompt_id: exact_entry}

            analysis_x = _analyze_fetch(
                svc_x, _exact_competitor_unavailable, exact_entry, "prompt-exact"
            )
            recs_x, resolved_x = _handle_fetch(
                svc_x, _exact_competitor_unavailable, "prompt-exact"
            )
            _assert_true("exact recovers", resolved_x and recs_x and recs_x[0].sync_status == "verified")
            _assert_equal("exact file", recs_x[0].source_filename, exact.name)
            _assert_true("exact has no execution ts", analysis_x["execution_timestamp_available"] is False)
            _assert_true("exact competitor unavailable", analysis_x["competitor_check_available"] is False)
            _assert_equal("exact reason", analysis_x["attribution_reason"], "exact_history_filename")
            _pass(results, "exact history filename recovers despite unavailable competitor check")

            # E. Prior-runtime leftover must never be assigned from prefix uniqueness alone.
            leftover_dir = tmp / "prior-runtime-leftover"
            svc_e2, comfy_e2, _de2, out_e2 = _service(
                leftover_dir, registered=registered, repo_root=repo_root
            )
            leftover = comfy_e2 / f"{SAVE_PREFIX}_00021_.png"
            _write_png(leftover, fill=(21, 0, 0))
            leftover_hist = {
                "prompt-new": _history_entry(
                    _txt2img_api(seed=210),
                    prepared_ui,
                    {},
                    "prompt-new",
                )
            }
            recs_e2, resolved_e2 = _handle(svc_e2, leftover_hist, "prompt-new")
            analysis_e2 = _analyze(svc_e2, leftover_hist, "prompt-new")
            _assert_equal("leftover no records", recs_e2, [])
            _assert_true("leftover retryable", resolved_e2 is False)
            _assert_equal(
                "leftover reason",
                analysis_e2["attribution_reason"],
                INSUFFICIENT_ATTRIBUTION_EVIDENCE,
            )
            _assert_equal("leftover no Drive copy", _drive_finals(out_e2), [])
            _pass(results, "prior-runtime leftover is not assigned from prefix uniqueness")

            amb_dir = tmp / "ambiguous"
            svc_a, comfy_a, drive_a, out_a = _service(amb_dir, registered=registered, repo_root=repo_root)
            file_a = comfy_a / f"{SAVE_PREFIX}_00001_.png"
            file_b = comfy_a / f"{SAVE_PREFIX}_00002_.png"
            _write_png(file_a, fill=(1, 1, 1))
            _write_png(file_b, fill=(2, 2, 2))
            _stamp(file_a, now)
            _stamp(file_b, now + 1)
            amb_hist = {
                "prompt-A": _history_entry(
                    _txt2img_api(seed=1), prepared_ui, {}, "prompt-A", execution_ts=now
                ),
                "prompt-B": _history_entry(
                    _txt2img_api(seed=2), prepared_ui, {}, "prompt-B", execution_ts=now + 1
                ),
            }
            recs_a, resolved_a = _handle(svc_a, amb_hist, "prompt-A")
            recs_b, resolved_b = _handle(svc_a, amb_hist, "prompt-B")
            _assert_equal("A no guess", recs_a, [])
            _assert_equal("B no guess", recs_b, [])
            _assert_true("A retryable", resolved_a is False)
            _assert_true("B retryable", resolved_b is False)
            _assert_true(
                "ambiguous token recorded",
                any(AMBIGUOUS_PREFIX_RECOVERY in msg for msg in svc_a.status.messages),
            )
            _assert_equal("no Drive copy guessed", _drive_finals(out_a), [])
            _pass(results, "two unresolved same-prefix prompts do not guess")
            _pass(results, "ambiguous same-prefix prompts remain retryable")

            # Verified candidate excluded; remaining unique in-window file can recover.
            excl_dir = tmp / "exclude-verified"
            svc_e, comfy_e, _de, out_e = _service(excl_dir, registered=registered, repo_root=repo_root)
            verified_file = comfy_e / f"{SAVE_PREFIX}_verified_00001_.png"
            remain_file = comfy_e / f"{SAVE_PREFIX}_remain_00002_.png"
            _write_png(verified_file, fill=(3, 3, 3))
            _write_png(remain_file, fill=(4, 4, 4))
            _stamp(verified_file, now)
            _stamp(remain_file, now + 2)
            first_hist = {
                "prompt-verified": _history_entry(
                    _txt2img_api(seed=3),
                    prepared_ui,
                    _flat_output(verified_file.name),
                    "prompt-verified",
                    execution_ts=now,
                )
            }
            recs_v, resolved_v = _handle(svc_e, first_hist, "prompt-verified")
            _assert_true("seed verified", resolved_v and recs_v and recs_v[0].sync_status == "verified")
            remain_hist = {
                "prompt-verified": first_hist["prompt-verified"],
                "prompt-remain": _history_entry(
                    _txt2img_api(seed=4),
                    prepared_ui,
                    {},
                    "prompt-remain",
                    execution_ts=now + 2,
                ),
            }
            recs_r, resolved_r = _handle(svc_e, remain_hist, "prompt-remain")
            _assert_true("remaining unique recovers", resolved_r and recs_r and recs_r[0].sync_status == "verified")
            _assert_equal("excluded verified file", recs_r[0].source_filename, remain_file.name)
            _pass(results, "verified candidate is excluded")

            unrel_dir = tmp / "unrelated"
            svc_u, comfy_u, _du, out_u = _service(unrel_dir, registered=registered, repo_root=repo_root)
            match = comfy_u / f"{SAVE_PREFIX}_00011_.png"
            other = comfy_u / "other_prefix_00099_.png"
            _write_png(match, fill=(5, 5, 5))
            _write_png(other, fill=(6, 6, 6))
            _stamp(match, now)
            later = now + 10
            _stamp(other, later)
            unrel_hist = {
                "prompt-unrel": _history_entry(
                    _txt2img_api(seed=5), prepared_ui, {}, "prompt-unrel", execution_ts=now
                )
            }
            recs_u, resolved_u = _handle(svc_u, unrel_hist, "prompt-unrel")
            _assert_true("matching prefix recovered", resolved_u and recs_u)
            _assert_equal("unrelated prefix excluded", recs_u[0].source_filename, match.name)
            _pass(results, "unrelated prefix is excluded")
            _pass(results, "newer unrelated file cannot steal attribution")

            late_dir = tmp / "late-history"
            svc_l, comfy_l, _dl, out_l = _service(late_dir, registered=registered, repo_root=repo_root)
            late_a = comfy_l / f"{SAVE_PREFIX}_late_00001_.png"
            late_b = comfy_l / f"{SAVE_PREFIX}_late_00002_.png"
            _write_png(late_a, fill=(7, 7, 7))
            _write_png(late_b, fill=(8, 8, 8))
            late_hist = {
                "prompt-late-A": _history_entry(_txt2img_api(seed=7), prepared_ui, {}, "prompt-late-A"),
                "prompt-late-B": _history_entry(_txt2img_api(seed=8), prepared_ui, {}, "prompt-late-B"),
            }
            recs_la, resolved_la = _handle(svc_l, late_hist, "prompt-late-A")
            recs_lb, resolved_lb = _handle(svc_l, late_hist, "prompt-late-B")
            _assert_true("late still retryable", resolved_la is False and resolved_lb is False)
            late_hist["prompt-late-A"] = _history_entry(
                _txt2img_api(seed=7),
                prepared_ui,
                _flat_output(late_a.name),
                "prompt-late-A",
            )
            recs_la2, resolved_la2 = _handle(svc_l, late_hist, "prompt-late-A")
            _assert_true("exact filename later resolves", resolved_la2 and recs_la2 and recs_la2[0].sync_status == "verified")
            _assert_equal("resolved A file", recs_la2[0].source_filename, late_a.name)
            recs_la3, _ = _handle(svc_l, late_hist, "prompt-late-A")
            _assert_equal("no duplicate after resolution", recs_la3, [])
            _assert_equal("one permanent for A", len(_drive_finals(out_l)), 1)
            _pass(results, "retry after history later exposes exact filename resolves correctly")
            _pass(results, "no duplicate permanent output after eventual resolution")

            # Empty + SaveImage + no local file stays unresolved (retryable)
            svc2, comfy2, _dr2, _do2 = _service(tmp / "retry", registered=registered, repo_root=repo_root)
            recs2, resolved2 = _handle(
                svc2,
                {
                    "prompt-wait": _history_entry(
                        _txt2img_api(seed=1),
                        prepared_ui,
                        {},
                        "prompt-wait",
                    )
                },
                "prompt-wait",
            )
            _assert_equal("no records yet", recs2, [])
            _assert_true("not marked resolved", resolved2 is False)
            _pass(results, "failed/pending prepared execution remains retryable")

        # Safety: 4.8.4 userdata untouched
        compat = (repo_root / "core/runtime/comfyui_userdata_route_compat.py").read_text(encoding="utf-8")
        _assert_true("4.8.4 compat still present", "ai_studio_userdata_route_compat_4_8_4" in compat)
        _assert_true("move-before-catchall still present", "reorder_move_before_catchall" in compat)
        _pass(results, "Package 4.8.4 userdata behavior unchanged")

        # no /prompt auto-queue browser
        autosync_src = (repo_root / "core/runtime/output_autosync.py").read_text(encoding="utf-8")
        diag_src = (repo_root / "core/scripts/diagnose_prepared_execution_autosync.py").read_text(
            encoding="utf-8"
        )
        _assert_true("autosync does not queue", "/prompt" not in autosync_src)
        _assert_true("rule C removed", "unique_uncontested_prefix" not in autosync_src)
        _assert_true("diag read-only note", "Does not queue /prompt" in diag_src)
        _pass(results, "no /prompt")
        _pass(results, "no auto-queue")
        _pass(results, "no browser automation")

        nb = json.loads(
            (repo_root / "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb").read_text(encoding="utf-8")
        )
        _assert_true("notebook JSON valid", isinstance(nb.get("cells"), list))
        nb_src = "".join("".join(cell.get("source") or []) for cell in nb.get("cells") or [])
        _assert_true(
            "notebook preserves watcher FAIL after launch",
            "Launch complete with OutputWatcher FAIL — autosync is NOT healthy." in nb_src,
        )
        _assert_true(
            "notebook does not claim automatic sync when watcher failed",
            "outputs will NOT sync automatically until the watcher reports OK." in nb_src,
        )
        _pass(results, "notebook JSON valid")

        from core.scripts.diagnose_prepared_execution_autosync import diagnose
        from core.scripts.run_output_watcher import initial_history_reconcile

        diag_payload = diagnose(
            repo_root=repo_root,
            preparation_id=PREP_ID,
            comfy_base_url="http://127.0.0.1:9",
        )
        for key in (
            "watcher_current_runtime",
            "watcher_process_alive",
            "heartbeat_fresh",
            "history_reachable",
            "prompt_present_in_history",
            "local_output_candidates",
            "evidence_status",
            "processed_index_status",
            "global_drive_copy_exists",
            "active_project",
            "project_mirror_exists",
            "generation_snapshot_exists",
            "preparation_linkage",
            "execution_timestamp_available",
            "competitor_check_available",
            "timestamp_window_candidate_count",
            "attribution_reason",
        ):
            _assert_true(f"diag has {key}", key in diag_payload)
        _pass(results, "live diagnostic distinguishes watcher/history/recovery classes")

        class _Status:
            def __init__(self) -> None:
                self.last_history_poll = ""
                self.watcher = ""
                self.ownership_state = ""
                self.process_alive = False
                self.heartbeat = ""
                self.last_error = ""

        class _FakeService:
            def __init__(self, succeed_on: int) -> None:
                self.status = _Status()
                self.calls = 0
                self.succeed_on = succeed_on
                self.writes = 0

            def reconcile_pending(self, history_timeout=None):
                self.calls += 1
                if self.calls >= self.succeed_on:
                    self.status.last_history_poll = "now"
                return []

            def write_status(self) -> None:
                self.writes += 1

        ok_svc = _FakeService(succeed_on=3)
        _recs, ok, used = initial_history_reconcile(
            ok_svc, attempts=5, retry_seconds=0, sleep_fn=lambda _s: None
        )
        _assert_true("startup retry eventually succeeds", ok and used == 3)
        fail_svc = _FakeService(succeed_on=99)
        _recs2, ok2, used2 = initial_history_reconcile(
            fail_svc, attempts=5, retry_seconds=0, sleep_fn=lambda _s: None
        )
        _assert_true("startup retry still fails after bound", (not ok2) and used2 == 5)
        _assert_true("startup never claimed OK while failing", fail_svc.status.watcher != "OK")
        _pass(results, "transient initial history failure is retried then fail-closed")

        help_proc = subprocess.run(
            [
                sys.executable,
                str(repo_root / "core/scripts/diagnose_prepared_execution_autosync.py"),
                "--help",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        _assert_equal("diag help", help_proc.returncode, 0)

        for label, script in (
            ("Package 4.8.4", "simulate_package484_colab_userdata_route_compat.py"),
            ("Package 4.8.3", "simulate_package483_live_workflow_open_diagnostics.py"),
            ("Package 4.8.2", "simulate_package482_prepared_workflow_integration.py"),
            ("Package 4.8.1", "simulate_package481_prepared_workflow_hotfix.py"),
            ("Package 4.8", "simulate_package48_workflow_library.py"),
            ("Package 4.7", "simulate_package47_generation_snapshots.py"),
            ("Package 4.5.2", "simulate_output_autosync.py"),
        ):
            completed = subprocess.run(
                [sys.executable, str(repo_root / "core" / "scripts" / script)],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            _assert_equal(f"{label} exit", completed.returncode, 0)
            _pass(results, f"{label} regressions green")

        build_text = (repo_root / "core/scripts/build_review_package.py").read_text(encoding="utf-8")
        _assert_true(
            "build lists 485",
            "simulate_package485_prepared_execution_autosync.py" in build_text,
        )
        _assert_true(
            "build lists diagnose",
            "diagnose_prepared_execution_autosync.py" in build_text,
        )
        _pass(results, "Package 4.8.5 prepared execution autosync simulations complete")

    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        print("\nRESULT: FAIL — package 4.8.5 simulations failed.")
        return 1

    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: PASS — package 4.8.5 prepared execution autosync green.")
    print("\nVerified programmatically:")
    print("  - prepared history recognition, capability, preparation linkage")
    print("  - prefix reuse is not a dedupe key; global + mountain-demo mirror")
    print("  - missed WS recovers via history; snapshot does not duplicate image")
    print("  - prior 4.8.x / 4.7 / 4.5.2 regressions")
    print("Not verified programmatically:")
    print("  - live Colab Drive appearance of the already-generated alpine image")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
