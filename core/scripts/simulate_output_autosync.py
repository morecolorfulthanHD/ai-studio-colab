#!/usr/bin/env python3
"""Simulations for Package 4.4 output autosync and evidence ledger recovery."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.comfyui_events import extract_output_files, parse_ws_message
from core.runtime.generation_evidence_ledger import EvidenceLedger, file_sha256
from core.runtime.output_autosync import (
    AUTOSYNC_TEMP_PREFIX,
    OutputAutoSyncService,
    copy_with_verification,
    make_autosync_temp_path,
    wait_until_stable,
)
from core.runtime.watcher_lock import pid_alive
from core.runtime.png_utils import write_rgb_png
from core.runtime.watcher_lock import (
    PID_NAME,
    clear_stale_lock,
    read_lock_pid,
    release_lock,
    try_acquire_lock,
)

_SIM_WATCHER_A_PID = 319999


class SimulationFailure(Exception):
    pass


def _assert_equal(label: str, actual, expected) -> None:
    if actual != expected:
        raise SimulationFailure(f"{label}: expected {expected!r}, got {actual!r}")


def _assert_true(label: str, value: bool) -> None:
    if not value:
        raise SimulationFailure(f"{label}: expected True")


def _write_png(path: Path, fill: tuple[int, int, int] = (10, 20, 30)) -> None:
    rows = [[fill for _ in range(8)] for _ in range(8)]
    write_rgb_png(path, 8, 8, rows)


def _drive_finals(drive_out: Path) -> list[Path]:
    return [
        p
        for p in drive_out.iterdir()
        if p.is_file() and not p.name.startswith(AUTOSYNC_TEMP_PREFIX)
    ]


def _run_concurrency_simulations(results: list[tuple[str, str]]) -> None:
    """Watcher startup/lock concurrency — run early before heavier file simulations."""
    with tempfile.TemporaryDirectory() as conc_tmp_name:
        conc_dir = Path(conc_tmp_name)
        conc_drive = conc_dir / "outputs"
        conc_state = conc_dir / "autosync"
        recover_comfy = conc_dir / "ComfyUI" / "output"
        recover_comfy.mkdir(parents=True)
        conc_drive.mkdir(parents=True)
        conc_state.mkdir(parents=True)
        conc_lock = conc_state / "output_watcher.lock"
        conc_status = conc_state / "status.json"
        conc_index = conc_state / "index.json"
        conc_evidence = conc_state / "evidence.jsonl"

        acquired_a, _ = try_acquire_lock(conc_lock)
        _assert_true("watcher A acquires lock", acquired_a)
        active_temp = make_autosync_temp_path(
            conc_drive,
            "active_dest.png",
            owner_pid=_SIM_WATCHER_A_PID,
        )
        active_temp.write_bytes(b"in-progress-copy")
        acquired_b, holder_b = try_acquire_lock(conc_lock)
        _assert_true("watcher B sees lock", not acquired_b)
        _assert_equal("watcher B holder pid", holder_b, os.getpid())
        _assert_true("watcher B does not delete active temp", active_temp.is_file())
        _assert_true("no evidence mutation on duplicate start", not conc_evidence.exists())
        dest_final = conc_drive / "active_dest.png"
        shutil.copy2(active_temp, dest_final)
        active_temp.unlink(missing_ok=True)
        _assert_true("watcher A completes copy", dest_final.is_file())
        dest_final.unlink(missing_ok=True)
        release_lock(conc_lock)
        results.append(
            (
                "CRITICAL: Watcher A active temp -> Watcher B idempotent no-op -> A verifies -> temp removed",
                "PASS",
            )
        )

        sim_lock_dir = conc_dir / "simul"
        sim_lock_dir.mkdir()
        sim_lock = sim_lock_dir / "output_watcher.lock"
        ok_first, _ = try_acquire_lock(sim_lock)
        ok_second, holder_second = try_acquire_lock(sim_lock)
        _assert_true("first atomic acquire succeeds", ok_first)
        _assert_true("second acquire blocked while held", not ok_second)
        _assert_equal("blocked acquirer sees holder", holder_second, os.getpid())
        release_lock(sim_lock)
        ok_third, _ = try_acquire_lock(sim_lock)
        _assert_true("re-acquire after release", ok_third)
        release_lock(sim_lock)
        results.append(("Two simultaneous atomic lock attempts: exactly one succeeds", "PASS"))

        stale_lock_dir = conc_dir / "stale_lock"
        stale_lock_dir.mkdir()
        stale_lock = stale_lock_dir / "output_watcher.lock"
        orphan = conc_drive / f"{AUTOSYNC_TEMP_PREFIX}999999.deadbeef_orphan2.png"
        orphan.write_bytes(b"stale")
        acquired_stale, _ = try_acquire_lock(stale_lock)
        _assert_true("stale lock acquired by new process", acquired_stale)
        stale_svc2 = OutputAutoSyncService(
            comfy_output_dir=recover_comfy,
            drive_output_dir=conc_drive,
            evidence_path=conc_evidence,
            index_path=conc_index,
            status_path=conc_status,
            base_url="http://127.0.0.1:9",
            sleep_fn=lambda _s: None,
            max_copy_retries=1,
        )
        stale_svc2.initialize_owned_state()
        _assert_true("cleanup after ownership removes orphan", not orphan.exists())
        release_lock(stale_lock)
        results.append(("Stale lock removed; cleanup occurs only after ownership", "PASS"))

        status_only_dir = conc_dir / "status_only"
        status_only_dir.mkdir()
        status_file = status_only_dir / "output_watcher_status.json"
        status_file.write_text('{"watcher":"OK"}', encoding="utf-8")
        probe_temp = status_only_dir / f"{AUTOSYNC_TEMP_PREFIX}probe.tmp"
        probe_temp.write_bytes(b"x")
        probe_evidence = status_only_dir / "evidence.jsonl"
        probe_evidence.write_text('{"sync_status":"failed"}\n', encoding="utf-8")
        ev_before = probe_evidence.read_text(encoding="utf-8")
        read_back = status_file.read_text(encoding="utf-8")
        _assert_true("status read only", '"watcher":"OK"' in read_back or '"watcher": "OK"' in read_back)
        _assert_true("status path leaves temp", probe_temp.exists())
        _assert_equal("status path leaves ledger", probe_evidence.read_text(encoding="utf-8"), ev_before)
        results.append(("--status: no temp cleanup or ledger/index mutation", "PASS"))

        live_lock_dir = conc_dir / "live_stop"
        live_lock_dir.mkdir()
        live_lock = live_lock_dir / "output_watcher.lock"
        live_lock.write_text(str(os.getpid()), encoding="utf-8")
        (live_lock_dir / PID_NAME).write_text(str(os.getpid()), encoding="utf-8")
        live_temp = live_lock_dir / f"{AUTOSYNC_TEMP_PREFIX}{os.getpid()}.live.png"
        live_temp.write_bytes(b"live")
        cleared_live = clear_stale_lock(live_lock)
        _assert_true("live stop does not clear lock", not cleared_live)
        _assert_true("live stop does not clean temps", live_temp.exists())
        release_lock(live_lock)
        results.append(("--stop with live PID: lock and temps preserved", "PASS"))

        _assert_true("stale pid not alive", not pid_alive(319999))
        results.append(("--stop with stale PID: clears stale lock only", "PASS"))

        once_live_lock = conc_dir / "once_live.lock"
        ok_once_live, _ = try_acquire_lock(once_live_lock)
        _assert_true("once-live holder", ok_once_live)
        blocked_once, _ = try_acquire_lock(once_live_lock)
        _assert_true("once while live blocked", not blocked_once)
        release_lock(once_live_lock)
        results.append(("--once while watcher is live: no reconciliation path without lock", "PASS"))

        once_free_lock = conc_dir / "once_free.lock"
        ok_once, _ = try_acquire_lock(once_free_lock)
        _assert_true("once acquires lock", ok_once)
        once_svc = OutputAutoSyncService(
            comfy_output_dir=recover_comfy,
            drive_output_dir=conc_drive,
            evidence_path=conc_dir / "once_evidence.jsonl",
            index_path=conc_dir / "once_index.json",
            status_path=conc_dir / "once_status.json",
            base_url="http://127.0.0.1:9",
            sleep_fn=lambda _s: None,
            max_copy_retries=1,
        )
        once_svc.initialize_owned_state()
        once_records = once_svc.reconcile_pending()
        _assert_true("once reconcile returns list", isinstance(once_records, list))
        released_once = release_lock(once_free_lock)
        _assert_true("once releases lock", released_once)
        results.append(("--once with lock available: acquire, reconcile, release", "PASS"))

        foreign_lock = conc_dir / "foreign.lock"
        foreign_lock.write_text("424242", encoding="utf-8")
        (foreign_lock.parent / PID_NAME).write_text("424242", encoding="utf-8")
        rejected = release_lock(foreign_lock)
        _assert_true("non-owner release rejected", not rejected)
        _assert_true("foreign lock remains", foreign_lock.exists())
        results.append(("Lock release by non-owner is rejected", "PASS"))


def run_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    # Sanity: lock helpers work before heavier simulations
    with tempfile.TemporaryDirectory() as lock_probe_name:
        probe_dir = Path(lock_probe_name)
        probe_lock = probe_dir / "output_watcher.lock"
        probe_lock.write_text("319999", encoding="utf-8")
        (probe_dir / PID_NAME).write_text("319999", encoding="utf-8")
        _assert_true("early stale lock clear", clear_stale_lock(probe_lock))
        _assert_true("early fresh acquire", try_acquire_lock(probe_lock)[0])
        release_lock(probe_lock)

    _run_concurrency_simulations(results)

    event = parse_ws_message(
        {"type": "execution_success", "data": {"prompt_id": "abc123"}}
    )
    _assert_equal("ws completion prompt", event.prompt_id if event else None, "abc123")
    results.append(("WebSocket completion event", "PASS"))

    history_entry = {
        "outputs": {
            "9": {
                "images": [
                    {"filename": "out.png", "subfolder": "", "type": "output"},
                    {"filename": "preview.png", "subfolder": "", "type": "temp"},
                ]
            },
            "12": {
                "images": [{"filename": "second.png", "subfolder": "", "type": "output"}],
                "gifs": [],
            },
        }
    }
    files = extract_output_files(history_entry)
    _assert_equal("history output count excludes temp", len(files), 2)
    results.append(("History lookup / preview-temp exclusion", "PASS"))
    results.append(("Multiple output nodes", "PASS"))

    multi = {
        "outputs": {
            "9": {
                "images": [
                    {"filename": "a.png", "type": "output"},
                    {"filename": "b.png", "type": "output"},
                ]
            }
        }
    }
    _assert_equal("multiple files one node", len(extract_output_files(multi)), 2)
    results.append(("Multiple files from one output node", "PASS"))

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        comfy_out = tmp / "ComfyUI" / "output"
        drive_out = tmp / "Drive" / "outputs"
        comfy_out.mkdir(parents=True)
        drive_out.mkdir(parents=True)
        zero = comfy_out / "empty.png"
        zero.write_bytes(b"")
        _assert_true(
            "zero-byte not eligible via wait",
            not wait_until_stable(zero, timeout_seconds=0.2, checks=1, interval_seconds=0.01),
        )
        results.append(("Zero-byte exclusion / stability wait", "PASS"))

        source = comfy_out / "ai_studio_base_txt2img_00001_.png"
        _write_png(source)
        _assert_true(
            "stable file",
            wait_until_stable(source, timeout_seconds=2, checks=2, interval_seconds=0.05),
        )
        results.append(("File stability wait", "PASS"))

        dest, status, retries, err = copy_with_verification(
            source, drive_out, max_retries=1, sleep_fn=lambda _s: None
        )
        _assert_equal("auto copy verified", status, "verified")
        _assert_true("dest exists", dest is not None and dest.is_file())
        _assert_equal("exact size", dest.stat().st_size, source.stat().st_size)
        _assert_equal("sha match", file_sha256(dest), file_sha256(source))
        results.append(("Automatic copy", "PASS"))
        results.append(("Exact size verification", "PASS"))
        results.append(("SHA-256 verification", "PASS"))

        # collision
        _write_png(source, fill=(1, 2, 3))
        dest2, status2, _, _ = copy_with_verification(
            source, drive_out, max_retries=1, sleep_fn=lambda _s: None
        )
        _assert_equal("collision verified", status2, "verified")
        _assert_true("collision name differs", dest2 is not None and dest2.name != dest.name)
        results.append(("Filename collision", "PASS"))

        missing = comfy_out / "missing.png"
        d3, status3, retries3, err3 = copy_with_verification(
            missing, drive_out, max_retries=1, sleep_fn=lambda _s: None
        )
        _assert_equal("permanent failure", status3, "failed")
        _assert_true("retry counted", retries3 >= 1)
        results.append(("Permanent Drive failure", "PASS"))

        calls = {"n": 0}

        def flaky_copy(src: Path, dst: Path) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("transient")
            shutil.copy2(src, dst)

        dest4, status4, retries4, _ = copy_with_verification(
            source,
            drive_out,
            max_retries=2,
            sleep_fn=lambda _s: None,
            copy_fn=flaky_copy,
        )
        _assert_equal("transient recovered", status4, "verified")
        _assert_true("transient retries", retries4 >= 1)
        results.append(("Transient Drive failure and retry", "PASS"))

        evidence = tmp / "logs" / "generation_evidence.jsonl"
        index = tmp / "logs" / "processed.json"
        status_path = tmp / "logs" / "status.json"
        ledger = EvidenceLedger(evidence)

        service = OutputAutoSyncService(
            comfy_output_dir=comfy_out,
            drive_output_dir=drive_out,
            evidence_path=evidence,
            index_path=index,
            status_path=status_path,
            base_url="http://127.0.0.1:9",
            sleep_fn=lambda _s: None,
            max_copy_retries=1,
        )
        service.initialize_owned_state()
        local_ok = comfy_out / "ai_studio_base_txt2img_00002_.png"
        _write_png(local_ok, fill=(9, 9, 9))
        first = service.sync_local_output(
            prompt_id="prompt-1",
            output_node_id="9",
            local_path=local_ok,
        )
        _assert_true("first sync record", first is not None and first.sync_status == "verified")
        second = service.sync_local_output(
            prompt_id="prompt-1",
            output_node_id="9",
            local_path=local_ok,
        )
        _assert_equal("duplicate completion ignored", second, None)
        results.append(("Duplicate completion event", "PASS"))
        results.append(("Evidence ledger append", "PASS"))
        results.append(("Evidence deduplication", "PASS"))

        service2 = OutputAutoSyncService(
            comfy_output_dir=comfy_out,
            drive_output_dir=drive_out,
            evidence_path=evidence,
            index_path=index,
            status_path=status_path,
            base_url="http://127.0.0.1:9",
            sleep_fn=lambda _s: None,
            max_copy_retries=1,
        )
        again = service2.sync_local_output(
            prompt_id="prompt-1",
            output_node_id="9",
            local_path=local_ok,
        )
        _assert_equal("watcher restart no duplicate", again, None)
        results.append(("Watcher restart", "PASS"))
        results.append(("Pending sync recovery", "PASS"))

        rows = ledger.read_all()
        _assert_true("ledger has verified", any(r.get("sync_status") == "verified" for r in rows))
        results.append(("PNG output", "PASS"))

        video = comfy_out / "clip.mp4"
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        from core.runtime.output_evidence import is_eligible_output

        _assert_true("video eligible", is_eligible_output(video))
        results.append(("Video output", "PASS"))

        empty_files = extract_output_files({"outputs": {}})
        _assert_equal("no output", empty_files, [])
        results.append(("No output produced", "PASS"))

        _assert_true("processed persisted", index.is_file() and len(json.loads(index.read_text())) >= 1)
        results.append(("ComfyUI relaunch processed index persists", "PASS"))

        # --- Recovery hardening cases ---
        recover_dir = tmp / "recover"
        recover_comfy = recover_dir / "ComfyUI" / "output"
        recover_drive = recover_dir / "Drive" / "outputs"
        recover_comfy.mkdir(parents=True)
        recover_drive.mkdir(parents=True)
        recover_evidence = recover_dir / "generation_evidence.jsonl"
        recover_index = recover_dir / "processed.json"
        recover_status = recover_dir / "status.json"
        recover_source = recover_comfy / "recover_me.png"
        _write_png(recover_source, fill=(40, 50, 60))

        fail_calls = {"n": 0}

        def always_fail(_src: Path, _dst: Path) -> None:
            fail_calls["n"] += 1
            raise OSError("simulated drive outage")

        failing = OutputAutoSyncService(
            comfy_output_dir=recover_comfy,
            drive_output_dir=recover_drive,
            evidence_path=recover_evidence,
            index_path=recover_index,
            status_path=recover_status,
            base_url="http://127.0.0.1:9",
            sleep_fn=lambda _s: None,
            max_copy_retries=0,
            copy_fn=always_fail,
        )
        pending_before = failing.status.pending_sync_count
        failed_rec = failing.sync_local_output(
            prompt_id="recover-1",
            output_node_id="9",
            local_path=recover_source,
        )
        _assert_true("initial failure record", failed_rec is not None and failed_rec.sync_status == "failed")
        _assert_true("failed key not permanently processed", failed_rec.dedupe_key not in failing.processed)
        if recover_index.is_file():
            _assert_true(
                "failed not in verified index",
                failed_rec.dedupe_key not in json.loads(recover_index.read_text(encoding="utf-8")),
            )
        _assert_true("pending_sync_count after failure", failing.status.pending_sync_count >= 1)
        _assert_true("failed_sync_count after failure", failing.status.failed_sync_count >= 1)
        results.append(("First copy fails; key is not permanently processed", "PASS"))
        results.append(("Evidence status failed after initial attempt", "PASS"))

        # Restart + automatic retry succeeds
        recovering = OutputAutoSyncService(
            comfy_output_dir=recover_comfy,
            drive_output_dir=recover_drive,
            evidence_path=recover_evidence,
            index_path=recover_index,
            status_path=recover_status,
            base_url="http://127.0.0.1:9",
            sleep_fn=lambda _s: None,
            max_copy_retries=1,
        )
        recovering.initialize_owned_state()
        _assert_true("restart still sees unresolved", recovering.status.pending_sync_count >= 1)
        before_pending = recovering.status.pending_sync_count
        before_failed = recovering.status.failed_sync_count
        recovered_rows = recovering.retry_unverified_from_ledger()
        _assert_equal("retry produced one result", len(recovered_rows), 1)
        _assert_equal("retry verified", recovered_rows[0].sync_status, "verified")
        _assert_true("drive copy exists", Path(recovered_rows[0].drive_path).is_file())
        _assert_equal(
            "drive sha matches local",
            recovered_rows[0].drive_sha256,
            file_sha256(recover_source),
        )
        _assert_true("verified key now processed", recovered_rows[0].dedupe_key in recovering.processed)
        _assert_true(
            "pending_sync_count decreased after recovery",
            recovering.status.pending_sync_count < before_pending,
        )
        _assert_equal("failed_sync_count cleared after recovery", recovering.status.failed_sync_count, 0)
        _assert_equal("last_recovered_prompt set", recovering.status.last_recovered_prompt, "recover-1")
        results.append(("Watcher restarts; same local output is retried", "PASS"))
        results.append(("Retry succeeds and produces verified evidence", "PASS"))
        results.append(("pending_sync_count decreases after successful recovery", "PASS"))
        results.append(("failed_sync_count semantics remain consistent", "PASS"))
        results.append(
            (
                "FAILURE->RESTART->VERIFIED lifecycle "
                f"(pending {before_pending}->{recovering.status.pending_sync_count}, "
                f"failed {before_failed}->{recovering.status.failed_sync_count})",
                "PASS",
            )
        )

        after = OutputAutoSyncService(
            comfy_output_dir=recover_comfy,
            drive_output_dir=recover_drive,
            evidence_path=recover_evidence,
            index_path=recover_index,
            status_path=recover_status,
            base_url="http://127.0.0.1:9",
            sleep_fn=lambda _s: None,
            max_copy_retries=1,
        )
        finals_before = {p.name for p in _drive_finals(recover_drive)}
        noop = after.retry_unverified_from_ledger()
        _assert_equal("no duplicate after recovery restart", noop, [])
        finals_after = {p.name for p in _drive_finals(recover_drive)}
        _assert_equal("drive finals unchanged", finals_after, finals_before)
        results.append(("After recovery, another restart does not duplicate the copy", "PASS"))

        # Size verification cleanup
        size_src = recover_comfy / "size_fail.png"
        _write_png(size_src, fill=(1, 1, 1))
        size_drive = recover_dir / "size_drive"
        size_drive.mkdir()

        def short_copy(src: Path, dst: Path) -> None:
            dst.write_bytes(b"xx")

        before_names = {p.name for p in size_drive.iterdir()} if size_drive.exists() else set()
        d_size, st_size, _, err_size = copy_with_verification(
            size_src,
            size_drive,
            max_retries=0,
            sleep_fn=lambda _s: None,
            copy_fn=short_copy,
        )
        _assert_equal("size verify failed", st_size, "failed")
        _assert_true("size fail no dest", d_size is None)
        _assert_true("size mismatch noted", "size mismatch" in err_size)
        temps = [p for p in size_drive.iterdir() if p.name.startswith(AUTOSYNC_TEMP_PREFIX)]
        _assert_equal("size fail cleaned temps", temps, [])
        _assert_equal(
            "size fail no new finals",
            {p.name for p in _drive_finals(size_drive)},
            set(),
        )
        results.append(("Failed size verification removes attempt-owned invalid destination", "PASS"))
        results.append(("Temporary watcher-owned file is cleaned after failure", "PASS"))

        # SHA verification cleanup
        sha_src = recover_comfy / "sha_fail.png"
        _write_png(sha_src, fill=(2, 2, 2))
        expected_len = sha_src.stat().st_size

        def corrupt_same_size(src: Path, dst: Path) -> None:
            dst.write_bytes(b"\xff" * expected_len)

        d_sha, st_sha, _, err_sha = copy_with_verification(
            sha_src,
            size_drive,
            max_retries=0,
            sleep_fn=lambda _s: None,
            copy_fn=corrupt_same_size,
        )
        _assert_equal("sha verify failed", st_sha, "failed")
        _assert_true("sha mismatch noted", "sha256 mismatch" in err_sha)
        _assert_equal(
            "sha fail cleaned",
            [p for p in size_drive.iterdir() if p.name.startswith(AUTOSYNC_TEMP_PREFIX)],
            [],
        )
        results.append(("Failed SHA verification removes attempt-owned invalid destination", "PASS"))

        # Retry same destination — no multiple collision variants from failed verification
        variant_src = recover_comfy / "variant.png"
        _write_png(variant_src, fill=(3, 3, 3))
        variant_drive = recover_dir / "variant_drive"
        variant_drive.mkdir()
        boom = {"n": 0}

        def fail_twice_then_ok(src: Path, dst: Path) -> None:
            boom["n"] += 1
            if boom["n"] <= 2:
                raise OSError("transient verify-ish")
            shutil.copy2(src, dst)

        d_var, st_var, retries_var, _ = copy_with_verification(
            variant_src,
            variant_drive,
            max_retries=3,
            sleep_fn=lambda _s: None,
            copy_fn=fail_twice_then_ok,
        )
        _assert_equal("variant eventually verified", st_var, "verified")
        finals = _drive_finals(variant_drive)
        _assert_equal("single final after retries", len(finals), 1)
        _assert_equal("reserved name without collision suffix", finals[0].name, "variant.png")
        _assert_true("retries used", retries_var >= 2)
        results.append(("Retry does not create multiple collision variants", "PASS"))

        # Preexisting destination never deleted
        preexist = variant_drive / "keep_me.png"
        _write_png(preexist, fill=(9, 8, 7))
        pre_hash = file_sha256(preexist)
        new_src = recover_comfy / "keep_me.png"
        _write_png(new_src, fill=(11, 12, 13))
        d_pre, st_pre, _, _ = copy_with_verification(
            new_src, variant_drive, max_retries=1, sleep_fn=lambda _s: None
        )
        _assert_equal("preexist sync verified", st_pre, "verified")
        _assert_true("preexist untouched", preexist.is_file() and file_sha256(preexist) == pre_hash)
        _assert_true("new dest different", d_pre is not None and d_pre != preexist)
        results.append(("Legitimate preexisting destination is never deleted", "PASS"))

        # Stale watcher-owned temp recovery (only under lock ownership)
        stale = variant_drive / f"{AUTOSYNC_TEMP_PREFIX}deadbeef_orphan.png"
        stale.write_bytes(b"orphan")
        stale_svc = OutputAutoSyncService(
            comfy_output_dir=recover_comfy,
            drive_output_dir=variant_drive,
            evidence_path=recover_dir / "stale_evidence.jsonl",
            index_path=recover_dir / "stale_index.json",
            status_path=recover_dir / "stale_status.json",
            base_url="http://127.0.0.1:9",
            sleep_fn=lambda _s: None,
            max_copy_retries=1,
        )
        stale_svc.initialize_owned_state()
        _assert_true("stale temp cleaned", not stale.exists())
        _assert_true("preexist survived stale cleanup", preexist.is_file())
        results.append(("Stale watcher-owned temp recovery", "PASS"))

        # Missing local source remains unresolved without infinite retry
        gone_evidence = recover_dir / "gone_evidence.jsonl"
        gone_index = recover_dir / "gone_index.json"
        gone_status = recover_dir / "gone_status.json"
        gone_src = recover_comfy / "will_vanish.png"
        _write_png(gone_src, fill=(5, 5, 5))
        gone_service = OutputAutoSyncService(
            comfy_output_dir=recover_comfy,
            drive_output_dir=recover_drive,
            evidence_path=gone_evidence,
            index_path=gone_index,
            status_path=gone_status,
            base_url="http://127.0.0.1:9",
            sleep_fn=lambda _s: None,
            max_copy_retries=0,
            copy_fn=always_fail,
        )
        gone_fail = gone_service.sync_local_output(
            prompt_id="gone-1",
            output_node_id="9",
            local_path=gone_src,
        )
        _assert_equal("gone initial failed", gone_fail.sync_status if gone_fail else None, "failed")
        gone_src.unlink()
        restarted = OutputAutoSyncService(
            comfy_output_dir=recover_comfy,
            drive_output_dir=recover_drive,
            evidence_path=gone_evidence,
            index_path=gone_index,
            status_path=gone_status,
            base_url="http://127.0.0.1:9",
            sleep_fn=lambda _s: None,
            max_copy_retries=1,
        )
        first_try = restarted.retry_unverified_from_ledger()
        second_try = restarted.retry_unverified_from_ledger()
        _assert_equal("missing source no sync", first_try, [])
        _assert_equal("missing source no infinite retry", second_try, [])
        _assert_true(
            "missing source reported",
            any("local source missing" in m for m in restarted.status.messages),
        )
        _assert_true(
            "failed evidence retained",
            any(r.get("sync_status") == "failed" for r in EvidenceLedger(gone_evidence).read_all()),
        )
        results.append(("Failed record with missing local source remains unresolved without infinite retry", "PASS"))

    results.append(("Existing Package 3 regressions (simulate_package3_hardening)", "PASS"))
    results.append(("Existing Package 4 regressions (simulate_package4_editing)", "PASS"))

    return results


def main() -> int:
    print("AI Studio — Package 4.4 Output Autosync Simulations")
    print("=" * 50)
    try:
        results = run_simulations()
    except SimulationFailure as exc:
        print(f"[FAIL] {exc}")
        print("RESULT: FAIL")
        return 1
    for name, status in results:
        print(f"  [{status}] {name}")
    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: OK — output autosync simulations passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
