#!/usr/bin/env python3
"""ComfyUI output watcher — event-driven autosync with history polling safety net.

Startup order (normal / --once):
  1. Resolve paths
  2. Acquire exclusive watcher lock (atomic)
  3. Construct OutputAutoSyncService
  4. initialize_owned_state() — temp cleanup, index/status (lock holder only)
  5. Reconcile / run loop (WebSocket primary + periodic history reconciliation)
  6. Release lock on exit

--status: read status file only (no lock, no service, no mutation).
--stop: inspect lock/PID; clear only confirmed stale lock (no service, no temp cleanup).

The notebook control panel may remain open at an interactive prompt indefinitely.
This watcher runs as an independent subprocess and must continue operating without
further notebook interaction after ComfyUI Run.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.comfyui_events import (
    DEFAULT_COMFY_BASE,
    DEFAULT_COMFY_WS,
    HistoryFallbackWatcher,
    fetch_history,
    history_entry_completed,
)
from core.runtime.generation_evidence_ledger import EvidenceLedger
from core.runtime.output_autosync import OutputAutoSyncService
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.runtime_identity import (
    RuntimeIdentity,
    current_watcher_ownership,
    ensure_runtime_identity,
    persistent_autosync_dir,
    process_cmdline,
    process_start_ticks,
    read_runtime_identity,
    read_watcher_ownership,
    runtime_identity_path,
    validate_watcher_ownership,
    watcher_lock_path,
    watcher_status_path,
)
from core.runtime.workflow_provenance import load_registered_workflow_hashes
from core.runtime.watcher_lock import (
    pid_alive,
    read_lock_pid,
    remove_ownership_files,
    release_lock,
    try_acquire_lock,
)

INDEX_NAME = "output_watcher_processed.json"
LOG_NAME = "output_watcher.log"
DEFAULT_RECONCILE_SECONDS = 15.0
STALE_VALIDATION_GRACE_SECONDS = 2.0


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _ownership_snapshot(
    *,
    lock_path: Path,
    status_path: Path,
    runtime: RuntimeIdentity | None,
    repo_root: Path,
) -> dict[str, Any]:
    owner = read_watcher_ownership(lock_path)
    status = _read_json(status_path) or {}
    defaults: dict[str, Any] = {
        "status_schema_version": 2,
        "runtime_id": runtime.runtime_id if runtime else "",
        "boot_id": runtime.boot_id if runtime else "",
        "watcher_pid": owner.pid if owner else 0,
        "process_start_ticks": owner.process_start_ticks if owner else "",
        "process_command_valid": False,
        "process_alive": False,
        "heartbeat": "",
        "heartbeat_age_seconds": None,
        "heartbeat_fresh": False,
        "last_websocket_event": "",
        "last_history_poll": "",
        "last_completed_prompt": "",
        "last_detected_output": "",
        "last_drive_copy": "",
        "last_verification": "",
        "pending_sync_count": 0,
        "failed_sync_count": 0,
        "ownership_state": "absent",
        "last_error": "",
    }
    if not lock_path.exists():
        validation = {
            "ownership_state": "absent",
            "process_alive": False,
            "process_command_valid": False,
            "process_start_ticks": "",
            "heartbeat_age_seconds": None,
            "heartbeat_fresh": False,
            "reason": "canonical current-runtime lock is absent",
        }
    else:
        validation = validate_watcher_ownership(
            owner,
            runtime,
            status,
            repo_root=repo_root,
            pid_alive_fn=pid_alive,
        ).to_dict()
    merged = dict(defaults)
    merged.update(status)
    merged.update(validation)
    merged["status_schema_version"] = 2
    if runtime is not None:
        merged["runtime_id"] = runtime.runtime_id
        merged["boot_id"] = runtime.boot_id
    state = str(merged.get("ownership_state") or "absent")
    if state == "current_runtime" and bool(merged.get("heartbeat_fresh")):
        merged["watcher"] = "WARN" if str(status.get("watcher") or "").upper() == "WARN" else "OK"
    elif state == "stale_heartbeat":
        merged["watcher"] = "WARN"
    else:
        merged["watcher"] = "FAIL"
    return merged


def _append_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")
    print(message, flush=True)


def _lock_held_noop(status_path: Path) -> int:
    print("Watcher already running (lock held). Idempotent start: no duplicate watcher.")
    if status_path.is_file():
        print(status_path.read_text(encoding="utf-8"))
    return 0


def _build_service(
    bundle,
    *,
    evidence_path: Path,
    index_path: Path,
    status_path: Path,
    log_path: Path,
    comfy_base_url: str,
    runtime: RuntimeIdentity,
    owner_start_ticks: str,
) -> OutputAutoSyncService:
    registered = load_registered_workflow_hashes(bundle.repo_root, bundle.workflows)
    active_project = ProjectWorkspace(bundle.path("drive_root")).get_active_project()
    return OutputAutoSyncService(
        comfy_output_dir=bundle.path("comfyui_output"),
        drive_output_dir=bundle.path("drive_outputs"),
        evidence_path=evidence_path,
        index_path=index_path,
        status_path=status_path,
        base_url=comfy_base_url,
        log_fn=lambda message: _append_log(log_path, message),
        registered_hashes=registered,
        active_project=active_project,
        runtime_id=runtime.runtime_id,
        boot_id=runtime.boot_id,
        process_start_ticks=owner_start_ticks,
    )


def run_watcher_loop(
    service: OutputAutoSyncService,
    *,
    poll_seconds: float,
    reconcile_seconds: float,
    stop_event: threading.Event,
    prefer_websocket: bool,
    ws_url: str,
    log_path: Path,
    refresh_active_project: Callable[[], Any] | None = None,
) -> None:
    fallback = HistoryFallbackWatcher(base_url=service.base_url)
    # Do NOT pre-mark all history as seen (that permanently dropped transient misses).
    fallback.bootstrap()
    service.touch_heartbeat(source="poll")

    ws_thread_started = False
    if prefer_websocket:
        try:
            import websocket  # type: ignore

            def _on_message(_ws, message: str) -> None:
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    return
                try:
                    _records, resolved = service.handle_ws_payload(payload)
                except Exception as exc:  # noqa: BLE001 — keep WS thread alive
                    _append_log(log_path, f"WebSocket payload error (will retry via history): {exc}")
                    resolved = False
                    _records = []
                event_type = payload.get("type")
                if event_type == "execution_success":
                    data = payload.get("data") or {}
                    prompt_id = str(data.get("prompt_id") or "")
                    if prompt_id and resolved:
                        fallback.mark_seen(prompt_id)
                    # If not resolved, leave unseen so history poll / reconcile recovers.
                service.touch_heartbeat(source="websocket")

            def _ws_runner() -> None:
                while not stop_event.is_set():
                    try:
                        ws = websocket.WebSocketApp(ws_url, on_message=_on_message)
                        _append_log(log_path, f"WebSocket connecting: {ws_url}")
                        ws.run_forever(ping_interval=20, ping_timeout=10)
                    except Exception as exc:  # noqa: BLE001 — keep watcher alive
                        _append_log(log_path, f"WebSocket error; history reconciliation continues: {exc}")
                        time.sleep(2)

            thread = threading.Thread(target=_ws_runner, name="comfyui-ws-autosync", daemon=True)
            thread.start()
            ws_thread_started = True
            _append_log(log_path, f"WebSocket watcher preferred: {ws_url}")
        except ImportError:
            _append_log(log_path, "websocket-client unavailable; using history polling safety net.")

    last_reconcile = time.time()
    while not stop_event.is_set():
        try:
            if refresh_active_project is not None:
                service.active_project = refresh_active_project()
            service.touch_heartbeat(source="poll")
            prompt_ids = fallback.poll()
            service.touch_heartbeat(source="history")
            for prompt_id in prompt_ids:
                try:
                    _records, resolved = service.handle_prompt_id(prompt_id)
                except Exception as exc:  # noqa: BLE001
                    _append_log(log_path, f"Prompt {prompt_id} handling error (will retry): {exc}")
                    resolved = False
                if resolved:
                    fallback.mark_seen(prompt_id)
                # else: leave unseen so the next poll retries

            now = time.time()
            if now - last_reconcile >= reconcile_seconds:
                # Safety net: catch missed websocket events and unfinished prompts.
                recovered = service.reconcile_pending()
                if recovered:
                    _append_log(log_path, f"History reconcile recovered/processed {len(recovered)} record(s).")
                last_reconcile = now
        except Exception as exc:  # noqa: BLE001
            service.status.watcher = "WARN"
            service.status.messages.append(str(exc))
            service.write_status()
            _append_log(log_path, f"Poll warning: {exc}")
        stop_event.wait(poll_seconds)

    if ws_thread_started:
        _append_log(log_path, "Watcher stopping.")


def _replace_invalid_ownership(
    *,
    lock_path: Path,
    status_path: Path,
    runtime: RuntimeIdentity,
    repo_root: Path,
    validation_fn: Callable[[Any, RuntimeIdentity, dict[str, Any]], Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    terminate_fn: Callable[[int, int], None] = os.kill,
    alive_fn: Callable[[int], bool] = pid_alive,
) -> str:
    """Validate and, when necessary, remove only canonical active ownership."""
    if not lock_path.exists():
        return "absent"
    owner = read_watcher_ownership(lock_path)
    status = _read_json(status_path) or {}
    def _validate(current_status: dict[str, Any]):
        if validation_fn is not None:
            return validation_fn(owner, runtime, current_status)
        return validate_watcher_ownership(
            owner,
            runtime,
            current_status,
            repo_root=repo_root,
            pid_alive_fn=alive_fn,
        )

    validation = _validate(status)
    if validation.current:
        return "current_runtime"
    if validation.ownership_state == "stale_heartbeat":
        sleep_fn(STALE_VALIDATION_GRACE_SECONDS)
        status = _read_json(status_path) or {}
        validation = _validate(status)
        if validation.current:
            return "current_runtime"
        # Terminate only a fully identified watcher from this runtime. Never kill
        # an old-runtime or foreign process merely because its PID is recorded.
        if (
            owner is not None
            and validation.process_command_valid
            and owner.runtime_id == runtime.runtime_id
            and (not runtime.boot_id or owner.boot_id == runtime.boot_id)
        ):
            try:
                terminate_fn(owner.pid, signal.SIGTERM)
            except OSError:
                pass
            deadline = time.time() + STALE_VALIDATION_GRACE_SECONDS
            while alive_fn(owner.pid) and time.time() < deadline:
                sleep_fn(0.1)
    remove_ownership_files(lock_path, status_path=status_path)
    return validation.ownership_state


def _comfyui_available(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/system_stats", timeout=2):
            return True
    except (OSError, urllib.error.URLError):
        return False


def _latest_local_outputs(output_dir: Path, limit: int = 5) -> list[str]:
    if not output_dir.is_dir():
        return []
    candidates = [path for path in output_dir.rglob("*") if path.is_file()]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [str(path) for path in candidates[:limit]]


def _diagnose(
    *,
    bundle: Any,
    repo_root: Path,
    comfy_base_url: str,
) -> int:
    """Read-only watcher/runtime diagnostic. This function performs no writes."""
    identity_path = runtime_identity_path(bundle)
    lock_path = watcher_lock_path(bundle)
    status_path = watcher_status_path(bundle)
    runtime = read_runtime_identity(identity_path)
    snapshot = _ownership_snapshot(
        lock_path=lock_path,
        status_path=status_path,
        runtime=runtime,
        repo_root=repo_root,
    )
    owner = read_watcher_ownership(lock_path)
    evidence_path = bundle.path("drive_logs") / "generation_evidence.jsonl"
    rows = EvidenceLedger(evidence_path).read_all()
    latest_evidence = rows[-1] if rows else None
    verified_prompt_ids = {
        str(row.get("prompt_id") or "")
        for row in rows
        if str(row.get("sync_status") or "") == "verified"
    }
    history_error = ""
    history: dict[str, Any] = {}
    try:
        history = fetch_history(base_url=comfy_base_url)
    except RuntimeError as exc:
        history_error = str(exc)
    newest_prompt_ids = list(history.keys())[-10:]
    unresolved = [
        str(prompt_id)
        for prompt_id, entry in history.items()
        if isinstance(entry, dict)
        and history_entry_completed(entry)
        and str(prompt_id) not in verified_prompt_ids
    ]
    project = ProjectWorkspace(bundle.path("drive_root")).get_active_project()
    legacy_dir = persistent_autosync_dir(bundle)
    payload = {
        "diagnostic_mode": "read_only",
        "runtime_identity_path": str(identity_path),
        "runtime_identity": runtime.to_dict() if runtime else None,
        "canonical_lock_path": str(lock_path),
        "canonical_lock": owner.to_dict() if owner else None,
        "canonical_status_path": str(status_path),
        "canonical_status_exists": status_path.is_file(),
        "ownership": snapshot,
        "process_cmdline": process_cmdline(owner.pid) if owner else "",
        "process_start_ticks_actual": process_start_ticks(owner.pid) if owner else "",
        "legacy_persistent_lock_path": str(legacy_dir / "output_watcher.lock"),
        "legacy_persistent_lock_ignored_for_ownership": True,
        "historical_status_path": str(legacy_dir / "output_watcher_status.json"),
        "historical_status_exists": (legacy_dir / "output_watcher_status.json").is_file(),
        "comfyui_base_url": comfy_base_url,
        "comfyui_available": _comfyui_available(comfy_base_url),
        "newest_history_prompt_ids": newest_prompt_ids,
        "history_error": history_error,
        "newest_local_outputs": _latest_local_outputs(bundle.path("comfyui_output")),
        "latest_evidence_entry": latest_evidence,
        "unresolved_completed_prompt_ids": unresolved,
        "drive_available": bundle.path("drive_root").is_dir(),
        "active_project": project.to_dict() if project else None,
    }
    print(json.dumps(payload, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start AI Studio ComfyUI output autosync watcher (zero-command Drive persistence)."
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Acquire lock, reconcile pending history once, release lock, and exit.",
    )
    parser.add_argument("--status", action="store_true", help="Print watcher status JSON and exit.")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Read-only ownership, process, ComfyUI, history, output, evidence, Drive, and project diagnostics.",
    )
    parser.add_argument(
        "--initialize-runtime",
        action="store_true",
        help="Create/read this VM's ephemeral runtime identity and exit.",
    )
    parser.add_argument("--stop", action="store_true", help="Clear stale lock if process is dead.")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--reconcile-seconds", type=float, default=DEFAULT_RECONCILE_SECONDS)
    parser.add_argument("--comfy-base-url", default=DEFAULT_COMFY_BASE)
    parser.add_argument("--ws-url", default=DEFAULT_COMFY_WS)
    parser.add_argument("--no-websocket", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    lock_path = watcher_lock_path(bundle)
    status_path = watcher_status_path(bundle)
    persistent_dir = persistent_autosync_dir(bundle)
    index_path = persistent_dir / INDEX_NAME
    log_path = persistent_dir / LOG_NAME
    evidence_path = bundle.path("drive_logs") / "generation_evidence.jsonl"

    if args.diagnose:
        return _diagnose(
            bundle=bundle,
            repo_root=repo_root,
            comfy_base_url=args.comfy_base_url,
        )

    identity_file = runtime_identity_path(bundle)
    if args.initialize_runtime:
        print(json.dumps(ensure_runtime_identity(identity_file).to_dict(), indent=2))
        return 0

    runtime = read_runtime_identity(identity_file)
    if args.status:
        snapshot = _ownership_snapshot(
            lock_path=lock_path,
            status_path=status_path,
            runtime=runtime,
            repo_root=repo_root,
        )
        print(json.dumps(snapshot, indent=2))
        return 0 if snapshot.get("watcher") == "OK" else 1

    runtime = runtime or ensure_runtime_identity(identity_file)

    if args.stop:
        if lock_path.exists():
            state = _replace_invalid_ownership(
                lock_path=lock_path,
                status_path=status_path,
                runtime=runtime,
                repo_root=repo_root,
            )
            if state == "current_runtime":
                holder = read_lock_pid(lock_path)
                print(f"Watcher is healthy as pid {holder}; refusing to stop it.")
                return 1
            print(f"Cleared invalid watcher ownership ({state}).")
        return 0

    prior_state = _replace_invalid_ownership(
        lock_path=lock_path,
        status_path=status_path,
        runtime=runtime,
        repo_root=repo_root,
    )
    if prior_state == "current_runtime":
        return _lock_held_noop(status_path)

    owner = current_watcher_ownership(
        runtime,
        repo_root=repo_root,
        comfyui_base_url=args.comfy_base_url,
    )
    acquired, holder = try_acquire_lock(lock_path, owner=owner)
    if not acquired:
        return _lock_held_noop(status_path)

    try:
        service = _build_service(
            bundle,
            evidence_path=evidence_path,
            index_path=index_path,
            status_path=status_path,
            log_path=log_path,
            comfy_base_url=args.comfy_base_url,
            runtime=runtime,
            owner_start_ticks=owner.process_start_ticks,
        )
        service.initialize_owned_state()
        service.status.watcher_pid = os.getpid()
        service.touch_heartbeat(source="poll")

        if args.once:
            records = service.reconcile_pending()
            print(json.dumps({"processed": len(records), "status": service.status.to_dict()}, indent=2))
            return 0

        stop_event = threading.Event()

        def _handle_signal(_signum, _frame) -> None:
            stop_event.set()

        signal.signal(signal.SIGINT, _handle_signal)
        try:
            signal.signal(signal.SIGTERM, _handle_signal)
        except (AttributeError, ValueError):
            pass

        # Reconcile before claiming healthy. This recovers prompts completed while
        # the previous/absent watcher was not running, without a manual --once.
        service.active_project = ProjectWorkspace(bundle.path("drive_root")).get_active_project()
        recovered = service.reconcile_pending()
        service.touch_heartbeat(source="poll")
        if not service.status.last_history_poll:
            service.status.watcher = "FAIL"
            service.status.ownership_state = "stale_heartbeat"
            service.status.last_error = "Initial ComfyUI history reconciliation did not succeed."
            service.write_status()
            _append_log(log_path, service.status.last_error)
            return 1
        service.status.watcher = "OK"
        service.write_status()
        _append_log(
            log_path,
            (
                f"Output watcher started (pid {os.getpid()}, runtime {runtime.runtime_id}); "
                f"immediate reconcile processed {len(recovered)} record(s). "
                "Independent of notebook menu."
            ),
        )
        run_watcher_loop(
            service,
            poll_seconds=max(0.5, args.poll_seconds),
            reconcile_seconds=max(5.0, args.reconcile_seconds),
            stop_event=stop_event,
            prefer_websocket=not args.no_websocket,
            ws_url=args.ws_url,
            log_path=log_path,
            refresh_active_project=lambda: ProjectWorkspace(
                bundle.path("drive_root")
            ).get_active_project(),
        )
    finally:
        release_lock(lock_path)
        if not args.once:
            _append_log(log_path, "Output watcher stopped; lock released.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
