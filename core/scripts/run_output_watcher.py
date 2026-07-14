#!/usr/bin/env python3
"""ComfyUI output watcher — event-driven autosync with history polling fallback.

Startup order (normal / --once):
  1. Resolve paths
  2. Acquire exclusive watcher lock (atomic)
  3. Construct OutputAutoSyncService
  4. initialize_owned_state() — temp cleanup, index/status (lock holder only)
  5. Reconcile / run loop
  6. Release lock on exit

--status: read status file only (no lock, no service, no mutation).
--stop: inspect lock/PID; clear only confirmed stale lock (no service, no temp cleanup).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.comfyui_events import DEFAULT_COMFY_BASE, DEFAULT_COMFY_WS, HistoryFallbackWatcher
from core.runtime.output_autosync import OutputAutoSyncService
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.watcher_lock import (
    PID_NAME,
    clear_stale_lock,
    pid_alive,
    read_lock_pid,
    release_lock,
    try_acquire_lock,
)

LOCK_NAME = "output_watcher.lock"
STATUS_NAME = "output_watcher_status.json"
INDEX_NAME = "output_watcher_processed.json"


def _runtime_state_dir(bundle) -> Path:
    try:
        return bundle.path("drive_logs") / "autosync"
    except KeyError:
        return bundle.path("runtime_workflows").parent / "autosync"


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
) -> OutputAutoSyncService:
    return OutputAutoSyncService(
        comfy_output_dir=bundle.path("comfyui_output"),
        drive_output_dir=bundle.path("drive_outputs"),
        evidence_path=evidence_path,
        index_path=index_path,
        status_path=status_path,
        base_url=comfy_base_url,
        log_fn=lambda message: _append_log(log_path, message),
    )


def run_watcher_loop(
    service: OutputAutoSyncService,
    *,
    poll_seconds: float,
    stop_event: threading.Event,
    prefer_websocket: bool,
    ws_url: str,
    log_path: Path,
) -> None:
    service.reconcile_pending()
    fallback = HistoryFallbackWatcher(base_url=service.base_url)
    fallback.bootstrap()

    ws_thread_started = False
    if prefer_websocket:
        try:
            import websocket  # type: ignore

            def _on_message(_ws, message: str) -> None:
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    return
                service.handle_ws_payload(payload)

            def _ws_runner() -> None:
                while not stop_event.is_set():
                    try:
                        ws = websocket.WebSocketApp(ws_url, on_message=_on_message)
                        ws.run_forever(ping_interval=20, ping_timeout=10)
                    except Exception as exc:  # noqa: BLE001 — keep watcher alive
                        _append_log(log_path, f"WebSocket error; falling back to poll: {exc}")
                        time.sleep(2)

            thread = threading.Thread(target=_ws_runner, name="comfyui-ws-autosync", daemon=True)
            thread.start()
            ws_thread_started = True
            _append_log(log_path, f"WebSocket watcher connected preference: {ws_url}")
        except ImportError:
            _append_log(log_path, "websocket-client unavailable; using history polling fallback.")

    while not stop_event.is_set():
        try:
            for prompt_id in fallback.poll():
                service.handle_prompt_id(prompt_id)
        except Exception as exc:  # noqa: BLE001
            service.status.watcher = "WARN"
            service.status.messages.append(str(exc))
            service.write_status()
            _append_log(log_path, f"Poll warning: {exc}")
        stop_event.wait(poll_seconds)

    if ws_thread_started:
        _append_log(log_path, "Watcher stopping.")


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
    parser.add_argument("--stop", action="store_true", help="Clear stale lock if process is dead.")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--comfy-base-url", default=DEFAULT_COMFY_BASE)
    parser.add_argument("--ws-url", default=DEFAULT_COMFY_WS)
    parser.add_argument("--no-websocket", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    state_dir = _runtime_state_dir(bundle)
    lock_path = state_dir / LOCK_NAME
    status_path = state_dir / STATUS_NAME
    index_path = state_dir / INDEX_NAME
    log_path = state_dir / "output_watcher.log"
    evidence_path = bundle.path("drive_logs") / "generation_evidence.jsonl"

    if args.status:
        if status_path.is_file():
            print(status_path.read_text(encoding="utf-8"))
            return 0
        print(json.dumps({"watcher": "FAIL", "messages": ["status file missing"]}, indent=2))
        return 1

    if args.stop:
        if lock_path.exists():
            holder = read_lock_pid(lock_path)
            if holder is not None and pid_alive(holder):
                print(f"Watcher still running as pid {holder}; not stopping live process from this helper.")
                return 1
            if clear_stale_lock(lock_path):
                print("Cleared stale watcher lock.")
        return 0

    acquired, holder = try_acquire_lock(lock_path)
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
        )
        service.initialize_owned_state()

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

        service.status.watcher = "OK"
        service.write_status()
        _append_log(log_path, "Output watcher started.")
        run_watcher_loop(
            service,
            poll_seconds=max(0.5, args.poll_seconds),
            stop_event=stop_event,
            prefer_websocket=not args.no_websocket,
            ws_url=args.ws_url,
            log_path=log_path,
        )
    finally:
        release_lock(lock_path)
        if not args.once:
            _append_log(log_path, "Output watcher stopped; lock released.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
