#!/usr/bin/env python3
"""Generation ID normalization and validation (Package 4.7.1).

Accepted input forms:
  - Canonical: gen_<uuid>
  - Bare UUID: <uuid>
  - Either form with surrounding whitespace

Normalized output is always lowercase:
  gen_<uuid>

The optional ``gen_`` prefix is accepted case-insensitively (``GEN_``, ``Gen_``).
UUID hex digits are normalized to lowercase. Partial UUIDs, filenames, and
arbitrary strings are rejected.
"""

from __future__ import annotations

import re
import uuid

GENERATION_ID_PREFIX = "gen_"
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class InvalidGenerationIdError(ValueError):
    """Raised when a generation ID cannot be normalized."""


def format_generation_id_help() -> str:
    return (
        "ERROR: Invalid generation ID.\n"
        "Expected:\n"
        "  gen_<UUID>\n"
        "or:\n"
        "  <UUID>"
    )


def normalize_generation_id(value: str) -> str:
    """Return canonical ``gen_<uuid>`` or raise InvalidGenerationIdError."""
    if value is None:
        raise InvalidGenerationIdError(format_generation_id_help())
    text = str(value).strip()
    if not text:
        raise InvalidGenerationIdError(format_generation_id_help())

    # Reject obvious filenames / path fragments.
    if "/" in text or "\\" in text or text.lower().endswith(
        (".png", ".jpg", ".jpeg", ".webp", ".gif", ".json", ".zip")
    ):
        raise InvalidGenerationIdError(format_generation_id_help())

    lowered = text.lower()
    if lowered.startswith(GENERATION_ID_PREFIX):
        remainder = lowered[len(GENERATION_ID_PREFIX) :]
        # Reject double prefix: gen_gen_<uuid>
        if remainder.startswith(GENERATION_ID_PREFIX):
            raise InvalidGenerationIdError(format_generation_id_help())
        uuid_part = remainder
    else:
        uuid_part = lowered

    if not uuid_part or not _UUID_RE.match(uuid_part):
        raise InvalidGenerationIdError(format_generation_id_help())

    try:
        parsed = uuid.UUID(uuid_part)
    except (ValueError, AttributeError) as exc:
        raise InvalidGenerationIdError(format_generation_id_help()) from exc

    return f"{GENERATION_ID_PREFIX}{str(parsed)}"


def try_normalize_generation_id(value: str) -> str | None:
    """Return canonical ID or None when input is empty/whitespace-only."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return normalize_generation_id(text)
