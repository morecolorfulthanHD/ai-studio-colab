#!/usr/bin/env python3
"""Canonical Drive artifact ownership for identity-benchmark outputs.

Cross-path contract (Package 4.12.1):

  One ComfyUI execution (prompt_id + output_node_id + output_sha256)
  → exactly one canonical Drive image.

Ownership rule:
  - OutputWatcher/autosync is the preferred persister.
  - Benchmark capture / missed-history recovery MUST reuse a verified autosync
    Drive copy when present (or when it appears within a bounded wait).
  - Only if no verified autosync copy exists may capture create a canonical
    fallback copy under the same execution identity.
  - If capture creates first, later autosync MUST reuse that exact file.

Concurrency:
  Both paths serialize on an exclusive lock keyed by the execution artifact key
  so destination allocation + copy + evidence append cannot TOCTOU-duplicate.
"""

from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .generation_evidence_ledger import file_sha256, utc_now
from .identity_benchmark import BENCHMARK_CAPABILITY
from .jsonl_file_lock import exclusive_jsonl_lock

STATUS_REUSED_AUTOSYNC = "REUSED_AUTOSYNC"
STATUS_REUSED_EXISTING = "REUSED_EXISTING"
STATUS_CREATED_CANONICAL_FALLBACK = "CREATED_CANONICAL_FALLBACK"
STATUS_SOURCE_UNDER_DRIVE = "SOURCE_UNDER_DRIVE"
STATUS_FAILED = "FAILED"

# Bounded coordination wait when capture races ahead of watcher evidence.
# Primary coordination is the exclusive execution artifact lock; wait is only a
# secondary safety net (default off). Callers may raise it explicitly.
DEFAULT_AUTOSYNC_WAIT_SECONDS = 0.0
DEFAULT_AUTOSYNC_POLL_SECONDS = 0.05


def execution_artifact_key(prompt_id: str, output_node_id: str, output_sha256: str) -> str:
    """Shared cross-path identity for one durable Drive artifact."""
    return "|".join(
        [
            str(prompt_id or ""),
            str(output_node_id or ""),
            str(output_sha256 or "").strip().lower(),
        ]
    )


def artifact_lock_target(drive_root: Path, key: str) -> Path:
    """Stable path whose sibling ``.lock`` serializes one execution identity.

    ``exclusive_jsonl_lock`` locks ``<target>.lock``; the target itself is unused
    except as a namespaced key under ``logs/autosync/artifact_locks/``.
    """
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return Path(drive_root) / "logs" / "autosync" / "artifact_locks" / digest


@contextmanager
def exclusive_execution_artifact_lock(
    drive_root: Path,
    *,
    prompt_id: str,
    output_node_id: str,
    output_sha256: str,
    timeout_seconds: float = 30.0,
) -> Iterator[str]:
    """Serialize autosync + benchmark capture for one execution identity."""
    key = execution_artifact_key(prompt_id, output_node_id, output_sha256)
    lock_target = artifact_lock_target(drive_root, key)
    with exclusive_jsonl_lock(lock_target, timeout_seconds=timeout_seconds):
        yield key


def _default_drive_output_dir(drive_root: Path) -> Path:
    return Path(drive_root) / "outputs"


def _default_evidence_path(drive_root: Path) -> Path:
    return Path(drive_root) / "logs" / "autosync" / "evidence.jsonl"


def _path_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def find_verified_drive_copies_for_execution(
    evidence_path: Path,
    *,
    prompt_id: str,
    output_node_id: str,
    output_sha256: str,
) -> list[Path]:
    """Return verified Drive paths for exact prompt/node/SHA (unique by resolve())."""
    from .generation_evidence_ledger import EvidenceLedger

    sha = str(output_sha256 or "").strip().lower()
    if not sha or not evidence_path.is_file():
        return []
    matches: list[Path] = []
    seen: set[str] = set()
    for row in EvidenceLedger(evidence_path).read_all():
        if str(row.get("sync_status") or "") != "verified":
            continue
        if str(row.get("prompt_id") or "") != prompt_id:
            continue
        if str(row.get("output_node_id") or "") != output_node_id:
            continue
        row_sha = str(row.get("drive_sha256") or row.get("local_sha256") or "").strip().lower()
        if row_sha != sha:
            continue
        drive_path = Path(str(row.get("drive_path") or ""))
        if not drive_path.is_file():
            continue
        key = str(drive_path.resolve())
        if key in seen:
            continue
        seen.add(key)
        matches.append(drive_path)
    return matches


def choose_canonical_drive_path(candidates: list[Path]) -> tuple[Path, list[Path]]:
    """Deterministically choose one canonical path; remainder are historical duplicates."""
    if not candidates:
        raise ValueError("candidates required")
    resolved = sorted({str(p.resolve()): p for p in candidates}.items(), key=lambda item: item[0])
    canonical = resolved[0][1]
    duplicates = [p for _, p in resolved[1:]]
    return canonical, duplicates


def format_historical_duplicate_report(*, canonical: Path, duplicates: list[Path], sha: str) -> list[str]:
    lines: list[str] = []
    for dup in duplicates:
        lines.append(
            "Historical duplicate artifact detected:\n"
            f"- canonical: {canonical}\n"
            f"- duplicate: {dup}\n"
            f"- same SHA: yes ({sha})\n"
            "- action: none (report-only)"
        )
    return lines


@dataclass
class CanonicalArtifactResult:
    ok: bool
    drive_path: Path | None = None
    drive_sha256: str = ""
    local_path: str = ""
    reused_existing: bool = False
    status: str = STATUS_FAILED
    execution_key: str = ""
    historical_duplicates: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.drive_path is not None:
            payload["drive_path"] = str(self.drive_path)
        return payload


def _verify_candidate_sha(candidate: Path, sha: str) -> tuple[bool, str, str]:
    try:
        actual = file_sha256(candidate).lower()
    except OSError as exc:
        return False, "", f"Unable to read Drive artifact {candidate}: {exc}"
    if actual != sha:
        return False, actual, f"Drive SHA mismatch for {candidate} (expected {sha}, actual {actual})"
    return True, actual, ""


def _wait_for_verified_copies(
    evidence_path: Path,
    *,
    prompt_id: str,
    output_node_id: str,
    output_sha256: str,
    wait_seconds: float,
    poll_seconds: float,
) -> list[Path]:
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    while True:
        found = find_verified_drive_copies_for_execution(
            evidence_path,
            prompt_id=prompt_id,
            output_node_id=output_node_id,
            output_sha256=output_sha256,
        )
        if found:
            return found
        if time.monotonic() >= deadline:
            return []
        time.sleep(max(0.001, float(poll_seconds)))


def _append_verified_evidence(
    *,
    evidence_path: Path,
    prompt_id: str,
    output_node_id: str,
    source: Path,
    destination: Path,
    sha: str,
    drive_sha: str,
    messages: list[str],
    capability: str = BENCHMARK_CAPABILITY,
) -> None:
    from .generation_evidence_ledger import EvidenceLedger, EvidenceRecord

    EvidenceLedger(evidence_path).append(
        EvidenceRecord(
            prompt_id=prompt_id,
            schema_version=2,
            output_node_id=output_node_id,
            local_path=str(source),
            drive_path=str(destination),
            source_filename=source.name,
            drive_filename=destination.name,
            local_sha256=sha,
            drive_sha256=drive_sha,
            byte_size=destination.stat().st_size,
            created_timestamp=utc_now(),
            synchronized_timestamp=utc_now(),
            sync_status="verified",
            capability=capability,
            snapshot_status="skipped_identity_benchmark",
            messages=list(messages),
            generation_id="",
        )
    )


def ensure_canonical_identity_benchmark_artifact(
    *,
    drive_root: Path,
    source_path: Path,
    prompt_id: str,
    output_node_id: str,
    source_sha256: str,
    drive_output_dir: Path | None = None,
    evidence_path: Path | None = None,
    preferred_drive_path: Path | None = None,
    wait_for_autosync_seconds: float = DEFAULT_AUTOSYNC_WAIT_SECONDS,
    autosync_poll_seconds: float = DEFAULT_AUTOSYNC_POLL_SECONDS,
    allow_create_fallback: bool = True,
    created_by: str = "benchmark_capture",
) -> CanonicalArtifactResult:
    """Ensure exactly one verified Drive artifact for this execution identity.

    ``created_by`` is recorded in evidence messages when this path creates the file:
      - autosync → preferred owner
      - benchmark_capture / recovery → canonical fallback
    """
    from .output_autosync import copy_with_verification
    from .permanent_output_naming import resolve_permanent_destination

    result = CanonicalArtifactResult(ok=False, local_path=str(source_path))
    source = Path(source_path)
    sha = str(source_sha256 or "").strip().lower()
    out_dir = Path(drive_output_dir) if drive_output_dir else _default_drive_output_dir(drive_root)
    ev_path = Path(evidence_path) if evidence_path else _default_evidence_path(drive_root)
    result.execution_key = execution_artifact_key(prompt_id, output_node_id, sha)

    if not sha:
        result.errors.append("ERROR: source SHA required for durable benchmark artifact.")
        return result
    if not prompt_id or not output_node_id:
        result.errors.append("ERROR: prompt_id and output_node_id required for durable artifact.")
        return result

    try:
        # Bounded wait OUTSIDE the lock so autosync can still create the canonical
        # file while capture coordinates. Lock is acquired only for the final
        # check+create critical section.
        if (
            wait_for_autosync_seconds > 0
            and source.is_file()
            and not find_verified_drive_copies_for_execution(
                ev_path,
                prompt_id=prompt_id,
                output_node_id=output_node_id,
                output_sha256=sha,
            )
        ):
            _wait_for_verified_copies(
                ev_path,
                prompt_id=prompt_id,
                output_node_id=output_node_id,
                output_sha256=sha,
                wait_seconds=wait_for_autosync_seconds,
                poll_seconds=autosync_poll_seconds,
            )
        with exclusive_execution_artifact_lock(
            drive_root,
            prompt_id=prompt_id,
            output_node_id=output_node_id,
            output_sha256=sha,
        ):
            return _ensure_canonical_locked(
                result=result,
                drive_root=Path(drive_root),
                source=source,
                prompt_id=prompt_id,
                output_node_id=output_node_id,
                sha=sha,
                out_dir=out_dir,
                ev_path=ev_path,
                preferred_drive_path=preferred_drive_path,
                wait_for_autosync_seconds=0.0,
                autosync_poll_seconds=autosync_poll_seconds,
                allow_create_fallback=allow_create_fallback,
                created_by=created_by,
                copy_with_verification=copy_with_verification,
                resolve_permanent_destination=resolve_permanent_destination,
            )
    except TimeoutError as exc:
        result.errors.append(f"ERROR: Timed out acquiring identity artifact lock: {exc}")
        return result


def _ensure_canonical_locked(
    *,
    result: CanonicalArtifactResult,
    drive_root: Path,
    source: Path,
    prompt_id: str,
    output_node_id: str,
    sha: str,
    out_dir: Path,
    ev_path: Path,
    preferred_drive_path: Path | None,
    wait_for_autosync_seconds: float,
    autosync_poll_seconds: float,
    allow_create_fallback: bool,
    created_by: str,
    copy_with_verification: Any,
    resolve_permanent_destination: Any,
) -> CanonicalArtifactResult:
    # Source missing: only reuse verified Drive evidence.
    if not source.is_file():
        candidates = find_verified_drive_copies_for_execution(
            ev_path, prompt_id=prompt_id, output_node_id=output_node_id, output_sha256=sha
        )
        if preferred_drive_path is not None and Path(preferred_drive_path).is_file():
            preferred = Path(preferred_drive_path)
            if preferred not in candidates:
                candidates = [preferred] + candidates
        if not candidates:
            result.errors.append(
                f"ERROR: Benchmark output missing and no verified Drive copy: {source}"
            )
            return result
        return _finalize_reuse(result, candidates, sha, status=STATUS_REUSED_EXISTING)

    try:
        actual_source = file_sha256(source).lower()
    except OSError as exc:
        result.errors.append(f"ERROR: Unable to hash source output: {exc}")
        return result
    if actual_source != sha:
        result.errors.append(
            f"ERROR: Source SHA mismatch (expected {sha}, actual {actual_source}) for {source}"
        )
        return result

    # Prefer verified evidence for this exact execution.
    existing = find_verified_drive_copies_for_execution(
        ev_path, prompt_id=prompt_id, output_node_id=output_node_id, output_sha256=sha
    )
    if preferred_drive_path is not None and Path(preferred_drive_path).is_file():
        preferred = Path(preferred_drive_path)
        if preferred not in existing:
            existing = [preferred] + existing

    if not existing and wait_for_autosync_seconds > 0:
        existing = _wait_for_verified_copies(
            ev_path,
            prompt_id=prompt_id,
            output_node_id=output_node_id,
            output_sha256=sha,
            wait_seconds=wait_for_autosync_seconds,
            poll_seconds=autosync_poll_seconds,
        )

    if existing:
        return _finalize_reuse(result, existing, sha, status=STATUS_REUSED_AUTOSYNC)

    # Source itself may already be the canonical Drive destination (live autosync).
    if _path_under(source, out_dir):
        result.ok = True
        result.drive_path = source
        result.drive_sha256 = sha
        result.reused_existing = True
        result.status = STATUS_SOURCE_UNDER_DRIVE
        result.messages.append(f"Durable benchmark artifact: {STATUS_SOURCE_UNDER_DRIVE}")
        result.messages.append(f"Source already under Drive outputs: {source}")
        return result

    if not allow_create_fallback:
        result.errors.append(
            "ERROR: No verified autosync Drive copy yet and create-fallback disabled."
        )
        return result

    try:
        destination = resolve_permanent_destination(
            out_dir,
            capability=BENCHMARK_CAPABILITY,
            source_path=source,
        )
    except RuntimeError as exc:
        result.errors.append(f"ERROR: Unable to allocate durable Drive destination: {exc}")
        return result

    destination_result, sync_status, _retries, error = copy_with_verification(source, destination)
    if sync_status != "verified" or destination_result is None:
        # Another worker may have created the canonical file while we allocated.
        raced = find_verified_drive_copies_for_execution(
            ev_path, prompt_id=prompt_id, output_node_id=output_node_id, output_sha256=sha
        )
        if raced:
            return _finalize_reuse(result, raced, sha, status=STATUS_REUSED_AUTOSYNC)
        result.errors.append(f"ERROR: Durable Drive copy failed: {error or sync_status}")
        return result

    try:
        drive_sha = file_sha256(destination_result).lower()
    except OSError as exc:
        result.errors.append(f"ERROR: Unable to verify Drive copy SHA: {exc}")
        return result
    if drive_sha != sha:
        result.errors.append(
            f"ERROR: Drive copy SHA mismatch (expected {sha}, actual {drive_sha})"
        )
        return result

    msg_tag = (
        "identity_benchmark_autosync_canonical"
        if created_by == "autosync"
        else "identity_benchmark_recovery_durable_copy"
    )
    _append_verified_evidence(
        evidence_path=ev_path,
        prompt_id=prompt_id,
        output_node_id=output_node_id,
        source=source,
        destination=destination_result,
        sha=sha,
        drive_sha=drive_sha,
        messages=[msg_tag, f"created_by={created_by}"],
    )

    result.ok = True
    result.drive_path = destination_result
    result.drive_sha256 = drive_sha
    result.reused_existing = False
    if created_by == "autosync":
        result.status = "CREATED_BY_AUTOSYNC"
        result.messages.append("Durable benchmark artifact: CREATED_BY_AUTOSYNC")
    else:
        result.status = STATUS_CREATED_CANONICAL_FALLBACK
        result.messages.append(f"Durable benchmark artifact: {STATUS_CREATED_CANONICAL_FALLBACK}")
    result.messages.append(f"Created verified Drive artifact: {destination_result}")
    return result


def _finalize_reuse(
    result: CanonicalArtifactResult,
    candidates: list[Path],
    sha: str,
    *,
    status: str,
) -> CanonicalArtifactResult:
    verified: list[Path] = []
    for candidate in candidates:
        ok, actual, err = _verify_candidate_sha(candidate, sha)
        if not ok:
            result.errors.append(f"ERROR: {err}")
            return result
        verified.append(candidate)
        result.drive_sha256 = actual
    canonical, duplicates = choose_canonical_drive_path(verified)
    result.historical_duplicates = [str(p) for p in duplicates]
    for line in format_historical_duplicate_report(
        canonical=canonical, duplicates=duplicates, sha=sha
    ):
        result.messages.append(line)
    result.ok = True
    result.drive_path = canonical
    result.reused_existing = True
    result.status = status
    result.messages.append(f"Durable benchmark artifact: {status}")
    result.messages.append(f"Reused verified Drive artifact: {canonical}")
    return result
