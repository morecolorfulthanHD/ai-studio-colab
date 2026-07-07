#!/usr/bin/env python3
"""Unified asset registry manager for AI Studio."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .registry_loader import RegistryBundle, RegistryLoader, find_repo_root

ASSET_REGISTRY_PATH = "configs/assets/asset_registry.json"


@dataclass
class AssetRecord:
    """Single asset with detected presence."""

    id: str
    name: str
    asset_type: str
    category: str
    scope: str
    engine: str
    intended_path: str
    runtime_path: str | None
    required_for: list[str]
    registry_status: str
    detected_status: str
    present: bool
    source_type: str = ""
    source_url: str = ""
    license_notes: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssetSummary:
    total: int = 0
    present: int = 0
    missing: int = 0
    planned: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    by_scope: dict[str, int] = field(default_factory=dict)
    by_engine: dict[str, int] = field(default_factory=dict)
    required_missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AssetManager:
    """Load and query the unified asset registry."""

    def __init__(self, bundle: RegistryBundle | None = None, repo_root: Path | None = None) -> None:
        if bundle is not None:
            self._bundle = bundle
            self.repo_root = bundle.repo_root
        else:
            self.repo_root = (repo_root or find_repo_root()).resolve()
            self._bundle = RegistryLoader(self.repo_root).load_all()
        self._assets = self._load_assets()
        self._records = [self._build_record(entry) for entry in self._assets]

    def _load_assets(self) -> list[dict[str, Any]]:
        data = self._bundle.get_manifest(ASSET_REGISTRY_PATH)
        assets = data.get("assets", [])
        if not isinstance(assets, list):
            raise ValueError(f"{ASSET_REGISTRY_PATH}: 'assets' must be a list")
        return assets

    @staticmethod
    def _path_present(path: Path) -> bool:
        if path.is_file():
            return True
        if path.is_dir():
            try:
                return any(path.iterdir())
            except OSError:
                return False
        return False

    def _resolve_paths(self, entry: dict[str, Any]) -> list[Path]:
        paths: list[Path] = []
        intended = entry.get("intended_path")
        if intended:
            paths.append(self.repo_root / intended)
        runtime = entry.get("runtime_path")
        if runtime:
            paths.append(Path(runtime))
        return paths

    def _detect_presence(self, entry: dict[str, Any]) -> tuple[bool, str]:
        paths = self._resolve_paths(entry)
        if paths and any(self._path_present(p) for p in paths):
            return True, "installed"
        registry_status = entry.get("status", "planned")
        if registry_status == "active":
            return False, "missing"
        if registry_status == "missing":
            return False, "missing"
        return False, "planned"

    def _build_record(self, entry: dict[str, Any]) -> AssetRecord:
        present, detected = self._detect_presence(entry)
        return AssetRecord(
            id=entry["id"],
            name=entry["name"],
            asset_type=entry["asset_type"],
            category=entry.get("category", ""),
            scope=entry.get("scope", "shared"),
            engine=entry.get("engine", "shared"),
            intended_path=entry.get("intended_path", ""),
            runtime_path=entry.get("runtime_path"),
            required_for=list(entry.get("required_for", [])),
            registry_status=entry.get("status", "planned"),
            detected_status=detected,
            present=present,
            source_type=entry.get("source_type", ""),
            source_url=entry.get("source_url", ""),
            license_notes=entry.get("license_notes", ""),
            notes=entry.get("notes", ""),
        )

    @property
    def assets(self) -> list[AssetRecord]:
        return list(self._records)

    def list_assets(self) -> list[AssetRecord]:
        return self.assets

    def get_asset(self, asset_id: str) -> AssetRecord | None:
        for record in self._records:
            if record.id == asset_id:
                return record
        return None

    def group_by(self, key: str) -> dict[str, list[AssetRecord]]:
        grouped: dict[str, list[AssetRecord]] = defaultdict(list)
        for record in self._records:
            value = getattr(record, key, "unknown")
            grouped[str(value)].append(record)
        return dict(grouped)

    def assets_for_workflow(self, workflow_id: str) -> list[AssetRecord]:
        return [
            record
            for record in self._records
            if workflow_id in record.required_for
        ]

    def missing_required(self, workflow_id: str | None = None) -> list[AssetRecord]:
        if workflow_id:
            candidates = self.assets_for_workflow(workflow_id)
        else:
            candidates = [r for r in self._records if r.required_for]
        return [r for r in candidates if not r.present and r.registry_status in {"active", "missing"}]

    def summary(self, workflow_id: str | None = None) -> AssetSummary:
        records = self.assets_for_workflow(workflow_id) if workflow_id else self._records
        summary = AssetSummary(total=len(records))

        for record in records:
            summary.by_type[record.asset_type] = summary.by_type.get(record.asset_type, 0) + 1
            summary.by_status[record.detected_status] = summary.by_status.get(record.detected_status, 0) + 1
            summary.by_scope[record.scope] = summary.by_scope.get(record.scope, 0) + 1
            summary.by_engine[record.engine] = summary.by_engine.get(record.engine, 0) + 1
            if record.present:
                summary.present += 1
            elif record.detected_status == "missing":
                summary.missing += 1
            else:
                summary.planned += 1

        summary.required_missing = [r.id for r in self.missing_required(workflow_id)]
        return summary

    def to_dict(self, workflow_id: str | None = None) -> dict[str, Any]:
        records = self.assets_for_workflow(workflow_id) if workflow_id else self._records
        return {
            "summary": self.summary(workflow_id).to_dict(),
            "assets": [r.to_dict() for r in records],
        }

    def print_summary(self, workflow_id: str | None = None) -> None:
        summary = self.summary(workflow_id)
        title = f"Workflow: {workflow_id}" if workflow_id else "All assets"
        print(f"AI Studio — Asset Summary ({title})")
        print("=" * 40)
        print(f"Total:   {summary.total}")
        print(f"Present: {summary.present}")
        print(f"Missing: {summary.missing}")
        print(f"Planned: {summary.planned}")
        if summary.required_missing:
            print(f"Required missing: {', '.join(summary.required_missing)}")
        print("\nBy type:")
        for key in sorted(summary.by_type):
            print(f"  {key}: {summary.by_type[key]}")
        print("\nBy detected status:")
        for key in sorted(summary.by_status):
            print(f"  {key}: {summary.by_status[key]}")


def main() -> int:
    manager = AssetManager()
    manager.print_summary()
    print("\nRESULT: OK — asset manager loaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
