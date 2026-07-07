#!/usr/bin/env python3
"""In-memory runtime state for AI Studio orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class RuntimeState:
    """Snapshot of runtime session metadata (not auto-persisted yet)."""

    platform_version: str = "0.2.0"
    environment: str = "unknown"
    last_runtime: str | None = None
    last_launch_mode: str | None = None
    last_workflow: str | None = None
    installed_models: list[str] = field(default_factory=list)
    installed_nodes: list[str] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)

    def touch_runtime(self, environment: str | None = None) -> None:
        self.last_runtime = _utc_now_iso()
        if environment:
            self.environment = environment

    def record_launch(self, mode: str, workflow: str | None = None) -> None:
        self.last_launch_mode = mode
        if workflow:
            self.last_workflow = workflow
        self.touch_runtime()

    def update_installed_models(self, names: list[str]) -> None:
        self.installed_models = sorted(set(names))

    def update_installed_nodes(self, names: list[str]) -> None:
        self.installed_nodes = sorted(set(names))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeState:
        return cls(
            platform_version=data.get("platform_version", "0.2.0"),
            environment=data.get("environment", "unknown"),
            last_runtime=data.get("last_runtime"),
            last_launch_mode=data.get("last_launch_mode"),
            last_workflow=data.get("last_workflow"),
            installed_models=list(data.get("installed_models", [])),
            installed_nodes=list(data.get("installed_nodes", [])),
            notes=dict(data.get("notes", {})),
        )
