#!/usr/bin/env python3
"""Permanent Drive asset naming for verified autosync copies.

Drive is the permanent asset library. Every verified generation receives a brand-new
immutable filename — never reuse the ComfyUI SaveImage name, never overwrite, never
append ``.1`` / ``.2`` collision suffixes for new generations.

Format:
  <capability>_<YYYYMMDD>_<sequence>.<extension>

Examples:
  txt2img_20260715_000001.png
  img2img_20260715_000002.png

Sequence is capability-specific, zero-padded to 6 digits, resets each UTC day,
and is allocated by scanning existing Drive files so it survives watcher restart.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

PERMANENT_NAME_PATTERN = re.compile(
    r"^(?P<capability>[a-z][a-z0-9_]*)_(?P<date>[0-9]{8})_(?P<seq>[0-9]{6})"
    r"(?P<ext>\.[A-Za-z0-9]+)$"
)

CAPABILITY_SLUGS = frozenset(
    {
        "txt2img",
        "img2img",
        "inpainting",
        "outpainting",
        "unknown",
        "qwen_image_edit_benchmark",
        "flux_fill_benchmark",
    }
)


def utc_date_stamp(when: datetime | None = None) -> str:
    moment = when or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%d")


def normalize_capability_slug(capability: str | None) -> str:
    raw = str(capability or "").strip().lower().replace("-", "_").replace("/", "_")
    if not raw:
        return "unknown"
    slug = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")
    if not slug:
        return "unknown"
    if slug in CAPABILITY_SLUGS:
        return slug
    # Keep descriptive unknown slugs when safe.
    if re.fullmatch(r"[a-z][a-z0-9_]{0,48}", slug):
        return slug
    return "unknown"


def parse_permanent_name(name: str) -> dict[str, str] | None:
    match = PERMANENT_NAME_PATTERN.match(name)
    if not match:
        return None
    return match.groupdict()


def max_sequence_for_day(
    drive_output_dir: Path,
    *,
    capability: str,
    date_stamp: str,
) -> int:
    """Highest sequence already present for capability+date (0 if none)."""
    slug = normalize_capability_slug(capability)
    highest = 0
    if not drive_output_dir.is_dir():
        return highest
    for path in drive_output_dir.iterdir():
        if not path.is_file():
            continue
        parsed = parse_permanent_name(path.name)
        if parsed is None:
            continue
        if parsed["capability"] != slug or parsed["date"] != date_stamp:
            continue
        try:
            highest = max(highest, int(parsed["seq"]))
        except ValueError:
            continue
    return highest


def allocate_permanent_drive_filename(
    drive_output_dir: Path,
    *,
    capability: str,
    extension: str,
    when: datetime | None = None,
) -> str:
    """Allocate the next unused permanent Drive filename for capability/day."""
    drive_output_dir.mkdir(parents=True, exist_ok=True)
    slug = normalize_capability_slug(capability)
    date_stamp = utc_date_stamp(when)
    ext = extension if extension.startswith(".") else f".{extension}"
    ext = ext.lower()
    next_seq = max_sequence_for_day(drive_output_dir, capability=slug, date_stamp=date_stamp) + 1
    while next_seq < 1_000_000:
        candidate = f"{slug}_{date_stamp}_{next_seq:06d}{ext}"
        if not (drive_output_dir / candidate).exists():
            return candidate
        next_seq += 1
    raise RuntimeError(
        f"Unable to allocate permanent Drive filename for {slug} on {date_stamp} under {drive_output_dir}."
    )


def resolve_permanent_destination(
    drive_output_dir: Path,
    *,
    capability: str,
    source_path: Path,
    when: datetime | None = None,
) -> Path:
    """Return a brand-new destination path; never equals an existing file."""
    filename = allocate_permanent_drive_filename(
        drive_output_dir,
        capability=capability,
        extension=source_path.suffix or ".png",
        when=when,
    )
    destination = drive_output_dir / filename
    if destination.exists():
        raise RuntimeError(f"Refusing to overwrite existing Drive asset: {destination}")
    return destination
