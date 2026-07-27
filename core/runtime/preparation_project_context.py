#!/usr/bin/env python3
"""Resolve project context for workflow library preparation (Package 4.8.1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .project_workspace import ACTIVE_PROJECT_SETTINGS, ProjectManifest, ProjectWorkspace


@dataclass
class PreparationProjectContext:
    project: ProjectManifest | None
    mode: str  # "global" | "project"
    source: str  # "flag-global" | "flag-project" | "active-project" | "no-active"


def _read_active_pointer(drive_root: Path) -> dict[str, Any] | None:
    path = drive_root / ACTIVE_PROJECT_SETTINGS
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError(f"Malformed active project settings: {path}") from None
    if not isinstance(data, dict):
        raise ValueError(f"Malformed active project settings: {path}")
    slug = str(data.get("slug") or data.get("project_slug") or "").strip()
    project_id = str(data.get("project_id") or "").strip()
    if not slug and not project_id:
        return None
    return data


def resolve_preparation_project(
    drive_root: Path,
    *,
    use_global: bool = False,
    project_ref: str | None = None,
) -> PreparationProjectContext:
    """Resolve project for preparation.

    Rules:
    - --global → global mode
    - --project <slug-or-id> → explicit project (error if missing/archived)
    - neither → active project if set; else global
    - active pointer present but unresolvable → error (no silent global fallback)
    - --global and --project together → error (caller should check first)
    """
    workspace = ProjectWorkspace(drive_root)

    if use_global and project_ref:
        raise ValueError("Conflicting flags: use either --global or --project, not both.")

    if use_global:
        return PreparationProjectContext(project=None, mode="global", source="flag-global")

    if project_ref:
        ref = str(project_ref).strip()
        if not ref:
            raise ValueError("--project requires a project slug or id.")
        try:
            project = workspace.resolve_project(ref)
        except (FileNotFoundError, ValueError) as exc:
            raise ValueError(f"Project not found: {ref}") from exc
        if project.is_archived():
            raise ValueError(f"Project is archived and cannot receive preparations: {project.slug}")
        return PreparationProjectContext(project=project, mode="project", source="flag-project")

    pointer = _read_active_pointer(drive_root)
    if pointer is None:
        return PreparationProjectContext(project=None, mode="global", source="no-active")

    slug = str(pointer.get("slug") or pointer.get("project_slug") or "").strip()
    project_id = str(pointer.get("project_id") or "").strip()
    ref = slug or project_id
    try:
        project = workspace.resolve_project(ref)
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(
            f"Active project pointer exists ({ref}) but the project cannot be resolved. "
            "Fix or clear the active project before preparing. "
            f"Details: {exc}"
        ) from exc
    if project.is_archived():
        raise ValueError(
            f"Active project is archived and cannot receive preparations: {project.slug}"
        )
    return PreparationProjectContext(project=project, mode="project", source="active-project")
