#!/usr/bin/env python3
"""AI Studio project/workspace manifests and active-project state."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_MANIFEST_VERSION = "1.0.0"
ACTIVE_PROJECT_SETTINGS = "settings/active_project.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "project"


@dataclass
class ProjectManifest:
    project_id: str
    slug: str
    display_name: str
    description: str = ""
    created_at: str = ""
    updated_at: str = ""
    default_workflow: str = ""
    preferred_models: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    outputs_dir: str = ""
    manifest_version: str = PROJECT_MANIFEST_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectManifest:
        return cls(
            project_id=str(data.get("project_id") or ""),
            slug=str(data.get("slug") or ""),
            display_name=str(data.get("display_name") or ""),
            description=str(data.get("description") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            default_workflow=str(data.get("default_workflow") or ""),
            preferred_models=list(data.get("preferred_models") or []),
            tags=list(data.get("tags") or []),
            outputs_dir=str(data.get("outputs_dir") or ""),
            manifest_version=str(data.get("manifest_version") or PROJECT_MANIFEST_VERSION),
        )


def validate_manifest(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("project_id", "slug", "display_name", "created_at", "outputs_dir"):
        if not str(data.get(key) or "").strip():
            errors.append(f"Missing required field: {key}")
    slug = str(data.get("slug") or "")
    if slug and slug != slugify(slug):
        errors.append(f"Invalid slug format: {slug}")
    return errors


class ProjectWorkspace:
    """Drive-backed project workspace under AI_Studio/projects/."""

    def __init__(self, drive_root: Path) -> None:
        self.drive_root = drive_root
        self.projects_root = drive_root / "projects"
        self.settings_dir = drive_root / "settings"

    def project_dir(self, slug: str) -> Path:
        return self.projects_root / slug

    def manifest_path(self, slug: str) -> Path:
        return self.project_dir(slug) / "project.json"

    def active_project_path(self) -> Path:
        return self.settings_dir / "active_project.json"

    def list_projects(self) -> list[ProjectManifest]:
        if not self.projects_root.is_dir():
            return []
        manifests: list[ProjectManifest] = []
        for child in sorted(self.projects_root.iterdir()):
            if not child.is_dir():
                continue
            manifest_file = child / "project.json"
            if not manifest_file.is_file():
                continue
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                manifests.append(ProjectManifest.from_dict(data))
            except (OSError, json.JSONDecodeError):
                continue
        return manifests

    def load_project(self, slug: str) -> ProjectManifest | None:
        path = self.manifest_path(slug)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ProjectManifest.from_dict(data)

    def create_project(
        self,
        *,
        display_name: str,
        slug: str | None = None,
        description: str = "",
        default_workflow: str = "",
        preferred_models: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> ProjectManifest:
        chosen_slug = slugify(slug or display_name)
        project_dir = self.project_dir(chosen_slug)
        if project_dir.exists():
            raise FileExistsError(f"Project slug already exists: {chosen_slug}")

        now = utc_now()
        outputs_dir = str(project_dir / "outputs")
        manifest = ProjectManifest(
            project_id=str(uuid.uuid4()),
            slug=chosen_slug,
            display_name=display_name,
            description=description,
            created_at=now,
            updated_at=now,
            default_workflow=default_workflow,
            preferred_models=list(preferred_models or []),
            tags=list(tags or []),
            outputs_dir=outputs_dir,
        )
        errors = validate_manifest(manifest.to_dict())
        if errors:
            raise ValueError("; ".join(errors))

        for sub in ("inputs", "masks", "references", "outputs", "workflows", "metadata"):
            (project_dir / sub).mkdir(parents=True, exist_ok=True)
        self.manifest_path(chosen_slug).write_text(
            json.dumps(manifest.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest

    def set_active_project(self, slug: str | None) -> dict[str, Any]:
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        if slug is None:
            path = self.active_project_path()
            if path.is_file():
                path.unlink()
            return {"active_project": None}
        manifest = self.load_project(slug)
        if manifest is None:
            raise FileNotFoundError(f"Unknown project slug: {slug}")
        payload = {"slug": manifest.slug, "project_id": manifest.project_id, "updated_at": utc_now()}
        self.active_project_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return payload

    def get_active_project(self) -> ProjectManifest | None:
        path = self.active_project_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        slug = str(data.get("slug") or "")
        if not slug:
            return None
        return self.load_project(slug)
