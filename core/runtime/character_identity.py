#!/usr/bin/env python3
"""Platform-generic character identity records (Package 4.12).

Drive-backed first-class characters, separate from generation lineage.
No Zara-specific fields. One required SHA-verified primary face reference.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .generation_evidence_ledger import file_sha256

PACKAGE_VERSION = "4.12"
CHARACTER_ID_PREFIX = "char_"
CHARACTER_FILENAME = "character.json"
REFERENCES_SUBDIR = "references"
PRIMARY_FACE_FILENAME = "primary_face.png"
CHARACTERS_ROOT_NAME = "characters"

_CHARACTER_ID_RE = re.compile(
    r"^char_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class InvalidCharacterIdError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def characters_root(drive_root: Path) -> Path:
    return Path(drive_root) / CHARACTERS_ROOT_NAME


def normalize_character_id(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise InvalidCharacterIdError("ERROR: Character ID is required.")
    if _CHARACTER_ID_RE.fullmatch(text):
        return text.lower()
    # Accept bare UUID.
    bare = text
    if bare.lower().startswith("char_"):
        bare = bare[5:]
    try:
        value = uuid.UUID(bare)
    except ValueError as exc:
        raise InvalidCharacterIdError(
            "ERROR: Invalid character ID. Expected char_<uuid> or a UUID."
        ) from exc
    return f"{CHARACTER_ID_PREFIX}{value}"


def allocate_character_id() -> str:
    return f"{CHARACTER_ID_PREFIX}{uuid.uuid4()}"


@dataclass
class FaceReference:
    relative_path: str
    sha256: str
    original_filename: str = ""
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {k: v for k, v in payload.items() if v is not None and v != ""}


@dataclass
class CharacterRecord:
    character_id: str
    display_name: str
    created_at: str
    updated_at: str
    primary_face_ref: dict[str, Any]
    additional_refs: list[dict[str, Any]] = field(default_factory=list)
    project_slug: str | None = None
    package_version: str = PACKAGE_VERSION
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload.get("project_slug"):
            payload["project_slug"] = None
        return payload


@dataclass
class CharacterResult:
    ok: bool
    character: CharacterRecord | None = None
    character_dir: str = ""
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "character": self.character.to_dict() if self.character else None,
            "character_dir": self.character_dir,
            "messages": self.messages,
            "errors": self.errors,
        }


def character_dir(drive_root: Path, character_id: str) -> Path:
    cid = normalize_character_id(character_id)
    return characters_root(drive_root) / cid


def load_character(drive_root: Path, character_id: str) -> CharacterRecord | None:
    path = character_dir(drive_root, character_id) / CHARACTER_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return CharacterRecord(
            character_id=str(data.get("character_id") or ""),
            display_name=str(data.get("display_name") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            primary_face_ref=dict(data.get("primary_face_ref") or {}),
            additional_refs=list(data.get("additional_refs") or []),
            project_slug=(str(data["project_slug"]) if data.get("project_slug") else None),
            package_version=str(data.get("package_version") or PACKAGE_VERSION),
            notes=list(data.get("notes") or []),
        )
    except (TypeError, ValueError):
        return None


def list_characters(drive_root: Path) -> list[CharacterRecord]:
    root = characters_root(drive_root)
    if not root.is_dir():
        return []
    rows: list[CharacterRecord] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        record = load_character(drive_root, child.name)
        if record is not None:
            rows.append(record)
    return rows


def resolve_primary_face_path(drive_root: Path, record: CharacterRecord) -> Path | None:
    rel = str((record.primary_face_ref or {}).get("relative_path") or "").strip()
    if not rel or Path(rel).is_absolute():
        return None
    path = character_dir(drive_root, record.character_id) / rel
    return path if path.is_file() else None


def verify_character_face(drive_root: Path, record: CharacterRecord) -> tuple[bool, str]:
    expected = str((record.primary_face_ref or {}).get("sha256") or "").strip()
    if not expected:
        return False, "ERROR: Character primary face SHA256 is missing."
    path = resolve_primary_face_path(drive_root, record)
    if path is None:
        return False, "ERROR: Character primary face image is missing."
    actual = file_sha256(path)
    if actual != expected:
        return False, "ERROR: Character primary face SHA256 mismatch."
    return True, ""


def register_character(
    drive_root: Path,
    *,
    display_name: str,
    primary_face_image: Path,
    project_slug: str | None = None,
    character_id: str | None = None,
    dry_run: bool = False,
) -> CharacterResult:
    result = CharacterResult(ok=False)
    name = str(display_name or "").strip()
    if not name:
        result.errors.append("ERROR: display_name is required.")
        return result
    source = Path(primary_face_image)
    if not source.is_file():
        result.errors.append(f"ERROR: Primary face image not found: {source}")
        return result
    suffix = source.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        result.errors.append("ERROR: Primary face must be png/jpg/jpeg/webp.")
        return result

    cid = normalize_character_id(character_id) if character_id else allocate_character_id()
    dest_dir = character_dir(drive_root, cid)
    if dest_dir.exists() and (dest_dir / CHARACTER_FILENAME).is_file():
        result.errors.append(f"ERROR: Character already exists: {cid}")
        return result

    sha = file_sha256(source)
    face_rel = f"{REFERENCES_SUBDIR}/{PRIMARY_FACE_FILENAME}"
    now = utc_now()
    record = CharacterRecord(
        character_id=cid,
        display_name=name,
        created_at=now,
        updated_at=now,
        primary_face_ref=FaceReference(
            relative_path=face_rel,
            sha256=sha,
            original_filename=source.name,
        ).to_dict(),
        additional_refs=[],
        project_slug=(str(project_slug).strip() or None) if project_slug else None,
    )
    result.character = record
    result.character_dir = str(dest_dir)
    if dry_run:
        result.ok = True
        result.messages.append("Dry run: character would be registered (not written).")
        return result

    refs_dir = dest_dir / REFERENCES_SUBDIR
    refs_dir.mkdir(parents=True, exist_ok=True)
    dest_face = dest_dir / face_rel
    # Always store under the stable relative path name (bytes unchanged).
    shutil.copy2(source, dest_face)
    (dest_dir / CHARACTER_FILENAME).write_text(
        json.dumps(record.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    ok, err = verify_character_face(drive_root, record)
    if not ok:
        result.errors.append(err)
        shutil.rmtree(dest_dir, ignore_errors=True)
        return result
    result.ok = True
    result.messages.append(f"Registered character {cid}")
    result.messages.append(f"Primary face archived at {face_rel} sha256={sha}")
    return result
