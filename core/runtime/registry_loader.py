#!/usr/bin/env python3
"""Load all JSON manifests under configs/ into structured objects."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in (current, *current.parents):
        if (path / "README.md").is_file() and (path / "configs").is_dir():
            return path
    raise FileNotFoundError(
        "Could not locate AI Studio Colab repository root. "
        "Run from inside the cloned repository."
    )


@dataclass(frozen=True)
class RegistryBundle:
    """Strongly typed view of known registries plus raw manifest access."""

    repo_root: Path
    paths: dict[str, Any]
    repo_relative: dict[str, str]
    models: list[dict[str, Any]]
    nodes: list[dict[str, Any]]
    presets: list[dict[str, Any]]
    workflows: list[dict[str, Any]]
    assets: list[dict[str, Any]]
    capabilities: list[dict[str, Any]]
    manifests: dict[str, dict[str, Any]] = field(default_factory=dict)

    def path(self, key: str) -> Path:
        value = self.paths.get(key)
        if not value:
            raise KeyError(f"Unknown path key: {key}")
        return Path(value)

    def repo_path(self, key: str) -> Path:
        rel = self.repo_relative.get(key, key)
        return self.repo_root / rel

    def get_manifest(self, relative_path: str) -> dict[str, Any]:
        if relative_path not in self.manifests:
            raise KeyError(f"Manifest not loaded: {relative_path}")
        return self.manifests[relative_path]


class RegistryLoader:
    """Discover and load JSON manifests from configs/."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = (repo_root or find_repo_root()).resolve()

    def discover_manifest_paths(self) -> list[Path]:
        configs_dir = self.repo_root / "configs"
        if not configs_dir.is_dir():
            raise FileNotFoundError(f"configs/ not found under {self.repo_root}")
        return sorted(configs_dir.rglob("*.json"))

    def load_all(self) -> RegistryBundle:
        manifests: dict[str, dict[str, Any]] = {}
        for path in self.discover_manifest_paths():
            rel = path.relative_to(self.repo_root).as_posix()
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError(f"{rel}: manifest root must be a JSON object")
            manifests[rel] = data

        paths_data = manifests.get("configs/paths/colab_paths.json", {})
        models_data = manifests.get("configs/models/model_registry.json", {})
        nodes_data = manifests.get("configs/nodes/node_registry.json", {})
        presets_data = manifests.get("configs/presets/default_generation_presets.json", {})
        workflows_data = manifests.get("configs/workflows/workflow_registry.json", {})
        assets_data = manifests.get("configs/assets/asset_registry.json", {})
        capabilities_data = manifests.get("configs/capabilities/capability_registry.json", {})

        return RegistryBundle(
            repo_root=self.repo_root,
            paths=paths_data.get("paths", {}),
            repo_relative=paths_data.get("repo_relative", {}),
            models=_as_list(models_data.get("models"), "models"),
            nodes=_as_list(nodes_data.get("nodes"), "nodes"),
            presets=_as_list(presets_data.get("presets"), "presets"),
            workflows=_as_list(workflows_data.get("workflows"), "workflows"),
            assets=_as_list(assets_data.get("assets"), "assets"),
            capabilities=_as_list(capabilities_data.get("capabilities"), "capabilities"),
            manifests=manifests,
        )


def _as_list(value: Any, label: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Expected list for {label}")
    return value
