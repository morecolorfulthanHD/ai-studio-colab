#!/usr/bin/env python3
"""Shared helpers for detecting eligible ComfyUI generated outputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ELIGIBLE_OUTPUT_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".mp4",
    ".webm",
}

PLACEHOLDER_BASENAMES = {
    "_output_images_will_be_put_here",
}


def is_eligible_output(path: Path) -> bool:
    if not path.is_file():
        return False

    try:
        stat = path.stat()
    except OSError:
        return False

    if stat.st_size == 0:
        return False

    if path.name in PLACEHOLDER_BASENAMES:
        return False

    return path.suffix.lower() in ELIGIBLE_OUTPUT_SUFFIXES


def latest_eligible_output(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None

    candidates = [path for path in directory.rglob("*") if is_eligible_output(path)]
    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def describe_output_file(path: Path) -> dict[str, Any]:
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0)
    return {
        "path": str(path),
        "filename": path.name,
        "extension": path.suffix.lower(),
        "size_bytes": stat.st_size,
        "modified_at": modified.isoformat(),
    }


@dataclass
class GenerationEvidence:
    local_verified: bool = False
    drive_verified: bool = False
    local_file: dict[str, Any] | None = None
    drive_file: dict[str, Any] | None = None
    historical_drive_evidence: dict[str, Any] | None = None
    local_output_dir: str = ""
    drive_output_dir: str = ""
    messages: list[str] = field(default_factory=list)

    @property
    def evidence_status(self) -> str:
        if self.local_verified and self.drive_verified:
            return "verified"
        if self.local_verified:
            return "verified_local"
        return "not_yet_verified"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_status"] = self.evidence_status
        return data


def _drive_sync_verified(local_latest: Path, drive_candidate: Path) -> tuple[bool, list[str]]:
    messages: list[str] = []
    if not drive_candidate.is_file():
        return False, messages

    try:
        drive_size = drive_candidate.stat().st_size
    except OSError:
        messages.append(
            f"Drive file exists but could not be read: {drive_candidate.name}"
        )
        return False, messages

    if drive_size == 0:
        messages.append(
            f"Drive has matching filename {drive_candidate.name} but file is empty; "
            "synchronization not verified."
        )
        return False, messages

    if not is_eligible_output(drive_candidate):
        messages.append(
            f"Drive file {drive_candidate.name} is not an eligible generated output."
        )
        return False, messages

    local_size = local_latest.stat().st_size
    if local_size != drive_size:
        messages.append(
            "Matching Drive filename found, but file size differs; "
            "synchronization is not verified."
        )
        return False, messages

    messages.append(
        f"Drive synchronization verified: {drive_candidate.name} "
        f"(matching filename and size {drive_size} bytes)."
    )
    return True, messages


def inspect_generation_evidence(
    local_output_dir: Path,
    drive_output_dir: Path | None = None,
) -> GenerationEvidence:
    evidence = GenerationEvidence(
        local_output_dir=str(local_output_dir),
        drive_output_dir=str(drive_output_dir) if drive_output_dir else "",
    )

    if not local_output_dir.is_dir():
        evidence.messages.append("ComfyUI output directory does not exist yet.")
        return evidence

    local_latest = latest_eligible_output(local_output_dir)
    if local_latest is None:
        evidence.messages.append("No eligible generated output found in ComfyUI output directory.")
        return evidence

    evidence.local_verified = True
    evidence.local_file = describe_output_file(local_latest)
    evidence.messages.append(f"Local generation evidence: {local_latest.name}")

    if drive_output_dir is None:
        return evidence

    if not drive_output_dir.is_dir():
        evidence.messages.append("Drive outputs directory does not exist yet.")
        return evidence

    drive_candidate = drive_output_dir / local_latest.name
    drive_verified, drive_messages = _drive_sync_verified(local_latest, drive_candidate)
    evidence.messages.extend(drive_messages)

    if drive_verified:
        evidence.drive_verified = True
        evidence.drive_file = describe_output_file(drive_candidate)
        return evidence

    drive_latest = latest_eligible_output(drive_output_dir)
    if drive_latest is not None:
        evidence.historical_drive_evidence = describe_output_file(drive_latest)
        evidence.messages.append(
            "Drive contains eligible output "
            f"{drive_latest.name} but not the matching local filename "
            f"{local_latest.name}; synchronization not verified for current local generation."
        )
    else:
        evidence.messages.append("No eligible synchronized output found on Drive.")

    return evidence
