#!/usr/bin/env python3
"""Helpers for interpreting node_registry.json entries."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def is_node_required(entry: dict[str, Any]) -> bool:
    return "all" in entry.get("required_for", []) or entry.get("install_mode") == "required"


def node_folder_name(entry: dict[str, Any]) -> str:
    return entry.get("folder_name") or entry["name"]


def inspect_node_path(path: Path) -> str:
    if not path.exists():
        return "missing"
    if not path.is_dir():
        return "invalid"
    if (path / ".git").is_dir():
        return "installed"
    return "present"


def evaluate_required_nodes(
    required_node_names: list[str],
    registry_entries: list[dict[str, Any]],
    custom_nodes_dir: Path,
) -> dict[str, list[str]]:
    registry_map = {entry["name"]: entry for entry in registry_entries}
    missing_registration: list[str] = []
    uninstalled: list[str] = []

    for node_name in required_node_names:
        entry = registry_map.get(node_name)
        if not entry:
            missing_registration.append(node_name)
            continue
        target = custom_nodes_dir / node_folder_name(entry)
        if inspect_node_path(target) not in {"installed", "present"}:
            uninstalled.append(node_name)

    return {
        "missing_registration": missing_registration,
        "uninstalled": uninstalled,
    }


def summarize_node_installation(
    entries: list[dict[str, Any]],
    custom_nodes_dir: Path,
) -> dict[str, Any]:
    installed: list[str] = []
    missing_required: list[str] = []
    missing_optional: list[str] = []

    for entry in entries:
        name = entry["name"]
        target = custom_nodes_dir / node_folder_name(entry)
        state = inspect_node_path(target)
        required = is_node_required(entry)

        if state in {"installed", "present"}:
            installed.append(name)
        elif required:
            missing_required.append(name)
        else:
            missing_optional.append(name)

    return {
        "installed": installed,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "custom_nodes_dir": str(custom_nodes_dir),
        "total_registered": len(entries),
        "core_ready": len(missing_required) == 0,
    }
