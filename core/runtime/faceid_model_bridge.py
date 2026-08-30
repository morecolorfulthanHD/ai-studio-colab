#!/usr/bin/env python3
"""Bridge Drive-canonical FaceID assets into IPAdapter's runtime discovery paths.

Pinned ComfyUI_IPAdapter_plus (a0f451a…) resolves models via ``folder_paths`` at
execution time — not via SHA checks on Drive canonical paths:

* ``get_clipvision_file`` → ``folder_paths.get_filename_list("clip_vision")`` +
  regex ``(ViT.H.14.*s32B.b79K|…)`` (``utils.py``)
* ``get_ipadapter_file`` for ``FACEID PLUS V2`` → ``faceid.plusv2.sd15.(bin|safetensors)$``
* ``get_lora_file`` → ``faceid.plusv2.sd15.lora.safetensors$``

``extra_model_paths.yaml`` maps ``ipadapter`` and ``loras`` to Drive, but **not**
``clip_vision``. Canonical filenames (``ip-adapter-faceid-plusv2_sd15.bin``) also
do not match the pinned unified-loader regexes. A filesystem+SHA dependency check
therefore false-positives while ``IPAdapterUnifiedLoaderFaceID`` raises
``ClipVision model not found``.

AI Studio bridges Drive-canonical files into real ``ComfyUI/models/{clip_vision,ipadapter,loras}/``
entries using discovery-compatible names (file-level links only).
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .generation_evidence_ledger import file_sha256
from .reactor_model_bridge import BridgeAction, _ensure_bridge_link, _paths_content_match

FACEID_PLUS_V2_PRESET = "FACEID PLUS V2"
CLIP_VISION_CANONICAL_FILENAME = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
IPADAPTER_CANONICAL_FILENAME = "ip-adapter-faceid-plusv2_sd15.bin"
LORA_CANONICAL_FILENAME = "ip-adapter-faceid-plusv2_sd15_lora.safetensors"
IPADAPTER_DISCOVERY_FILENAME = "faceid.plusv2.sd15.bin"
LORA_DISCOVERY_FILENAME = "faceid.plusv2.sd15.lora.safetensors"
FACEID_LOADER_NODE_TYPES = ("IPAdapterUnifiedLoaderFaceID",)
FACEID_LIVE_NODE_TYPES = ("IPAdapterUnifiedLoaderFaceID", "IPAdapterFaceID")


@dataclass
class FaceidRuntimeBridgeResult:
    ok: bool
    canonical_clip_vision_dir: str = ""
    canonical_ipadapter_dir: str = ""
    canonical_lora_dir: str = ""
    runtime_clip_vision_dir: str = ""
    runtime_ipadapter_dir: str = ""
    runtime_lora_dir: str = ""
    clip_vision_verified: bool = False
    ipadapter_verified: bool = False
    lora_verified: bool = False
    resolver_verified: bool = False
    dry_run: bool = False
    actions: list[BridgeAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["actions"] = [asdict(a) for a in self.actions]
        return payload


def default_canonical_clip_vision_dir(drive_models_shared: Path) -> Path:
    return Path(drive_models_shared) / "clip_vision"


def default_canonical_ipadapter_dir(drive_models_shared: Path) -> Path:
    return Path(drive_models_shared) / "ipadapter"


def default_canonical_lora_dir(drive_models_shared: Path) -> Path:
    return Path(drive_models_shared) / "loras"


def runtime_clip_vision_dir(comfyui_runtime: Path) -> Path:
    return Path(comfyui_runtime) / "models" / "clip_vision"


def runtime_ipadapter_dir(comfyui_runtime: Path) -> Path:
    return Path(comfyui_runtime) / "models" / "ipadapter"


def runtime_lora_dir(comfyui_runtime: Path) -> Path:
    return Path(comfyui_runtime) / "models" / "loras"


def runtime_clip_vision_path(comfyui_runtime: Path) -> Path:
    return runtime_clip_vision_dir(comfyui_runtime) / CLIP_VISION_CANONICAL_FILENAME


def runtime_ipadapter_discovery_path(comfyui_runtime: Path) -> Path:
    return runtime_ipadapter_dir(comfyui_runtime) / IPADAPTER_DISCOVERY_FILENAME


def runtime_lora_discovery_path(comfyui_runtime: Path) -> Path:
    return runtime_lora_dir(comfyui_runtime) / LORA_DISCOVERY_FILENAME


def _list_category_basenames(category_dir: Path) -> list[str]:
    """Basenames visible under a ComfyUI model category directory."""
    category_dir = Path(category_dir)
    if not category_dir.is_dir():
        return []
    found: list[str] = []
    for root, _, files in os.walk(category_dir):
        rel = Path(root).relative_to(category_dir)
        for name in files:
            if rel == Path("."):
                found.append(name)
            else:
                found.append(str(rel / name).replace("\\", "/"))
    return found


def ipadapter_style_get_clipvision_basename(preset: str, clipvision_list: list[str]) -> str | None:
    """Mirror pinned ``utils.get_clipvision_file`` basename resolution (no ComfyUI import)."""
    preset_l = preset.lower()
    if preset_l.startswith("vit-g"):
        pattern = r"(ViT.bigG.14.*39B.b160k|ipadapter.*sdxl|sdxl.*model)\.(bin|safetensors)"
    elif preset_l.startswith("kolors"):
        pattern = r"clip.vit.large.patch14.336\.(bin|safetensors)"
    else:
        pattern = r"(ViT.H.14.*s32B.b79K|ipadapter.*sd15|sd1.?5.*model)\.(bin|safetensors)"
    matches = [name for name in clipvision_list if re.search(pattern, name, re.IGNORECASE)]
    return matches[0] if matches else None


def ipadapter_style_get_ipadapter_basename(
    preset: str,
    *,
    is_sdxl: bool,
    ipadapter_list: list[str],
) -> tuple[str | None, bool, str | None]:
    """Mirror pinned ``utils.get_ipadapter_file`` basename resolution."""
    preset_l = preset.lower()
    is_insightface = False
    lora_pattern: str | None = None

    if preset_l.startswith("faceid plus v2"):
        if is_sdxl:
            pattern = r"faceid.plusv2.sdxl\.(safetensors|bin)$"
            lora_pattern = r"faceid.plusv2.sdxl.lora\.safetensors$"
        else:
            pattern = r"faceid.plusv2.sd15\.(safetensors|bin)$"
            lora_pattern = r"faceid.plusv2.sd15.lora\.safetensors$"
        is_insightface = True
    else:
        return None, False, None

    matches = [name for name in ipadapter_list if re.search(pattern, name, re.IGNORECASE)]
    return (matches[0] if matches else None), is_insightface, lora_pattern


def ipadapter_style_get_lora_basename(pattern: str | None, lora_list: list[str]) -> str | None:
    """Mirror pinned ``utils.get_lora_file`` basename resolution."""
    if not pattern:
        return None
    matches = [name for name in lora_list if re.search(pattern, name, re.IGNORECASE)]
    return matches[0] if matches else None


def assess_faceid_pinned_resolver(
    comfyui_runtime: Path,
    *,
    preset: str = FACEID_PLUS_V2_PRESET,
    is_sdxl: bool = False,
) -> dict[str, Any]:
    """Verify pinned IPAdapter unified-loader helpers would resolve all FaceID assets."""
    comfyui_runtime = Path(comfyui_runtime)
    clip_list = _list_category_basenames(runtime_clip_vision_dir(comfyui_runtime))
    ipadapter_list = _list_category_basenames(runtime_ipadapter_dir(comfyui_runtime))
    lora_list = _list_category_basenames(runtime_lora_dir(comfyui_runtime))

    clip_name = ipadapter_style_get_clipvision_basename(preset, clip_list)
    ipadapter_name, is_insightface, lora_pattern = ipadapter_style_get_ipadapter_basename(
        preset,
        is_sdxl=is_sdxl,
        ipadapter_list=ipadapter_list,
    )
    lora_name = ipadapter_style_get_lora_basename(lora_pattern, lora_list)

    row: dict[str, Any] = {
        "status": "MISSING",
        "verified": False,
        "preset": preset,
        "clip_vision_basename": clip_name,
        "ipadapter_basename": ipadapter_name,
        "lora_basename": lora_name,
        "clip_vision_list_sample": clip_list[:10],
        "ipadapter_list_sample": ipadapter_list[:10],
        "lora_list_sample": lora_list[:10],
        "is_insightface": is_insightface,
        "notes": "",
        "benchmark_execution_tested": False,
    }

    missing: list[str] = []
    if clip_name is None:
        missing.append("clip_vision")
    if ipadapter_name is None:
        missing.append("ipadapter")
    if lora_name is None:
        missing.append("lora")

    if missing:
        row["status"] = "MISSING"
        row["notes"] = (
            "Pinned IPAdapter unified loader would raise model-not-found for: "
            + ", ".join(missing)
            + ". "
            + (
                "ClipVision: folder_paths clip_vision list is empty or filename does not "
                "match ViT.H.14.*s32B.b79K pattern."
                if "clip_vision" in missing
                else ""
            )
        ).strip()
        return row

    clip_path = runtime_clip_vision_dir(comfyui_runtime) / clip_name
    ipadapter_path = runtime_ipadapter_dir(comfyui_runtime) / ipadapter_name
    lora_path = runtime_lora_dir(comfyui_runtime) / lora_name
    for label, path in (
        ("clip_vision", clip_path),
        ("ipadapter", ipadapter_path),
        ("lora", lora_path),
    ):
        if not path.is_file() and not path.is_symlink():
            row["status"] = "RUNTIME_MISSING"
            row["notes"] = f"Resolver matched {label} basename {path.name!r} but file is absent."
            return row

    row["status"] = "VERIFIED"
    row["verified"] = True
    row["notes"] = (
        "Pinned get_clipvision_file / get_ipadapter_file / get_lora_file would resolve "
        f"for preset {preset!r} (runtime discovery only; benchmark execution not tested)."
    )
    return row


def assess_faceid_live_discovery(
    *,
    filesystem_resolver: dict[str, Any],
    object_info: dict[str, Any] | None,
    object_info_status: str,
    required_node_types: tuple[str, ...] = FACEID_LIVE_NODE_TYPES,
) -> dict[str, Any]:
    """Live FaceID discovery: object_info node registration + pinned filesystem resolver.

    Filesystem resolver VERIFIED is not sufficient. Without a successful object_info
    fetch, ComfyUI may not have imported IPAdapter / enumerated clip_vision yet.
    """
    row: dict[str, Any] = {
        "status": "UNCHECKED",
        "verified": False,
        "object_info_status": object_info_status,
        "filesystem_resolver_status": filesystem_resolver.get("status"),
        "filesystem_resolver_verified": bool(filesystem_resolver.get("verified")),
        "missing_node_types": [],
        "notes": "",
        "benchmark_execution_tested": False,
    }
    status = str(object_info_status or "unchecked").strip().lower()
    if status != "ok" or object_info is None:
        row["status"] = "UNCHECKED"
        row["notes"] = (
            f"Live ComfyUI object_info status={object_info_status}; "
            "FaceID CLIP resolver/discovery not live-verified."
        )
        return row

    missing = [t for t in required_node_types if t not in object_info]
    row["missing_node_types"] = missing
    if missing:
        row["status"] = "MISSING"
        row["notes"] = (
            "object_info is available but missing required FaceID node types: "
            + ", ".join(missing)
        )
        return row

    if not filesystem_resolver.get("verified"):
        row["status"] = str(filesystem_resolver.get("status") or "MISSING")
        row["notes"] = (
            "Live FaceID nodes are registered, but the pinned resolver cannot discover "
            "required CLIP Vision / FaceID Plus v2 files: "
            f"{filesystem_resolver.get('notes') or filesystem_resolver.get('status')}"
        )
        return row

    row["status"] = "VERIFIED"
    row["verified"] = True
    row["notes"] = (
        "Live FaceID node types present in object_info and pinned resolver matches "
        "CLIP Vision / FaceID Plus v2 files (runtime discovery only; "
        "benchmark execution not tested)."
    )
    return row


def _ensure_real_category_dir(
    runtime_dir: Path,
    *,
    dry_run: bool,
    result: FaceidRuntimeBridgeResult,
    label: str,
) -> bool:
    if runtime_dir.is_symlink():
        result.actions.append(
            BridgeAction(
                action="replace_dir_symlink",
                path=str(runtime_dir),
                notes=(
                    f"Replacing {label} directory symlink with real dir + file bridges "
                    "(IPAdapter folder_paths enumeration must see entries)."
                ),
            )
        )
        if dry_run:
            return True
        runtime_dir.unlink()
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return True
    if runtime_dir.exists() and not runtime_dir.is_dir():
        result.errors.append(f"ERROR: Runtime {label} path is not a directory: {runtime_dir}")
        return False
    if not runtime_dir.exists():
        result.actions.append(BridgeAction(action="mkdir", path=str(runtime_dir)))
        if not dry_run:
            runtime_dir.mkdir(parents=True, exist_ok=True)
    return True


def ensure_faceid_runtime_bridge(
    *,
    comfyui_runtime: Path,
    canonical_clip_vision_dir: Path,
    canonical_ipadapter_dir: Path,
    canonical_lora_dir: Path,
    dry_run: bool = False,
    require_clip: bool = True,
    require_ipadapter: bool = True,
    require_lora: bool = True,
) -> FaceidRuntimeBridgeResult:
    """Ensure IPAdapter-visible FaceID files resolve to Drive-canonical assets."""
    comfyui_runtime = Path(comfyui_runtime)
    canonical_clip_dir = Path(canonical_clip_vision_dir)
    canonical_ipa_dir = Path(canonical_ipadapter_dir)
    canonical_lora = Path(canonical_lora_dir)

    rt_clip_dir = runtime_clip_vision_dir(comfyui_runtime)
    rt_ipa_dir = runtime_ipadapter_dir(comfyui_runtime)
    rt_lora_dir = runtime_lora_dir(comfyui_runtime)

    canonical_clip = canonical_clip_dir / CLIP_VISION_CANONICAL_FILENAME
    canonical_ipa = canonical_ipa_dir / IPADAPTER_CANONICAL_FILENAME
    canonical_lora_file = canonical_lora / LORA_CANONICAL_FILENAME

    runtime_clip = rt_clip_dir / CLIP_VISION_CANONICAL_FILENAME
    runtime_ipa = rt_ipa_dir / IPADAPTER_DISCOVERY_FILENAME
    runtime_lora = rt_lora_dir / LORA_DISCOVERY_FILENAME

    result = FaceidRuntimeBridgeResult(
        ok=False,
        canonical_clip_vision_dir=str(canonical_clip_dir),
        canonical_ipadapter_dir=str(canonical_ipa_dir),
        canonical_lora_dir=str(canonical_lora),
        runtime_clip_vision_dir=str(rt_clip_dir),
        runtime_ipadapter_dir=str(rt_ipa_dir),
        runtime_lora_dir=str(rt_lora_dir),
        dry_run=dry_run,
    )

    if not comfyui_runtime.is_dir():
        result.errors.append(f"ERROR: ComfyUI runtime missing: {comfyui_runtime}")
        return result

    models_dir = comfyui_runtime / "models"
    if not models_dir.exists() and not dry_run:
        models_dir.mkdir(parents=True, exist_ok=True)

    for rt_dir, label in (
        (rt_clip_dir, "clip_vision"),
        (rt_ipa_dir, "ipadapter"),
        (rt_lora_dir, "loras"),
    ):
        if not _ensure_real_category_dir(rt_dir, dry_run=dry_run, result=result, label=label):
            return result

    bridges: list[tuple[Path, Path, bool, str]] = [
        (runtime_clip, canonical_clip, require_clip, "clip_vision"),
        (runtime_ipa, canonical_ipa, require_ipadapter, "ipadapter"),
        (runtime_lora, canonical_lora_file, require_lora, "lora"),
    ]

    for link_path, target, required, label in bridges:
        if not target.is_file():
            if required:
                result.errors.append(
                    f"ERROR: Canonical {label} missing on Drive (manual placement only): {target}"
                )
                return result
            continue
        if not _ensure_bridge_link(link_path, target, dry_run=dry_run, result=result):
            return result

    if dry_run:
        result.clip_vision_verified = canonical_clip.is_file()
        result.ipadapter_verified = canonical_ipa.is_file()
        result.lora_verified = canonical_lora_file.is_file()
        resolver = assess_faceid_pinned_resolver(comfyui_runtime)
        result.resolver_verified = bool(resolver.get("verified"))
        result.messages.append("DRY-RUN: FaceID bridge actions planned; no filesystem changes.")
        result.ok = not result.errors
        return result

    for link_path, target, required, label in bridges:
        if not target.is_file():
            continue
        if not link_path.exists():
            result.errors.append(f"ERROR: Runtime {label} missing after bridge: {link_path}")
            return result
        if not _paths_content_match(link_path, target):
            result.errors.append(
                f"ERROR: Runtime {label} does not resolve to canonical Drive asset "
                f"(runtime={link_path}, canonical={target})"
            )
            return result

    resolver = assess_faceid_pinned_resolver(comfyui_runtime)
    if not resolver.get("verified"):
        result.errors.append(
            "ERROR: Pinned IPAdapter resolver still cannot discover FaceID assets after bridge: "
            f"{resolver.get('notes')}"
        )
        return result

    result.resolver_verified = True
    if canonical_clip.is_file():
        result.clip_vision_verified = _paths_content_match(runtime_clip, canonical_clip)
    if canonical_ipa.is_file():
        result.ipadapter_verified = _paths_content_match(runtime_ipa, canonical_ipa)
    if canonical_lora_file.is_file():
        result.lora_verified = _paths_content_match(runtime_lora, canonical_lora_file)

    result.ok = not result.errors
    if result.ok:
        result.messages.append(
            "FaceID runtime file-level bridge ready "
            f"(resolver_verified={result.resolver_verified})"
        )
    return result


def assess_faceid_runtime_asset(
    *,
    canonical_path: Path,
    runtime_path: Path,
    resolver_role: str,
    comfyui_runtime: Path | None = None,
) -> dict[str, Any]:
    """Readiness row for a single FaceID runtime-visible asset vs Drive canonical."""
    canonical_path = Path(canonical_path)
    runtime_path = Path(runtime_path)
    row: dict[str, Any] = {
        "canonical_path": str(canonical_path),
        "runtime_path": str(runtime_path),
        "resolver_role": resolver_role,
        "canonical_present": canonical_path.is_file(),
        "runtime_present": False,
        "runtime_is_symlink": False,
        "runtime_resolves": False,
        "matches_canonical": False,
        "pinned_resolver_verified": False,
        "status": "MISSING",
        "verified": False,
        "actual_size_bytes": None,
        "canonical_size_bytes": None,
        "actual_sha256": None,
        "canonical_sha256": None,
    }
    if canonical_path.is_file():
        try:
            row["canonical_size_bytes"] = canonical_path.stat().st_size
            row["canonical_sha256"] = file_sha256(canonical_path)
        except OSError:
            row["status"] = "UNREADABLE"
            return row
    else:
        row["status"] = "CANONICAL_MISSING"
        return row

    try:
        exists = runtime_path.exists()
    except OSError:
        row["status"] = "RUNTIME_UNREADABLE"
        return row

    if not exists and not runtime_path.is_symlink():
        row["status"] = "RUNTIME_MISSING"
        return row

    row["runtime_present"] = True
    row["runtime_is_symlink"] = runtime_path.is_symlink()
    if runtime_path.parent.is_symlink():
        row["status"] = "RUNTIME_DIR_SYMLINK"
        row["notes"] = (
            f"Parent {resolver_role} path is a directory symlink; IPAdapter discovery "
            "may not list Drive-backed entries. Re-run Full Launch bridge."
        )
        return row

    try:
        row["runtime_resolves"] = True
        row["actual_size_bytes"] = runtime_path.stat().st_size
        row["actual_sha256"] = file_sha256(runtime_path)
    except OSError:
        row["status"] = "RUNTIME_UNREADABLE"
        return row

    if row["actual_size_bytes"] != row["canonical_size_bytes"]:
        row["status"] = "RUNTIME_SIZE_MISMATCH"
        return row
    if row["actual_sha256"] != row["canonical_sha256"]:
        row["status"] = "RUNTIME_SHA256_MISMATCH"
        return row

    if comfyui_runtime is not None:
        resolver = assess_faceid_pinned_resolver(Path(comfyui_runtime))
        row["pinned_resolver_verified"] = bool(resolver.get("verified"))
        if not row["pinned_resolver_verified"]:
            row["status"] = "RUNTIME_RESOLVER_MISSING"
            row["notes"] = resolver.get("notes") or "Pinned resolver cannot discover FaceID assets."
            return row

    row["matches_canonical"] = True
    row["status"] = "VERIFIED"
    row["verified"] = True
    return row
