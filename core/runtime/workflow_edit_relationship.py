#!/usr/bin/env python3
"""Compare canonical, prepared, and executed workflow relationships (Package 4.8)."""

from __future__ import annotations

from typing import Any


def compare_workflow_relationship(
    canonical_hash: str,
    prepared_hash: str,
    executed_hash: str,
) -> dict[str, Any]:
    """Return relationship flags and a human-readable label."""
    canonical = str(canonical_hash or "")
    prepared = str(prepared_hash or "")
    executed = str(executed_hash or "")

    prepared_matches_canonical = bool(canonical and prepared and canonical == prepared)
    prepared_parameterized_from_canonical = bool(
        canonical and prepared and canonical != prepared
    )
    executed_matches_prepared = bool(prepared and executed and prepared == executed)
    executed_modified_after_preparation = bool(
        prepared and executed and prepared != executed
    )

    if executed and prepared and executed == prepared:
        if prepared == canonical:
            label = "executed_matches_canonical"
        else:
            label = "executed_matches_prepared"
    elif executed and prepared and executed != prepared:
        label = "executed_modified_after_preparation"
    elif prepared and canonical and prepared != canonical:
        label = "prepared_parameterized_from_canonical"
    elif prepared and canonical and prepared == canonical:
        label = "prepared_matches_canonical"
    else:
        label = "unknown_relationship"

    return {
        "prepared_matches_canonical": prepared_matches_canonical,
        "prepared_parameterized_from_canonical": prepared_parameterized_from_canonical,
        "executed_matches_prepared": executed_matches_prepared,
        "executed_modified_after_preparation": executed_modified_after_preparation,
        "relationship": label,
        "canonical_workflow_hash": canonical,
        "prepared_workflow_hash": prepared,
        "executed_workflow_hash": executed,
    }
