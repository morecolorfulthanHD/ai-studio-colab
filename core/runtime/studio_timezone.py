#!/usr/bin/env python3
"""AI Studio human-facing timezone helpers (Package 4.12.3).

Machine-immutable records continue to use UTC ISO timestamps.
Human-facing Drive filenames and local reports use the configured studio zone.
Default: America/Los_Angeles. Historical filenames are never rewritten.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_STUDIO_TIMEZONE = "America/Los_Angeles"
ENV_STUDIO_TIMEZONE = "AI_STUDIO_TIMEZONE"


def get_studio_timezone_name() -> str:
    raw = str(os.environ.get(ENV_STUDIO_TIMEZONE) or "").strip()
    return raw or DEFAULT_STUDIO_TIMEZONE


def get_studio_tzinfo() -> ZoneInfo:
    name = get_studio_timezone_name()
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        # Windows dev hosts may lack the tzdata package; use a fixed PDT offset for the
        # default studio zone so CODE/SIM tests remain deterministic.
        if name == DEFAULT_STUDIO_TIMEZONE:
            return timezone(timedelta(hours=-7))
        raise ValueError(
            f"ERROR: Invalid AI Studio timezone {name!r}. "
            f"Set {ENV_STUDIO_TIMEZONE} to an IANA zone (default {DEFAULT_STUDIO_TIMEZONE}) "
            "or install the tzdata package."
        )


def studio_now(when: datetime | None = None) -> datetime:
    """Aware datetime in the studio timezone."""
    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(get_studio_tzinfo())


def studio_date_stamp(when: datetime | None = None) -> str:
    """YYYYMMDD in the studio timezone (for human-facing filenames)."""
    return studio_now(when).strftime("%Y%m%d")


def utc_iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
