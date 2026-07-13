#!/usr/bin/env python3
"""Stage persistent inputs into the ephemeral ComfyUI input directory."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from .output_sync import collision_safe_filename, utc_collision_timestamp

CHUNK_SIZE = 1024 * 1024

STAGE_OUTCOME_REUSED_IDENTICAL = "reused_identical"
STAGE_OUTCOME_NEWLY_STAGED = "newly_staged"
STAGE_OUTCOME_COLLISION_DIFFERENT_CONTENT = "collision_different_content"
STAGE_OUTCOME_COLLISION_DIFFERENT_SIZE = "collision_different_size"


@dataclass(frozen=True)
class StageInputResult:
    staged_path: Path
    staged_filename: str
    collision_named: bool
    reused_existing: bool
    outcome: str

    @property
    def message(self) -> str:
        if self.outcome == STAGE_OUTCOME_REUSED_IDENTICAL:
            return f"Reusing identical staged file in ComfyUI/input: {self.staged_filename}"
        if self.outcome == STAGE_OUTCOME_NEWLY_STAGED:
            return f"Staging new file into ComfyUI/input: {self.staged_filename}"
        if self.outcome == STAGE_OUTCOME_COLLISION_DIFFERENT_CONTENT:
            return (
                "Existing or reserved ComfyUI/input filename contains different content; "
                f"staging as collision-safe name: {self.staged_filename}"
            )
        if self.outcome == STAGE_OUTCOME_COLLISION_DIFFERENT_SIZE:
            return (
                "Existing or reserved ComfyUI/input filename has different size; "
                f"staging as collision-safe name: {self.staged_filename}"
            )
        return f"Staged file: {self.staged_filename}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def files_identical(source: Path, destination: Path) -> bool:
    """Return True when both paths are regular files with identical byte content."""
    try:
        if not source.is_file() or not destination.is_file():
            return False
        source_stat = source.stat()
        dest_stat = destination.stat()
        if source_stat.st_size == 0 or dest_stat.st_size == 0:
            return False
        if source_stat.st_size != dest_stat.st_size:
            return False
    except OSError:
        return False
    return _file_sha256(source) == _file_sha256(destination)


def _path_occupied(path: Path, dest_dir: Path, reserved_paths: frozenset[Path]) -> bool:
    if path in reserved_paths:
        return True
    return dest_dir.is_dir() and path.is_file()


def _find_collision_destination(
    dest_dir: Path,
    source_name: str,
    *,
    timestamp: str,
    reserved_paths: frozenset[Path],
) -> Path:
    candidate = dest_dir / collision_safe_filename(source_name, timestamp=timestamp)
    suffix = 1
    while _path_occupied(candidate, dest_dir, reserved_paths):
        candidate = dest_dir / collision_safe_filename(
            source_name,
            timestamp=timestamp,
            numeric_suffix=suffix,
        )
        suffix += 1
    return candidate


def resolve_stage_destination(
    source: Path,
    dest_dir: Path,
    *,
    timestamp: str | None = None,
    reserved_paths: frozenset[Path] | None = None,
) -> tuple[Path, bool, bool, str]:
    """Plan a staged destination without creating directories or copying files."""
    reserved = reserved_paths or frozenset()
    direct = dest_dir / source.name
    if _path_occupied(direct, dest_dir, reserved):
        if direct not in reserved and dest_dir.is_dir() and direct.is_file():
            if files_identical(source, direct):
                return direct, False, True, STAGE_OUTCOME_REUSED_IDENTICAL
            try:
                same_size = direct.stat().st_size == source.stat().st_size
            except OSError:
                same_size = False
        else:
            same_size = (
                dest_dir.is_dir()
                and direct.is_file()
                and direct not in reserved
                and direct.stat().st_size == source.stat().st_size
            )
        ts = timestamp or utc_collision_timestamp()
        candidate = _find_collision_destination(
            dest_dir,
            source.name,
            timestamp=ts,
            reserved_paths=reserved,
        )
        outcome = (
            STAGE_OUTCOME_COLLISION_DIFFERENT_CONTENT
            if same_size
            else STAGE_OUTCOME_COLLISION_DIFFERENT_SIZE
        )
        return candidate, True, False, outcome
    return direct, False, False, STAGE_OUTCOME_NEWLY_STAGED


def _result_from_plan(
    destination: Path,
    *,
    collision_named: bool,
    reused: bool,
    outcome: str,
) -> StageInputResult:
    return StageInputResult(
        staged_path=destination,
        staged_filename=destination.name,
        collision_named=collision_named,
        reused_existing=reused,
        outcome=outcome,
    )


def stage_input_file(
    source: Path,
    dest_dir: Path,
    *,
    dry_run: bool = False,
    timestamp: str | None = None,
    reserved_paths: frozenset[Path] | None = None,
) -> StageInputResult:
    """Copy or reuse a single staged input file."""
    destination, collision_named, reused, outcome = resolve_stage_destination(
        source,
        dest_dir,
        timestamp=timestamp,
        reserved_paths=reserved_paths,
    )
    if not dry_run and not reused:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return _result_from_plan(
        destination,
        collision_named=collision_named,
        reused=reused,
        outcome=outcome,
    )


def stage_inputs_batch(
    source: Path,
    dest_dir: Path,
    *,
    mask: Path | None = None,
    dry_run: bool = False,
    timestamp: str | None = None,
) -> tuple[StageInputResult, StageInputResult | None]:
    """Plan and optionally stage source and mask with batch-aware path reservation."""
    operation_timestamp = timestamp or utc_collision_timestamp()
    reserved: set[Path] = set()

    source_dest, source_collision, source_reused, source_outcome = resolve_stage_destination(
        source,
        dest_dir,
        timestamp=operation_timestamp,
        reserved_paths=frozenset(reserved),
    )
    if not source_reused:
        reserved.add(source_dest)

    source_result = _result_from_plan(
        source_dest,
        collision_named=source_collision,
        reused=source_reused,
        outcome=source_outcome,
    )

    mask_result: StageInputResult | None = None
    if mask is not None:
        if mask.name == source.name and files_identical(mask, source):
            mask_result = _result_from_plan(
                source_dest,
                collision_named=source_collision,
                reused=source_reused,
                outcome=source_outcome,
            )
        else:
            mask_dest, mask_collision, mask_reused, mask_outcome = resolve_stage_destination(
                mask,
                dest_dir,
                timestamp=operation_timestamp,
                reserved_paths=frozenset(reserved),
            )
            mask_result = _result_from_plan(
                mask_dest,
                collision_named=mask_collision,
                reused=mask_reused,
                outcome=mask_outcome,
            )

    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)
        if not source_reused:
            shutil.copy2(source, source_dest)
        if mask is not None and mask_result is not None:
            share_source_path = (
                mask.name == source.name
                and files_identical(mask, source)
                and mask_result.staged_path == source_dest
            )
            if not share_source_path and not mask_result.reused_existing:
                shutil.copy2(mask, mask_result.staged_path)

    return source_result, mask_result
