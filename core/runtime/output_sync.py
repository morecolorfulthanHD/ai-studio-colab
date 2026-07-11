#!/usr/bin/env python3
"""Collision-safe destination naming for ComfyUI output synchronization."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

COLLISION_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_COLLISION_SAFE_STEM_PATTERN = re.compile(
    r"^(?P<base>.+)__(?P<timestamp>[0-9]{8}T[0-9]{6}Z)(?:\.(?P<suffix>[0-9]+))?$"
)


def utc_collision_timestamp(when: datetime | None = None) -> str:
    moment = when or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime(COLLISION_TIMESTAMP_FORMAT)


def collision_base_stem(original_name: str) -> str:
    return Path(original_name).stem.rstrip("_")


def collision_safe_filename(
    original_name: str,
    *,
    timestamp: str,
    numeric_suffix: int | None = None,
) -> str:
    path = Path(original_name)
    base = collision_base_stem(original_name)
    suffix = path.suffix
    if numeric_suffix is None:
        return f"{base}__{timestamp}{suffix}"
    return f"{base}__{timestamp}.{numeric_suffix}{suffix}"


def is_collision_safe_derivative(local_filename: str, drive_filename: str) -> bool:
    local_path = Path(local_filename)
    drive_path = Path(drive_filename)
    if local_path.suffix.lower() != drive_path.suffix.lower():
        return False
    base = collision_base_stem(local_filename)
    match = _COLLISION_SAFE_STEM_PATTERN.match(drive_path.stem)
    if not match:
        return False
    return match.group("base") == base


def resolve_sync_destination(
    dest_dir: Path,
    source_name: str,
    *,
    fail_on_existing: bool = False,
    timestamp: str | None = None,
) -> tuple[Path, bool, Path | None]:
    """Return destination path, whether a collision was detected, and the original path."""
    original_dest = dest_dir / source_name
    if not original_dest.exists():
        return original_dest, False, None

    if fail_on_existing:
        return original_dest, True, original_dest

    ts = timestamp or utc_collision_timestamp()
    candidate = dest_dir / collision_safe_filename(source_name, timestamp=ts)
    if not candidate.exists():
        return candidate, True, original_dest

    suffix = 1
    while suffix < 10_000:
        candidate = dest_dir / collision_safe_filename(
            source_name,
            timestamp=ts,
            numeric_suffix=suffix,
        )
        if not candidate.exists():
            return candidate, True, original_dest
        suffix += 1

    raise RuntimeError(
        f"Unable to find a collision-safe destination for {source_name} under {dest_dir}."
    )


def find_collision_safe_drive_match(local_file: Path, drive_output_dir: Path) -> Path | None:
    """Find a collision-safe Drive copy of the local file with an exact byte-size match."""
    if not drive_output_dir.is_dir():
        return None

    local_size = local_file.stat().st_size
    matches: list[Path] = []

    for drive_path in drive_output_dir.iterdir():
        if not drive_path.is_file():
            continue
        if drive_path.name == local_file.name:
            matches.append(drive_path)
            continue
        if is_collision_safe_derivative(local_file.name, drive_path.name):
            matches.append(drive_path)

    verified = [
        path
        for path in matches
        if path.stat().st_size == local_size and path.stat().st_size > 0
    ]
    if not verified:
        return None

    if len(verified) == 1:
        return verified[0]

    exact = [path for path in verified if path.name == local_file.name]
    if exact:
        return exact[0]

    return max(verified, key=lambda path: path.stat().st_mtime)
