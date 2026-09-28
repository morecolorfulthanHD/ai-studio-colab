#!/usr/bin/env python3
"""Architecture-aware Comfy/Full Launch dependency profiles (Package 4.12.3).

PATH C (ipadapter_plus_face_sdxl) uses CLIP NON-FaceID IP-Adapter Plus Face.
It must not require FaceID / InsightFace / InstantID / ReActor install probes.
Legacy FaceID-era probes remain available when no PATH C architecture is selected
(or when an explicit FaceID/investigation profile is requested).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .identity_architecture_plugin import (
    ARCHITECTURE_INSTANTID,
    ARCHITECTURE_IPADAPTER_PLUS_FACE,
)

# FaceID-era install/probe capabilities (not required by PATH C graph).
FACEID_ERA_CAPABILITIES = frozenset(
    {
        "faceid_python_deps",
        "faceid_runtime_bridge",
        "faceid_buffalo_bridge",
        "reactor_insightface_bridge",
    }
)

FORBIDDEN_FOR_PATH_C_LAUNCH = frozenset(
    {
        "faceid",
        "insightface",
        "antelope",
        "buffalo",
        "instantid",
        "reactor",
        "ipadapter_faceid",
    }
)


@dataclass(frozen=True)
class LaunchProfile:
    """Which optional install/probe steps Full Launch may run."""

    profile_id: str
    architecture_id: str | None
    require_faceid_python_deps: bool
    require_faceid_runtime_bridge: bool
    require_faceid_buffalo_bridge: bool
    require_reactor_insightface_bridge: bool
    notes: tuple[str, ...] = ()

    @property
    def skip_faceid_era_probes(self) -> bool:
        return not (
            self.require_faceid_python_deps
            or self.require_faceid_runtime_bridge
            or self.require_faceid_buffalo_bridge
            or self.require_reactor_insightface_bridge
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["skip_faceid_era_probes"] = self.skip_faceid_era_probes
        return data


def normalize_architecture_id(architecture_id: str | None) -> str | None:
    if architecture_id is None:
        return None
    text = str(architecture_id).strip().lower()
    if not text or text in {"default", "legacy", "none"}:
        return None
    if text in {
        ARCHITECTURE_IPADAPTER_PLUS_FACE,
        "ipadapter_plus_face",
        "path_c",
        "path-c",
    }:
        return ARCHITECTURE_IPADAPTER_PLUS_FACE
    if text in {ARCHITECTURE_INSTANTID, "instantid"}:
        return ARCHITECTURE_INSTANTID
    return text


def launch_profile_for_architecture(architecture_id: str | None = None) -> LaunchProfile:
    """Resolve Full Launch dependency profile for an identity architecture."""
    arch = normalize_architecture_id(architecture_id)
    if arch == ARCHITECTURE_IPADAPTER_PLUS_FACE:
        return LaunchProfile(
            profile_id="path_c_ipadapter_plus_face",
            architecture_id=ARCHITECTURE_IPADAPTER_PLUS_FACE,
            require_faceid_python_deps=False,
            require_faceid_runtime_bridge=False,
            require_faceid_buffalo_bridge=False,
            require_reactor_insightface_bridge=False,
            notes=(
                "PATH C CLIP NON-FaceID: exclude FaceID/InsightFace/ReActor install probes",
                "albucore/median_blur FaceID python probe must not run",
            ),
        )
    # Default / InstantID / unspecified: keep legacy FaceID-era optional bridges.
    # FaceID python deps remain fail-closed only when explicitly required by profile.
    return LaunchProfile(
        profile_id="legacy_default",
        architecture_id=arch,
        require_faceid_python_deps=True,
        require_faceid_runtime_bridge=True,
        require_faceid_buffalo_bridge=True,
        require_reactor_insightface_bridge=True,
        notes=(
            "Legacy Full Launch includes FaceID/ReActor optional bridges",
            "FaceID python verify remains a hard gate for this profile",
        ),
    )


def path_c_launch_excludes_forbidden_deps(profile: LaunchProfile | None = None) -> bool:
    """True when the active profile excludes FaceID-era launch probes."""
    profile = profile or launch_profile_for_architecture(ARCHITECTURE_IPADAPTER_PLUS_FACE)
    return (
        profile.architecture_id == ARCHITECTURE_IPADAPTER_PLUS_FACE
        and profile.skip_faceid_era_probes
    )


def install_sh_skip_faceid_era(architecture_id: str | None) -> bool:
    return launch_profile_for_architecture(architecture_id).skip_faceid_era_probes


def live_architecture_from_config(repo_root: Path | None = None) -> str | None:
    """Read live architecture id from identity_architecture_benchmark.json when present."""
    if repo_root is None:
        return None
    path = Path(repo_root) / "configs" / "benchmarks" / "identity_architecture_benchmark.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    arch = data.get("architecture") or data.get("live_architecture")
    return normalize_architecture_id(str(arch) if arch else None)


def resolve_launch_architecture(
    architecture_id: str | None = None,
    *,
    env: dict[str, str] | None = None,
    settings: dict[str, Any] | None = None,
    repo_root: Path | None = None,
) -> str | None:
    """Resolve architecture for Full Launch dependency profile.

    Precedence: explicit arg → AI_STUDIO_IDENTITY_ARCHITECTURE → settings →
    live config architecture → None (legacy FaceID-era profile).
    """
    if architecture_id:
        return normalize_architecture_id(architecture_id)
    environ = env if env is not None else dict(os.environ)
    from_env = environ.get("AI_STUDIO_IDENTITY_ARCHITECTURE") or environ.get(
        "AI_STUDIO_LAUNCH_ARCHITECTURE"
    )
    if from_env:
        return normalize_architecture_id(from_env)
    if settings:
        from_settings = settings.get("identity_architecture") or settings.get(
            "launch_architecture"
        )
        if from_settings:
            return normalize_architecture_id(str(from_settings))
    return live_architecture_from_config(repo_root)


def path_c_forbidden_capabilities_present(capabilities: set[str] | frozenset[str]) -> bool:
    """True if any FaceID-era capability is still in a PATH C launch plan."""
    lowered = {str(c).strip().lower() for c in capabilities}
    return bool(lowered & FORBIDDEN_FOR_PATH_C_LAUNCH) or bool(
        lowered & FACEID_ERA_CAPABILITIES
    )
