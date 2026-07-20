#!/usr/bin/env python3
"""AI Studio project/workspace manifests, lifecycle, and active-project state.

Operating model
---------------
No active project (global-only):
  verified outputs -> AI_Studio/outputs/

Active project:
  verified outputs -> AI_Studio/outputs/  (canonical)
  mirrored copy    -> AI_Studio/projects/<slug>/outputs/

Active-project selection persists in AI_Studio/settings/active_project.json
across Colab runtime restarts until deactivated, archived, deleted, or switched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_SCHEMA_VERSION = 2
LEGACY_MANIFEST_VERSION = "1.0.0"
ACTIVE_PROJECT_SETTINGS = "settings/active_project.json"
LIFECYCLE_LEDGER_NAME = "project_lifecycle.jsonl"
RESERVED_SLUGS = frozenset(
    {
        "",
        ".",
        "..",
        "active",
        "archived",
        "global",
        "outputs",
        "settings",
        "projects",
        "logs",
        "models",
        "workflows",
        "inputs",
        "tmp",
        "temp",
    }
)
PROJECT_SUBDIRS = ("inputs", "masks", "references", "outputs", "workflows", "metadata")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "project"


def validate_slug(slug: str) -> list[str]:
    errors: list[str] = []
    if not slug:
        errors.append("Slug is empty.")
        return errors
    if slug in RESERVED_SLUGS:
        errors.append(f"Reserved project slug: {slug}")
    if slug != slugify(slug):
        errors.append(f"Invalid slug format: {slug}")
    if ".." in slug or "/" in slug or "\\" in slug:
        errors.append(f"Unsafe slug path characters: {slug}")
    return errors


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _dir_size_bytes(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file() and not child.is_symlink():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def _count_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for child in path.rglob("*") if child.is_file() and not child.is_symlink())


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
    # Package 4.6 schema fields
    schema_version: int = PROJECT_SCHEMA_VERSION
    status: str = "inactive"  # active | inactive | archived
    archived: bool = False
    archived_timestamp: str = ""
    last_generation_timestamp: str = ""
    generation_count: int = 0
    storage_bytes: int = 0
    previous_slugs: list[str] = field(default_factory=list)
    # Legacy Package 4.5 field retained for compatibility.
    manifest_version: str = LEGACY_MANIFEST_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectManifest":
        """Load Package 4.5 or 4.6 manifests with safe defaults (non-destructive)."""
        schema = data.get("schema_version")
        try:
            schema_version = int(schema) if schema is not None else 1
        except (TypeError, ValueError):
            schema_version = 1
        archived = bool(data.get("archived", False))
        status = str(data.get("status") or "").strip().lower()
        if not status:
            status = "archived" if archived else "inactive"
        if archived:
            status = "archived"
        name = str(data.get("display_name") or data.get("name") or "")
        return cls(
            project_id=str(data.get("project_id") or ""),
            slug=str(data.get("slug") or ""),
            display_name=name,
            description=str(data.get("description") or ""),
            created_at=str(data.get("created_at") or data.get("created_timestamp") or ""),
            updated_at=str(data.get("updated_at") or data.get("updated_timestamp") or ""),
            default_workflow=str(data.get("default_workflow") or ""),
            preferred_models=list(data.get("preferred_models") or []),
            tags=list(data.get("tags") or []),
            outputs_dir=str(data.get("outputs_dir") or ""),
            schema_version=max(schema_version, 1),
            status=status,
            archived=archived,
            archived_timestamp=str(data.get("archived_timestamp") or ""),
            last_generation_timestamp=str(data.get("last_generation_timestamp") or ""),
            generation_count=int(data.get("generation_count") or 0),
            storage_bytes=int(data.get("storage_bytes") or 0),
            previous_slugs=list(data.get("previous_slugs") or []),
            manifest_version=str(data.get("manifest_version") or LEGACY_MANIFEST_VERSION),
        )

    @property
    def name(self) -> str:
        return self.display_name

    def is_archived(self) -> bool:
        return self.archived or self.status == "archived"

    def can_receive_mirrors(self) -> bool:
        return not self.is_archived()


def validate_manifest(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("project_id", "slug", "display_name", "created_at", "outputs_dir"):
        if not str(data.get(key) or "").strip():
            errors.append(f"Missing required field: {key}")
    errors.extend(validate_slug(str(data.get("slug") or "")))
    status = str(data.get("status") or "inactive")
    if status not in {"active", "inactive", "archived"}:
        errors.append(f"Invalid status: {status}")
    return errors


@dataclass
class ProjectLifecycleRecord:
    timestamp: str
    action: str
    project_id: str
    name: str
    slug: str
    result: str
    previous_slug: str = ""
    active_project_before: str = ""
    active_project_after: str = ""
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectLifecycleLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: ProjectLifecycleRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows


class ProjectWorkspace:
    """Drive-backed project workspace under AI_Studio/projects/."""

    def __init__(self, drive_root: Path) -> None:
        self.drive_root = Path(drive_root)
        self.projects_root = self.drive_root / "projects"
        self.settings_dir = self.drive_root / "settings"
        self.logs_dir = self.drive_root / "logs"
        self.lifecycle = ProjectLifecycleLedger(self.logs_dir / LIFECYCLE_LEDGER_NAME)

    def project_dir(self, slug: str) -> Path:
        return self.projects_root / slug

    def manifest_path(self, slug: str) -> Path:
        return self.project_dir(slug) / "project.json"

    def active_project_path(self) -> Path:
        return self.settings_dir / "active_project.json"

    def _write_manifest(self, manifest: ProjectManifest) -> None:
        errors = validate_manifest(manifest.to_dict())
        if errors:
            raise ValueError("; ".join(errors))
        _atomic_write_json(self.manifest_path(manifest.slug), manifest.to_dict())

    def _active_slug(self) -> str:
        path = self.active_project_path()
        if not path.is_file():
            return ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        return str(data.get("slug") or "")

    def _record_lifecycle(
        self,
        *,
        action: str,
        manifest: ProjectManifest | None,
        result: str,
        previous_slug: str = "",
        active_before: str = "",
        active_after: str = "",
        messages: list[str] | None = None,
    ) -> None:
        record = ProjectLifecycleRecord(
            timestamp=utc_now(),
            action=action,
            project_id=manifest.project_id if manifest else "",
            name=manifest.display_name if manifest else "",
            slug=manifest.slug if manifest else "",
            previous_slug=previous_slug,
            result=result,
            active_project_before=active_before,
            active_project_after=active_after,
            messages=list(messages or []),
        )
        self.lifecycle.append(record)

    def list_projects(self, *, include_archived: bool = False) -> list[ProjectManifest]:
        if not self.projects_root.is_dir():
            return []
        active_slug = self._active_slug()
        manifests: list[ProjectManifest] = []
        for child in sorted(self.projects_root.iterdir()):
            if not child.is_dir() or child.is_symlink():
                continue
            manifest_file = child / "project.json"
            if not manifest_file.is_file():
                continue
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("root must be object")
                manifest = ProjectManifest.from_dict(data)
                if not manifest.slug:
                    manifest.slug = child.name
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                # Report clearly; do not overwrite malformed metadata.
                print(f"WARNING: Malformed project metadata for {child.name}: {exc}", file=sys.stderr)
                continue
            if manifest.is_archived() and not include_archived:
                continue
            # Reflect active selection in status for display.
            if active_slug and manifest.slug == active_slug and not manifest.is_archived():
                manifest.status = "active"
            elif not manifest.is_archived() and manifest.status == "active":
                manifest.status = "inactive"
            manifests.append(manifest)

        # Active first, then recently updated, then name (stable sorts).
        manifests.sort(key=lambda item: (item.display_name or item.slug).lower())
        manifests.sort(key=lambda item: item.updated_at or item.created_at or "", reverse=True)
        manifests.sort(key=lambda item: 0 if (active_slug and item.slug == active_slug) else 1)
        return manifests

    def load_project(self, slug: str) -> ProjectManifest | None:
        path = self.manifest_path(slug)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ProjectManifest.from_dict(data)

    def resolve_project(self, identifier: str) -> ProjectManifest:
        """Resolve by slug or project_id. Raises FileNotFoundError / ValueError."""
        needle = str(identifier or "").strip()
        if not needle:
            raise ValueError("Project identifier is empty.")
        by_slug = self.load_project(needle)
        if by_slug is not None:
            return by_slug
        matches = [
            project
            for project in self.list_projects(include_archived=True)
            if project.project_id == needle
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous project_id matches multiple projects: {needle}")
        raise FileNotFoundError(f"Unknown project: {needle}")

    def create_project(
        self,
        *,
        display_name: str,
        slug: str | None = None,
        description: str = "",
        default_workflow: str = "",
        preferred_models: list[str] | None = None,
        tags: list[str] | None = None,
        set_active: bool = False,
    ) -> ProjectManifest:
        chosen_slug = slugify(slug or display_name)
        errors = validate_slug(chosen_slug)
        if errors:
            raise ValueError("; ".join(errors))
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
            schema_version=PROJECT_SCHEMA_VERSION,
            status="inactive",
            archived=False,
        )
        for sub in PROJECT_SUBDIRS:
            (project_dir / sub).mkdir(parents=True, exist_ok=True)
        self._write_manifest(manifest)
        active_before = self._active_slug()
        active_after = active_before
        if set_active:
            self.set_active_project(chosen_slug)
            active_after = chosen_slug
            manifest.status = "active"
        self._record_lifecycle(
            action="create",
            manifest=manifest,
            result="ok",
            active_before=active_before,
            active_after=active_after,
        )
        return manifest

    def set_active_project(self, slug: str | None) -> dict[str, Any]:
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        active_before = self._active_slug()
        if slug is None:
            path = self.active_project_path()
            if path.is_file():
                path.unlink()
            previous = self.load_project(active_before) if active_before else None
            if previous is not None and not previous.is_archived():
                previous.status = "inactive"
                previous.updated_at = utc_now()
                self._write_manifest(previous)
            self._record_lifecycle(
                action="deactivate",
                manifest=previous,
                result="ok" if active_before else "idempotent",
                active_before=active_before,
                active_after="",
                messages=["No active project; already in global mode."] if not active_before else [],
            )
            return {"active_project": None, "mode": "global"}

        manifest = self.resolve_project(slug)
        if manifest.is_archived():
            raise ValueError(f"Cannot activate archived project: {manifest.slug}")
        # Clear previous active project's status.
        if active_before and active_before != manifest.slug:
            previous = self.load_project(active_before)
            if previous is not None and not previous.is_archived():
                previous.status = "inactive"
                previous.updated_at = utc_now()
                self._write_manifest(previous)
        manifest.status = "active"
        manifest.updated_at = utc_now()
        self._write_manifest(manifest)
        payload = {
            "slug": manifest.slug,
            "project_id": manifest.project_id,
            "updated_at": utc_now(),
        }
        _atomic_write_json(self.active_project_path(), payload)
        self._record_lifecycle(
            action="activate",
            manifest=manifest,
            result="ok",
            active_before=active_before,
            active_after=manifest.slug,
        )
        return payload

    def deactivate_active_project(self) -> dict[str, Any]:
        return self.set_active_project(None)

    def get_active_project(self) -> ProjectManifest | None:
        path = self.active_project_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        slug = str(data.get("slug") or "")
        project_id = str(data.get("project_id") or "")
        if not slug and not project_id:
            return None
        try:
            if slug:
                manifest = self.load_project(slug)
            else:
                manifest = None
            if manifest is None and project_id:
                manifest = self.resolve_project(project_id)
        except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError):
            # Active pointer is stale (deleted/moved). Clear without raising.
            path.unlink(missing_ok=True)
            return None
        if manifest is None:
            path.unlink(missing_ok=True)
            return None
        if manifest.is_archived():
            path.unlink(missing_ok=True)
            return None
        manifest.status = "active"
        return manifest

    def current_mode(self) -> str:
        active = self.get_active_project()
        if active is None:
            return "Global outputs only"
        return f"Project — {active.slug}"

    def rename_project(
        self,
        identifier: str,
        *,
        display_name: str | None = None,
        new_slug: str | None = None,
    ) -> ProjectManifest:
        manifest = self.resolve_project(identifier)
        active_before = self._active_slug()
        previous_slug = manifest.slug
        changed = False

        if display_name is not None and display_name.strip() and display_name != manifest.display_name:
            manifest.display_name = display_name.strip()
            changed = True

        if new_slug is not None and new_slug.strip() and slugify(new_slug) != manifest.slug:
            dest_slug = slugify(new_slug)
            errors = validate_slug(dest_slug)
            if errors:
                raise ValueError("; ".join(errors))
            source_dir = self.project_dir(manifest.slug)
            dest_dir = self.project_dir(dest_slug)
            if dest_dir.exists():
                raise FileExistsError(f"Destination project slug already exists: {dest_slug}")
            if not source_dir.is_dir():
                raise FileNotFoundError(f"Project directory missing: {source_dir}")
            # Atomic-ish rename: move folder first; only then update metadata.
            try:
                source_dir.rename(dest_dir)
            except OSError as exc:
                raise RuntimeError(
                    f"Unable to rename project folder safely ({source_dir} -> {dest_dir}): {exc}"
                ) from exc
            if previous_slug not in manifest.previous_slugs:
                manifest.previous_slugs.append(previous_slug)
            manifest.slug = dest_slug
            manifest.outputs_dir = str(dest_dir / "outputs")
            changed = True

        if not changed:
            return manifest

        manifest.updated_at = utc_now()
        try:
            self._write_manifest(manifest)
        except Exception:
            # If slug renamed but metadata write fails, attempt rollback of folder move.
            if manifest.slug != previous_slug:
                try:
                    self.project_dir(manifest.slug).rename(self.project_dir(previous_slug))
                except OSError:
                    pass
            raise

        if active_before == previous_slug:
            _atomic_write_json(
                self.active_project_path(),
                {
                    "slug": manifest.slug,
                    "project_id": manifest.project_id,
                    "updated_at": utc_now(),
                },
            )
            manifest.status = "active"

        self._record_lifecycle(
            action="rename",
            manifest=manifest,
            result="ok",
            previous_slug=previous_slug,
            active_before=active_before,
            active_after=self._active_slug(),
        )
        return manifest

    def archive_project(self, identifier: str) -> ProjectManifest:
        manifest = self.resolve_project(identifier)
        active_before = self._active_slug()
        if manifest.is_archived():
            return manifest
        was_active = active_before == manifest.slug
        if was_active:
            self.set_active_project(None)
        manifest.archived = True
        manifest.status = "archived"
        manifest.archived_timestamp = utc_now()
        manifest.updated_at = utc_now()
        self._write_manifest(manifest)
        self._record_lifecycle(
            action="archive",
            manifest=manifest,
            result="ok",
            active_before=active_before,
            active_after=self._active_slug(),
            messages=["Active project archived; switched to global-only mode."] if was_active else [],
        )
        return manifest

    def restore_project(self, identifier: str, *, set_active: bool = False) -> ProjectManifest:
        manifest = self.resolve_project(identifier)
        active_before = self._active_slug()
        manifest.archived = False
        manifest.status = "inactive"
        manifest.archived_timestamp = ""
        manifest.updated_at = utc_now()
        self._write_manifest(manifest)
        if set_active:
            self.set_active_project(manifest.slug)
            manifest.status = "active"
        self._record_lifecycle(
            action="restore",
            manifest=manifest,
            result="ok",
            active_before=active_before,
            active_after=self._active_slug(),
        )
        return manifest

    def validate_project_deletion_path(self, slug: str) -> Path:
        """Ensure deletion target is strictly inside AI_Studio/projects/<slug>/."""
        errors = validate_slug(slug)
        if errors:
            raise ValueError("; ".join(errors))
        projects_root = self.projects_root.resolve()
        target = (self.projects_root / slug).resolve()
        try:
            target.relative_to(projects_root)
        except ValueError as exc:
            raise ValueError(f"Deletion path escapes projects root: {target}") from exc
        if target == projects_root:
            raise ValueError("Refusing to delete projects root.")
        if target.parent != projects_root:
            raise ValueError(f"Deletion path must be a direct project child: {target}")
        if target.is_symlink() or self.projects_root.is_symlink():
            raise ValueError("Refusing to delete through symlink project paths.")
        return target

    def delete_project(
        self,
        identifier: str,
        *,
        confirm_slug: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        manifest = self.resolve_project(identifier)
        if not dry_run and confirm_slug != manifest.slug:
            raise PermissionError(
                f"Confirmation slug mismatch: expected {manifest.slug!r}, got {confirm_slug!r}"
            )
        target = self.validate_project_deletion_path(manifest.slug)
        active_before = self._active_slug()
        file_count = _count_files(target) if target.exists() else 0
        dir_count = (
            sum(1 for child in target.rglob("*") if child.is_dir() and not child.is_symlink())
            if target.exists()
            else 0
        )
        payload = {
            "project_id": manifest.project_id,
            "slug": manifest.slug,
            "name": manifest.display_name,
            "path": str(target),
            "dry_run": dry_run,
            "files": file_count,
            "directories": dir_count,
            "global_outputs_preserved": True,
            "evidence_preserved": True,
        }
        if dry_run:
            payload["result"] = "dry_run"
            return payload

        if active_before == manifest.slug:
            self.set_active_project(None)

        self._record_lifecycle(
            action="delete",
            manifest=manifest,
            result="started",
            active_before=active_before,
            active_after=self._active_slug(),
        )
        if target.exists():
            shutil.rmtree(target)
        self._record_lifecycle(
            action="delete",
            manifest=manifest,
            result="ok",
            active_before=active_before,
            active_after=self._active_slug(),
            messages=[f"Deleted {file_count} files / {dir_count} directories under {target}"],
        )
        payload["result"] = "ok"
        return payload

    def migrate_project(self, slug: str, *, apply: bool = False) -> dict[str, Any]:
        path = self.manifest_path(slug)
        if not path.is_file():
            raise FileNotFoundError(f"Unknown project slug: {slug}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Malformed project metadata for {slug}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"Malformed project metadata for {slug}: root must be object")

        original = dict(raw)
        migrated = ProjectManifest.from_dict(raw)
        if not migrated.project_id:
            migrated.project_id = str(uuid.uuid4())
        if not migrated.created_at:
            migrated.created_at = utc_now()
        if not migrated.updated_at:
            migrated.updated_at = migrated.created_at
        if not migrated.outputs_dir:
            migrated.outputs_dir = str(self.project_dir(migrated.slug) / "outputs")
        migrated.schema_version = PROJECT_SCHEMA_VERSION
        if migrated.is_archived():
            migrated.status = "archived"
            migrated.archived = True
        elif migrated.slug == self._active_slug():
            migrated.status = "active"
        else:
            migrated.status = "inactive"
            migrated.archived = False

        changes: list[str] = []
        new_payload = migrated.to_dict()
        for key, value in new_payload.items():
            if original.get(key) != value:
                changes.append(key)

        result = {
            "slug": slug,
            "apply": apply,
            "changed_fields": changes,
            "before": original,
            "after": new_payload,
        }
        if apply and changes:
            self._write_manifest(migrated)
            for sub in PROJECT_SUBDIRS:
                (self.project_dir(migrated.slug) / sub).mkdir(parents=True, exist_ok=True)
            self._record_lifecycle(
                action="migrate",
                manifest=migrated,
                result="ok",
                active_before=self._active_slug(),
                active_after=self._active_slug(),
                messages=[f"Updated fields: {', '.join(changes)}"],
            )
        return result

    def migrate_all(self, *, apply: bool = False) -> list[dict[str, Any]]:
        if not self.projects_root.is_dir():
            return []
        results: list[dict[str, Any]] = []
        for child in sorted(self.projects_root.iterdir()):
            if not child.is_dir() or not (child / "project.json").is_file():
                continue
            try:
                results.append(self.migrate_project(child.name, apply=apply))
            except ValueError as exc:
                results.append({"slug": child.name, "apply": apply, "error": str(exc)})
        return results

    def compute_statistics(
        self,
        identifier: str,
        *,
        evidence_path: Path | None = None,
    ) -> dict[str, Any]:
        manifest = self.resolve_project(identifier)
        project_dir = self.project_dir(manifest.slug)
        outputs_dir = Path(manifest.outputs_dir) if manifest.outputs_dir else project_dir / "outputs"
        stats = {
            "project_id": manifest.project_id,
            "name": manifest.display_name,
            "slug": manifest.slug,
            "status": "active" if self._active_slug() == manifest.slug else manifest.status,
            "archived": manifest.is_archived(),
            "created_timestamp": manifest.created_at,
            "updated_timestamp": manifest.updated_at,
            "last_generation_timestamp": manifest.last_generation_timestamp,
            "input_count": _count_files(project_dir / "inputs"),
            "mask_count": _count_files(project_dir / "masks"),
            "reference_count": _count_files(project_dir / "references"),
            "workflow_count": _count_files(project_dir / "workflows"),
            "metadata_file_count": _count_files(project_dir / "metadata"),
            "project_output_count": _count_files(outputs_dir),
            "project_storage_bytes": _dir_size_bytes(project_dir),
            "project_output_storage_bytes": _dir_size_bytes(outputs_dir),
            "verified_generations": 0,
            "canonical_global_assets": 0,
            "capability_breakdown": {},
            "model_family_breakdown": {},
            "workflow_breakdown": {},
            "date_range": {"from": "", "to": ""},
            "missing_project_output_references": 0,
            "duplicate_content_count": 0,
        }
        if evidence_path is None:
            evidence_path = self.logs_dir / "generation_evidence.jsonl"
        if not evidence_path.is_file():
            return stats

        from .generation_history import collapse_generations

        generations = collapse_generations(
            evidence_path,
            project=manifest.slug,
            project_id=manifest.project_id,
            verified_only=True,
        )
        stats["verified_generations"] = len(generations)
        hashes: dict[str, int] = {}
        dates: list[str] = []
        for row in generations:
            capability = str(row.get("capability") or "unknown")
            family = str(row.get("model_family") or "unknown")
            workflow = str(row.get("workflow_identifier") or "unknown")
            stats["capability_breakdown"][capability] = stats["capability_breakdown"].get(capability, 0) + 1
            stats["model_family_breakdown"][family] = stats["model_family_breakdown"].get(family, 0) + 1
            stats["workflow_breakdown"][workflow] = stats["workflow_breakdown"].get(workflow, 0) + 1
            if row.get("drive_path"):
                stats["canonical_global_assets"] += 1
            project_path = str(row.get("project_output_path") or "")
            if project_path and not Path(project_path).is_file():
                stats["missing_project_output_references"] += 1
            digest = str(row.get("local_sha256") or row.get("drive_sha256") or "")
            if digest:
                hashes[digest] = hashes.get(digest, 0) + 1
            stamp = str(row.get("synchronized_timestamp") or row.get("created_timestamp") or "")
            if stamp:
                dates.append(stamp)
        stats["duplicate_content_count"] = sum(1 for count in hashes.values() if count > 1)
        if dates:
            stats["date_range"] = {"from": min(dates), "to": max(dates)}
            stats["last_generation_timestamp"] = max(dates)
        return stats
