#!/usr/bin/env python3
"""AI Studio human-facing timezone helpers (Package 4.12.3).

Machine-immutable records continue to use UTC ISO timestamps.
Human-facing Drive filenames and local reports use the configured studio zone.
Default: America/Los_Angeles. Historical filenames are never rewritten.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_STUDIO_TIMEZONE = "America/Los_Angeles"
ENV_STUDIO_TIMEZONE = "AI_STUDIO_TIMEZONE"


def get_studio_timezone_name() -> str:
    raw = str(os.environ.get(ENV_STUDIO_TIMEZONE) or "").strip()
    return raw or DEFAULT_STUDIO_TIMEZONE


class _USPacificFallback(tzinfo):
    """DST-aware America/Los_Angeles fallback when tzdata is missing (Windows).

    US Pacific: second Sunday in March 02:00 → PDT (UTC-7);
    first Sunday in November 02:00 → PST (UTC-8).
    """

    def utcoffset(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return timedelta(hours=-8)
        return timedelta(hours=-7) if self._is_dst(dt) else timedelta(hours=-8)

    def dst(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return timedelta(0)
        return timedelta(hours=1) if self._is_dst(dt) else timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        if dt is None:
            return "PST"
        return "PDT" if self._is_dst(dt) else "PST"

    @staticmethod
    def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime:
        # weekday: Mon=0 … Sun=6
        d = datetime(year, month, 1)
        # first desired weekday
        offset = (weekday - d.weekday()) % 7
        day = 1 + offset + 7 * (n - 1)
        return datetime(year, month, day)

    def _is_dst(self, dt: datetime) -> bool:
        # Compare in local wall time without tz (naive) for transition rules.
        local = dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
        year = local.year
        start = self._nth_weekday(year, 3, 6, 2).replace(hour=2)  # 2nd Sunday March 02:00
        end = self._nth_weekday(year, 11, 6, 1).replace(hour=2)  # 1st Sunday November 02:00
        return start <= local < end


_US_PACIFIC_FALLBACK = _USPacificFallback()


def get_studio_tzinfo() -> tzinfo:
    name = get_studio_timezone_name()
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == DEFAULT_STUDIO_TIMEZONE:
            return _US_PACIFIC_FALLBACK
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
