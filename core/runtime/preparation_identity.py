#!/usr/bin/env python3
"""Preparation ID normalization and validation (Package 4.8).

Accepted input forms:
  - Canonical: prep_<uuid>
  - Bare UUID: <uuid>
  - Either form with surrounding whitespace

Normalized output is always lowercase:
  prep_<uuid>
"""

from __future__ import annotations

import re
import uuid

PREPARATION_ID_PREFIX = "prep_"
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class InvalidPreparationIdError(ValueError):
    """Raised when a preparation ID cannot be normalized."""


def format_preparation_id_help() -> str:
    return (
        "ERROR: Invalid preparation ID.\n"
        "Expected:\n"
        "  prep_<UUID>\n"
        "or:\n"
        "  <UUID>"
    )


def normalize_preparation_id(value: str) -> str:
    """Return canonical ``prep_<uuid>`` or raise InvalidPreparationIdError."""
    if value is None:
        raise InvalidPreparationIdError(format_preparation_id_help())
    text = str(value).strip()
    if not text:
        raise InvalidPreparationIdError(format_preparation_id_help())

    if "/" in text or "\\" in text or text.lower().endswith(
        (".png", ".jpg", ".jpeg", ".webp", ".gif", ".json", ".zip")
    ):
        raise InvalidPreparationIdError(format_preparation_id_help())

    lowered = text.lower()
    if lowered.startswith(PREPARATION_ID_PREFIX):
        remainder = lowered[len(PREPARATION_ID_PREFIX) :]
        if remainder.startswith(PREPARATION_ID_PREFIX):
            raise InvalidPreparationIdError(format_preparation_id_help())
        uuid_part = remainder
    else:
        uuid_part = lowered

    if not uuid_part or not _UUID_RE.match(uuid_part):
        raise InvalidPreparationIdError(format_preparation_id_help())

    try:
        parsed = uuid.UUID(uuid_part)
    except (ValueError, AttributeError) as exc:
        raise InvalidPreparationIdError(format_preparation_id_help()) from exc

    return f"{PREPARATION_ID_PREFIX}{str(parsed)}"


def try_normalize_preparation_id(value: str) -> str | None:
    """Return canonical ID or None when input is empty/whitespace-only."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return normalize_preparation_id(text)
