#!/usr/bin/env python3
"""Event-driven ComfyUI output discovery, Drive sync, hash verification, and evidence.

Copy/verification model:
  1. Resolve one collision-safe final destination for the operation (never overwrite).
  2. Copy into a watcher-owned temporary file in the Drive output directory.
  3. Verify temporary file size and SHA-256 against the source.
  4. Atomically rename (os.replace) the temp onto the reserved destination when possible.
  5. On failure, delete only the attempt-owned temp (and never delete preexisting Dest files
     or the ComfyUI local source).

Fallback: if rename fails after a verified temp, report the error, leave diagnostics in the
evidence record, and clean the temp when safe — never claim verified without a matching
final destination SHA-256.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .comfyui_events import (
    DEFAULT_COMFY_BASE,
    extract_output_files,
    fetch_history,
    parse_ws_message,
)
from .generation_evidence_ledger import (
    EvidenceLedger,
    EvidenceRecord,
    dedupe_key_from_parts,
    file_sha256,
    utc_now,
)
from .output_evidence import ELIGIBLE_OUTPUT_SUFFIXES, is_eligible_output
from .output_sync import resolve_sync_destination
from .watcher_lock import pid_alive

AUTOSYNC_TEMP_PREFIX = ".ai_studio_autosync_tmp."


def parse_autosync_temp_pid(name: str) -> int | None:
    """Return owning PID from `.ai_studio_autosync_tmp.<pid>.<uuid>_<dest>` or None (legacy)."""
    if not name.startswith(AUTOSYNC_TEMP_PREFIX):
        return None
    rest = name[len(AUTOSYNC_TEMP_PREFIX) :]
    if "." not in rest:
        return None
    pid_part, _remainder = rest.split(".", 1)
    if pid_part.isdigit():
        return int(pid_part)
    return None


def make_autosync_temp_path(
    drive_output_dir: Path,
    destination_name: str,
    *,
    owner_pid: int | None = None,
) -> Path:
    pid = owner_pid if owner_pid is not None else os.getpid()
    return drive_output_dir / f"{AUTOSYNC_TEMP_PREFIX}{pid}.{uuid.uuid4().hex}_{destination_name}"


@dataclass
class AutoSyncStatus:
    watcher: str = "OK"
    last_completed_prompt: str = ""
    last_detected_output: str = ""
    last_drive_copy: str = ""
    last_verification: str = ""
    pending_sync_count: int = 0
    failed_sync_count: int = 0
    evidence_status: str = "idle"
    last_error: str = ""
    last_retry_timestamp: str = ""
    last_recovered_prompt: str = ""
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessedIndex:
    path: Path

    def load(self) -> set[str]:
        if not self.path.is_file():
            return set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        if isinstance(data, list):
            return {str(item) for item in data}
        return set()

    def save(self, keys: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(keys), indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)


def wait_until_stable(
    path: Path,
    *,
    interval_seconds: float = 0.35,
    checks: int = 3,
    timeout_seconds: float = 30.0,
) -> bool:
    deadline = time.time() + timeout_seconds
    last_size = -1
    stable = 0
    while time.time() < deadline:
        if not path.is_file():
            time.sleep(interval_seconds)
            continue
        try:
            size = path.stat().st_size
        except OSError:
            time.sleep(interval_seconds)
            continue
        if size <= 0:
            stable = 0
            last_size = size
            time.sleep(interval_seconds)
            continue
        if size == last_size:
            stable += 1
            if stable >= checks:
                return True
        else:
            stable = 0
            last_size = size
        time.sleep(interval_seconds)
    return False


def resolve_comfy_output_path(
    comfy_output_dir: Path,
    *,
    filename: str,
    subfolder: str = "",
) -> Path:
    if subfolder:
        return comfy_output_dir / subfolder / filename
    return comfy_output_dir / filename


def is_autosync_temp_name(name: str) -> bool:
    return name.startswith(AUTOSYNC_TEMP_PREFIX)


def cleanup_stale_autosync_temps(
    drive_output_dir: Path,
    *,
    pid_alive_fn: Callable[[int], bool] | None = None,
) -> list[str]:
    """Remove watcher-owned temps not owned by a live PID. Call only under watcher lock."""
    cleaned: list[str] = []
    if not drive_output_dir.is_dir():
        return cleaned
    alive = pid_alive_fn or pid_alive
    for path in drive_output_dir.iterdir():
        if not path.is_file():
            continue
        if not is_autosync_temp_name(path.name):
            continue
        temp_pid = parse_autosync_temp_pid(path.name)
        if temp_pid is not None and alive(temp_pid):
            continue
        try:
            path.unlink()
            cleaned.append(str(path))
        except OSError:
            cleaned.append(f"FAILED_CLEANUP:{path}")
    return cleaned


def _safe_unlink(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        if path.is_file():
            path.unlink()
        return ""
    except OSError as exc:
        return f"cleanup failed for {path}: {exc}"


def copy_with_verification(
    source: Path,
    drive_output_dir: Path,
    *,
    max_retries: int = 3,
    sleep_fn: Callable[[float], None] = time.sleep,
    copy_fn: Callable[[Path, Path], None] | None = None,
    owner_pid: int | None = None,
) -> tuple[Path | None, str, int, str]:
    """Copy source to Drive via temp + verify + rename; one destination per operation."""
    drive_output_dir.mkdir(parents=True, exist_ok=True)
    copier = copy_fn or (lambda src, dst: shutil.copy2(src, dst))
    destination, _collision, preexisting = resolve_sync_destination(drive_output_dir, source.name)
    if preexisting is not None and preexisting.exists() and destination == preexisting:
        return None, "failed", 0, "refusing to overwrite preexisting destination"

    retries = 0
    last_error = ""
    while retries <= max_retries:
        temp_path = make_autosync_temp_path(
            drive_output_dir,
            destination.name,
            owner_pid=owner_pid,
        )
        created_destination = False
        try:
            if not source.is_file():
                last_error = f"source missing: {source}"
                retries += 1
                sleep_fn(min(2 ** retries, 8))
                continue
            copier(source, temp_path)
            source_size = source.stat().st_size
            dest_size = temp_path.stat().st_size
            if source_size != dest_size or source_size == 0:
                last_error = f"size mismatch or empty copy ({source_size} vs {dest_size})"
                cleanup_err = _safe_unlink(temp_path)
                if cleanup_err:
                    last_error = f"{last_error}; {cleanup_err}"
                retries += 1
                sleep_fn(min(2 ** retries, 8))
                continue
            source_hash = file_sha256(source)
            dest_hash = file_sha256(temp_path)
            if source_hash != dest_hash:
                last_error = "sha256 mismatch after copy"
                cleanup_err = _safe_unlink(temp_path)
                if cleanup_err:
                    last_error = f"{last_error}; {cleanup_err}"
                retries += 1
                sleep_fn(min(2 ** retries, 8))
                continue
            if destination.exists():
                last_error = f"destination appeared during sync: {destination.name}"
                cleanup_err = _safe_unlink(temp_path)
                if cleanup_err:
                    last_error = f"{last_error}; {cleanup_err}"
                retries += 1
                sleep_fn(min(2 ** retries, 8))
                continue
            try:
                os.replace(temp_path, destination)
                created_destination = True
            except OSError as rename_exc:
                # Drive may not support atomic rename; fallback copy only if dest absent.
                last_error = f"rename failed ({rename_exc}); attempting fallback copy"
                try:
                    if destination.exists():
                        raise OSError("destination exists; cannot fallback-copy")
                    shutil.copy2(temp_path, destination)
                    created_destination = True
                    if file_sha256(destination) != source_hash or destination.stat().st_size != source_size:
                        cleanup_dest = _safe_unlink(destination)
                        created_destination = False
                        raise OSError(
                            "fallback copy failed verification"
                            + (f"; {cleanup_dest}" if cleanup_dest else "")
                        )
                    _safe_unlink(temp_path)
                except OSError as fallback_exc:
                    cleanup_err = _safe_unlink(temp_path)
                    last_error = f"{last_error}; {fallback_exc}"
                    if cleanup_err:
                        last_error = f"{last_error}; {cleanup_err}"
                    retries += 1
                    sleep_fn(min(2 ** retries, 8))
                    continue
            if not destination.is_file():
                last_error = "destination missing after rename"
                retries += 1
                sleep_fn(min(2 ** retries, 8))
                continue
            if destination.stat().st_size != source_size or file_sha256(destination) != source_hash:
                last_error = "destination failed final size/sha verification"
                if created_destination:
                    cleanup_err = _safe_unlink(destination)
                    if cleanup_err:
                        last_error = f"{last_error}; {cleanup_err}"
                retries += 1
                sleep_fn(min(2 ** retries, 8))
                continue
            return destination, "verified", retries, ""
        except OSError as exc:
            last_error = str(exc)
            cleanup_err = _safe_unlink(temp_path)
            if cleanup_err:
                last_error = f"{last_error}; {cleanup_err}"
            retries += 1
            if retries > max_retries:
                break
            sleep_fn(min(2 ** retries, 8))
        finally:
            if temp_path.exists() and is_autosync_temp_name(temp_path.name):
                _safe_unlink(temp_path)
    return None, "failed", retries, last_error


class OutputAutoSyncService:
    def __init__(
        self,
        *,
        comfy_output_dir: Path,
        drive_output_dir: Path,
        evidence_path: Path,
        index_path: Path,
        status_path: Path,
        base_url: str = DEFAULT_COMFY_BASE,
        log_fn: Callable[[str], None] | None = None,
        max_copy_retries: int = 3,
        sleep_fn: Callable[[float], None] | None = None,
        copy_fn: Callable[[Path, Path], None] | None = None,
    ) -> None:
        self.comfy_output_dir = comfy_output_dir
        self.drive_output_dir = drive_output_dir
        self.ledger = EvidenceLedger(evidence_path)
        self.index = ProcessedIndex(index_path)
        self.status_path = status_path
        self.base_url = base_url
        self.log = log_fn or (lambda message: None)
        self.max_copy_retries = max_copy_retries
        self.sleep_fn = sleep_fn or time.sleep
        self.copy_fn = copy_fn
        # Permanent processed set = verified keys only.
        self.processed = self.index.load()
        self.processed.update(self.ledger.verified_keys())
        # Keys whose local source is gone — report once, avoid hot-looping.
        self.unrecoverable_missing_source: set[str] = set()
        self.status = AutoSyncStatus()
        self.recompute_counters()

    def initialize_owned_state(
        self,
        *,
        pid_alive_fn: Callable[[int], bool] | None = None,
    ) -> list[str]:
        """Initialize mutable watcher state. Call only after exclusive lock acquisition."""
        cleaned = cleanup_stale_autosync_temps(
            self.drive_output_dir,
            pid_alive_fn=pid_alive_fn,
        )
        if cleaned:
            self.status.messages.append(f"Cleaned {len(cleaned)} stale autosync temp file(s).")
        self.recompute_counters()
        self.index.save(self.processed)
        self.write_status()
        return cleaned

    def write_status(self) -> None:
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.status_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.status.to_dict(), indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.status_path)

    def recompute_counters(self) -> None:
        """pending/failed counts reflect currently unresolved (retryable) outputs."""
        retryable = self.ledger.retryable_records()
        pending = 0
        failed = 0
        for row in retryable:
            status = str(row.get("sync_status") or "")
            if status == "pending":
                pending += 1
            elif status == "failed":
                failed += 1
        self.status.pending_sync_count = pending + failed
        self.status.failed_sync_count = failed

    def _prior_error_for_key(self, key: str) -> str:
        latest = self.ledger.latest_record_by_key().get(key)
        if not latest:
            return ""
        return str(latest.get("error_summary") or latest.get("prior_error_summary") or "")

    def _prior_retry_count(self, key: str) -> int:
        latest = self.ledger.latest_record_by_key().get(key)
        if not latest:
            return 0
        try:
            return int(latest.get("retry_count") or 0)
        except (TypeError, ValueError):
            return 0

    def sync_local_output(
        self,
        *,
        prompt_id: str,
        output_node_id: str,
        local_path: Path,
        workflow_identifier: str = "",
        workflow_hash: str = "",
        candidate_model: str = "",
        capability: str = "",
        recovery: bool = False,
    ) -> EvidenceRecord | None:
        if not is_eligible_output(local_path):
            return None
        if local_path.suffix.lower() not in ELIGIBLE_OUTPUT_SUFFIXES:
            return None
        if not wait_until_stable(local_path, timeout_seconds=30, checks=2, interval_seconds=0.05):
            self.status.last_error = f"Timed out waiting for stable file: {local_path}"
            self.status.messages.append(self.status.last_error)
            self.recompute_counters()
            self.write_status()
            return None

        local_hash = file_sha256(local_path)
        key = dedupe_key_from_parts(prompt_id, output_node_id, str(local_path), local_hash)
        if key in self.processed:
            self.log(f"Skipping already verified output: {local_path.name}")
            return None

        prior_error = self._prior_error_for_key(key)
        prior_retries = self._prior_retry_count(key)
        now = utc_now()
        if recovery:
            self.status.last_retry_timestamp = now

        self.status.last_completed_prompt = prompt_id
        self.status.last_detected_output = str(local_path)
        self.log(f"Output detected:\n{local_path}")

        pending = EvidenceRecord(
            prompt_id=prompt_id,
            workflow_identifier=workflow_identifier,
            workflow_hash=workflow_hash,
            output_node_id=output_node_id,
            local_path=str(local_path),
            local_sha256=local_hash,
            byte_size=local_path.stat().st_size,
            created_timestamp=now,
            sync_status="pending",
            retry_count=prior_retries,
            prior_error_summary=prior_error,
            candidate_model=candidate_model,
            capability=capability,
            messages=["recovery_attempt"] if recovery else [],
        )
        self.ledger.append(pending)
        self.recompute_counters()
        self.write_status()

        destination, sync_status, retries, error = copy_with_verification(
            local_path,
            self.drive_output_dir,
            max_retries=self.max_copy_retries,
            sleep_fn=self.sleep_fn,
            copy_fn=self.copy_fn,
        )
        attempt_retries = prior_retries + retries
        if sync_status == "verified" and destination is not None:
            record = EvidenceRecord(
                prompt_id=prompt_id,
                workflow_identifier=workflow_identifier,
                workflow_hash=workflow_hash,
                output_node_id=output_node_id,
                local_path=str(local_path),
                drive_path=str(destination),
                local_sha256=local_hash,
                drive_sha256=file_sha256(destination),
                byte_size=local_path.stat().st_size,
                created_timestamp=now,
                synchronized_timestamp=utc_now(),
                sync_status="verified",
                retry_count=attempt_retries,
                prior_error_summary=prior_error,
                candidate_model=candidate_model,
                capability=capability,
                messages=["recovered_after_failure"] if recovery and prior_error else [],
            )
            self.ledger.append(record)
            self.processed.add(key)
            self.index.save(self.processed)
            self.status.last_drive_copy = str(destination)
            self.status.last_verification = "verified"
            self.status.evidence_status = "verified"
            self.status.last_error = ""
            if recovery:
                self.status.last_recovered_prompt = prompt_id
            self.log(f"Drive copy verified:\n{destination}")
            self.log(f"Evidence updated:\n{prompt_id}")
            self.recompute_counters()
            self.write_status()
            return record

        record = EvidenceRecord(
            prompt_id=prompt_id,
            workflow_identifier=workflow_identifier,
            workflow_hash=workflow_hash,
            output_node_id=output_node_id,
            local_path=str(local_path),
            local_sha256=local_hash,
            byte_size=local_path.stat().st_size,
            created_timestamp=now,
            sync_status="failed",
            retry_count=attempt_retries,
            error_summary=error or "copy verification failed",
            prior_error_summary=prior_error,
            candidate_model=candidate_model,
            capability=capability,
            messages=["recovery_attempt_failed"] if recovery else [],
        )
        self.ledger.append(record)
        # Intentionally do NOT add failed keys to self.processed.
        self.status.last_verification = "failed"
        self.status.evidence_status = "failed"
        self.status.last_error = record.error_summary
        self.recompute_counters()
        self.write_status()
        return record

    def handle_prompt_id(self, prompt_id: str) -> list[EvidenceRecord]:
        history = fetch_history(base_url=self.base_url, prompt_id=prompt_id)
        if prompt_id in history and isinstance(history[prompt_id], dict):
            entry = history[prompt_id]
        elif "outputs" in history:
            entry = history
        else:
            self.status.messages.append(f"No history entry for prompt {prompt_id}")
            self.recompute_counters()
            self.write_status()
            return []

        output_metas = extract_output_files(entry)
        records: list[EvidenceRecord] = []
        if not output_metas:
            self.status.messages.append(f"Prompt {prompt_id} produced no eligible outputs.")
            self.status.last_completed_prompt = prompt_id
            self.recompute_counters()
            self.write_status()
            return records

        for meta in output_metas:
            local_path = resolve_comfy_output_path(
                self.comfy_output_dir,
                filename=meta["filename"],
                subfolder=meta.get("subfolder") or "",
            )
            record = self.sync_local_output(
                prompt_id=prompt_id,
                output_node_id=str(meta.get("node_id") or ""),
                local_path=local_path,
            )
            if record is not None:
                records.append(record)
        return records

    def handle_ws_payload(self, payload: dict[str, Any]) -> list[EvidenceRecord]:
        event = parse_ws_message(payload)
        if event is None:
            return []
        if payload.get("type") == "executed":
            return []
        return self.handle_prompt_id(event.prompt_id)

    def retry_unverified_from_ledger(self) -> list[EvidenceRecord]:
        """Retry pending/failed records when local source still exists and hash matches."""
        records: list[EvidenceRecord] = []
        for row in self.ledger.retryable_records():
            key = dedupe_key_from_parts(
                str(row.get("prompt_id") or ""),
                str(row.get("output_node_id") or ""),
                str(row.get("local_path") or ""),
                str(row.get("local_sha256") or ""),
            )
            if key in self.processed:
                continue
            if key in self.unrecoverable_missing_source:
                continue
            local_path = Path(str(row.get("local_path") or ""))
            expected_hash = str(row.get("local_sha256") or "")
            if not local_path.is_file():
                msg = (
                    f"Recovery impossible: local source missing for prompt "
                    f"{row.get('prompt_id')} ({local_path})"
                )
                self.status.messages.append(msg)
                self.status.last_error = msg
                self.unrecoverable_missing_source.add(key)
                continue
            try:
                actual_hash = file_sha256(local_path)
            except OSError as exc:
                msg = f"Recovery impossible: cannot hash local source {local_path}: {exc}"
                self.status.messages.append(msg)
                self.status.last_error = msg
                self.unrecoverable_missing_source.add(key)
                continue
            if expected_hash and actual_hash != expected_hash:
                msg = (
                    f"Recovery skipped: local hash changed for {local_path} "
                    f"(evidence {expected_hash[:12]}… vs current {actual_hash[:12]}…)"
                )
                self.status.messages.append(msg)
                continue
            recovered = self.sync_local_output(
                prompt_id=str(row.get("prompt_id") or ""),
                output_node_id=str(row.get("output_node_id") or ""),
                local_path=local_path,
                workflow_identifier=str(row.get("workflow_identifier") or ""),
                workflow_hash=str(row.get("workflow_hash") or ""),
                candidate_model=str(row.get("candidate_model") or ""),
                capability=str(row.get("capability") or ""),
                recovery=True,
            )
            if recovered is not None:
                records.append(recovered)
        self.recompute_counters()
        self.write_status()
        return records

    def reconcile_pending(self) -> list[EvidenceRecord]:
        """Startup recovery: retry unverified ledger rows, then discover unrecorded history."""
        records = self.retry_unverified_from_ledger()
        try:
            history = fetch_history(base_url=self.base_url)
        except RuntimeError as exc:
            self.status.watcher = "WARN"
            self.status.messages.append(str(exc))
            self.recompute_counters()
            self.write_status()
            return records
        for prompt_id, entry in history.items():
            if not isinstance(entry, dict):
                continue
            for meta in extract_output_files(entry):
                local_path = resolve_comfy_output_path(
                    self.comfy_output_dir,
                    filename=meta["filename"],
                    subfolder=meta.get("subfolder") or "",
                )
                if not local_path.is_file():
                    continue
                try:
                    key_probe = dedupe_key_from_parts(
                        str(prompt_id),
                        str(meta.get("node_id") or ""),
                        str(local_path),
                        file_sha256(local_path),
                    )
                except OSError:
                    continue
                if key_probe in self.processed:
                    continue
                synched = self.sync_local_output(
                    prompt_id=str(prompt_id),
                    output_node_id=str(meta.get("node_id") or ""),
                    local_path=local_path,
                    recovery=False,
                )
                if synched is not None:
                    records.append(synched)
        self.recompute_counters()
        self.write_status()
        return records


def format_completion_message(record: EvidenceRecord) -> str:
    return (
        f"Output detected:\n{record.local_path}\n"
        f"Drive copy verified:\n{record.drive_path or '(failed)'}\n"
        f"Evidence updated:\n{record.prompt_id}"
    )
