#!/usr/bin/env python3
"""Bridge Drive-canonical InsightFace assets into ReActor's runtime search path.

Pinned ReActor (6ad6b35a…) discovers swap models via::

    glob.glob(os.path.join(folder_paths.models_dir, "insightface/*"))

(see ``scripts/reactor_faceswap.get_models``), then exposes basenames on
``INPUT_TYPES`` → ``swap_model``. It does NOT use ``extra_model_paths.yaml``.

Directory-level symlinks of ``models/insightface`` onto Google Drive FUSE can
pass ``Path.exists`` while ``glob`` returns empty — live ``/object_info`` then
omits ``inswapper_128.onnx`` and the frontend reports the model missing.

AI Studio therefore uses a *real* ``ComfyUI/models/insightface/`` directory with
*file-level* bridges only (no whole-tree directory symlink).
"""

from __future__ import annotations

import glob
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .generation_evidence_ledger import file_sha256

INSWAPPER_FILENAME = "inswapper_128.onnx"
BUFFALO_REL = Path("models") / "buffalo_l" / "w600k_r50.onnx"
REACTOR_SWAP_MODEL_NODE_TYPES = ("ReActorFaceSwap", "ReActorFaceSwapOpt")
REACTOR_SWAP_FOLDERS = ("insightface", "reswapper", "hyperswap")


@dataclass
class BridgeAction:
    action: str
    path: str
    target: str = ""
    notes: str = ""


@dataclass
class ReactorInsightfaceBridgeResult:
    ok: bool
    canonical_insightface_dir: str = ""
    runtime_insightface_dir: str = ""
    canonical_inswapper: str = ""
    runtime_inswapper: str = ""
    canonical_buffalo: str = ""
    runtime_buffalo: str = ""
    inswapper_verified: bool = False
    buffalo_verified: bool = False
    reactor_glob_discoverable: bool = False
    dry_run: bool = False
    actions: list[BridgeAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["actions"] = [asdict(a) for a in self.actions]
        return payload


def default_canonical_insightface_dir(drive_models_shared: Path) -> Path:
    return Path(drive_models_shared) / "insightface"


def default_runtime_insightface_dir(comfyui_runtime: Path) -> Path:
    return Path(comfyui_runtime) / "models" / "insightface"


def reactor_runtime_inswapper_path(comfyui_runtime: Path) -> Path:
    return default_runtime_insightface_dir(comfyui_runtime) / INSWAPPER_FILENAME


def reactor_runtime_buffalo_path(comfyui_runtime: Path) -> Path:
    return default_runtime_insightface_dir(comfyui_runtime) / BUFFALO_REL


def reactor_style_list_swap_models(comfyui_runtime: Path) -> list[str]:
    """Mirror pinned ReActor get_models() basename discovery (no ComfyUI import)."""
    models_dir = Path(comfyui_runtime) / "models"
    found: list[str] = []
    for folder in REACTOR_SWAP_FOLDERS:
        pattern = str(models_dir / folder / "*")
        for path in glob.glob(pattern):
            if path.endswith(".onnx") or path.endswith(".pth"):
                found.append(os.path.basename(path))
    return found


def reactor_glob_discovers_inswapper(comfyui_runtime: Path) -> bool:
    return INSWAPPER_FILENAME in reactor_style_list_swap_models(comfyui_runtime)


def extract_comfy_combo_options(input_spec: Any) -> list[str]:
    """Parse ComfyUI object_info input spec into combo option strings."""
    if input_spec is None:
        return []
    if isinstance(input_spec, (list, tuple)) and input_spec:
        first = input_spec[0]
        if isinstance(first, (list, tuple)) and all(isinstance(x, str) for x in first):
            return [str(x) for x in first]
        if all(isinstance(x, str) for x in input_spec):
            return [str(x) for x in input_spec]
    if isinstance(input_spec, dict):
        options = input_spec.get("options") or input_spec.get("choices")
        if isinstance(options, (list, tuple)):
            return [str(x) for x in options]
    return []


def assess_reactor_live_swap_model_option(
    object_info: dict[str, Any] | None,
    *,
    object_info_status: str,
    required_filename: str = INSWAPPER_FILENAME,
    node_types: tuple[str, ...] = REACTOR_SWAP_MODEL_NODE_TYPES,
) -> dict[str, Any]:
    """Require live object_info to advertise required_filename on swap_model."""
    row: dict[str, Any] = {
        "status": "UNCHECKED",
        "verified": False,
        "required_filename": required_filename,
        "node_type": None,
        "swap_model_options": [],
        "notes": "",
    }
    if object_info_status != "ok" or object_info is None:
        row["status"] = "UNCHECKED"
        row["notes"] = (
            f"ComfyUI object_info status={object_info_status}; "
            "live swap_model option not verified."
        )
        return row

    for node_type in node_types:
        node = object_info.get(node_type)
        if not isinstance(node, dict):
            continue
        inputs = node.get("input") or {}
        required = inputs.get("required") or {}
        optional = inputs.get("optional") or {}
        spec = required.get("swap_model")
        if spec is None:
            spec = optional.get("swap_model")
        options = extract_comfy_combo_options(spec)
        row["node_type"] = node_type
        row["swap_model_options"] = options
        if required_filename in options:
            row["status"] = "VERIFIED"
            row["verified"] = True
            row["notes"] = (
                f"{node_type}.swap_model advertises {required_filename} "
                f"({len(options)} option(s))."
            )
            return row
        row["status"] = "MISSING"
        row["notes"] = (
            f"{node_type} is registered but swap_model options do not include "
            f"{required_filename}. Observed: {options[:20]}"
        )
        return row

    row["status"] = "NODE_MISSING"
    row["notes"] = (
        "object_info lacks ReActorFaceSwap / ReActorFaceSwapOpt; "
        "cannot verify swap_model."
    )
    return row


def _same_resolved_file(left: Path, right: Path) -> bool:
    try:
        if not left.exists() or not right.exists():
            return False
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _paths_content_match(left: Path, right: Path) -> bool:
    """True when paths resolve identically or (same size + SHA256)."""
    if _same_resolved_file(left, right):
        return True
    try:
        if not left.is_file() or not right.is_file():
            return False
        if left.stat().st_size != right.stat().st_size:
            return False
        return file_sha256(left) == file_sha256(right)
    except OSError:
        return False


def _create_bridge_link(link_path: Path, target: Path) -> str:
    """Create a non-duplicating link. Prefer symlink; hardlink files if symlink is unavailable."""
    link_path.parent.mkdir(parents=True, exist_ok=True)
    target_is_dir = target.is_dir()
    try:
        os.symlink(str(target), str(link_path), target_is_directory=target_is_dir)
        return "symlink"
    except OSError as symlink_exc:
        if target_is_dir:
            raise OSError(
                f"Unable to create directory symlink {link_path} -> {target}: {symlink_exc}"
            ) from symlink_exc
        try:
            os.link(str(target), str(link_path))
            return "hardlink"
        except OSError as hardlink_exc:
            raise OSError(
                f"Unable to create symlink or hardlink {link_path} -> {target}: "
                f"symlink={symlink_exc}; hardlink={hardlink_exc}"
            ) from hardlink_exc


def _ensure_bridge_link(
    link_path: Path,
    target: Path,
    *,
    dry_run: bool,
    result: ReactorInsightfaceBridgeResult,
) -> bool:
    """Create or repair a bridge link at link_path pointing at target. Returns True on success."""
    target = Path(target)
    link_path = Path(link_path)
    if not target.exists():
        result.errors.append(f"ERROR: Canonical target missing for bridge: {target}")
        return False

    desired = str(target)
    if link_path.is_symlink():
        try:
            current = os.readlink(link_path)
        except OSError:
            current = ""
        if _same_resolved_file(link_path, target) or current == desired:
            result.actions.append(
                BridgeAction(
                    action="unchanged",
                    path=str(link_path),
                    target=desired,
                    notes="symlink already correct",
                )
            )
            return True
        result.actions.append(
            BridgeAction(
                action="repair",
                path=str(link_path),
                target=desired,
                notes=f"stale symlink was -> {current}",
            )
        )
        if dry_run:
            return True
        link_path.unlink()
    elif link_path.exists():
        # Real file/dir occupying the slot — replace only files or empty dirs.
        if link_path.is_file():
            if _paths_content_match(link_path, target):
                # Already the same bytes (e.g. prior hardlink); leave in place.
                result.actions.append(
                    BridgeAction(
                        action="unchanged",
                        path=str(link_path),
                        target=desired,
                        notes="runtime file already matches canonical",
                    )
                )
                return True
            result.actions.append(
                BridgeAction(
                    action="replace_file",
                    path=str(link_path),
                    target=desired,
                    notes="replacing non-matching file with bridge link to Drive canonical",
                )
            )
            if dry_run:
                return True
            link_path.unlink()
        elif link_path.is_dir():
            try:
                next(link_path.iterdir())
                result.errors.append(
                    f"ERROR: Runtime path is a non-empty directory (not a symlink): {link_path}. "
                    "Refusing to delete; remove or empty it, then re-run Full Launch."
                )
                return False
            except StopIteration:
                result.actions.append(
                    BridgeAction(action="replace_empty_dir", path=str(link_path), target=desired)
                )
                if dry_run:
                    return True
                link_path.rmdir()
        else:
            result.errors.append(f"ERROR: Unsupported path type at {link_path}")
            return False
    else:
        result.actions.append(BridgeAction(action="create", path=str(link_path), target=desired))

    if dry_run:
        return True

    try:
        kind = _create_bridge_link(link_path, target)
    except OSError as exc:
        result.errors.append(f"ERROR: Bridge link failed: {exc}")
        return False
    result.actions[-1].notes = (result.actions[-1].notes + f"; created {kind}").strip("; ")
    if not _paths_content_match(link_path, target) and not _same_resolved_file(link_path, target):
        result.errors.append(
            f"ERROR: Bridge verification failed: {link_path} does not resolve to "
            f"canonical {target}"
        )
        return False
    return True


def _ensure_real_insightface_dir(
    runtime_dir: Path,
    *,
    dry_run: bool,
    result: ReactorInsightfaceBridgeResult,
) -> bool:
    """Ensure insightface is a real directory (not a Drive dir symlink)."""
    if runtime_dir.is_symlink():
        result.actions.append(
            BridgeAction(
                action="replace_dir_symlink",
                path=str(runtime_dir),
                notes=(
                    "Replacing directory symlink with real dir + file bridges "
                    "(ReActor glob.glob(insightface/*) must see entries)."
                ),
            )
        )
        if dry_run:
            return True
        runtime_dir.unlink()
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return True
    if runtime_dir.exists() and not runtime_dir.is_dir():
        result.errors.append(f"ERROR: Runtime insightface path is not a directory: {runtime_dir}")
        return False
    if not runtime_dir.exists():
        result.actions.append(BridgeAction(action="mkdir", path=str(runtime_dir)))
        if not dry_run:
            runtime_dir.mkdir(parents=True, exist_ok=True)
    return True


def ensure_reactor_insightface_bridge(
    *,
    comfyui_runtime: Path,
    canonical_insightface_dir: Path,
    dry_run: bool = False,
    require_inswapper: bool = True,
    require_buffalo: bool = False,
) -> ReactorInsightfaceBridgeResult:
    """Ensure ReActor-visible insightface *files* resolve to Drive-canonical assets."""
    comfyui_runtime = Path(comfyui_runtime)
    canonical_dir = Path(canonical_insightface_dir)
    runtime_dir = default_runtime_insightface_dir(comfyui_runtime)
    canonical_inswapper = canonical_dir / INSWAPPER_FILENAME
    runtime_inswapper = runtime_dir / INSWAPPER_FILENAME
    canonical_buffalo = canonical_dir / BUFFALO_REL
    runtime_buffalo = runtime_dir / BUFFALO_REL

    result = ReactorInsightfaceBridgeResult(
        ok=False,
        canonical_insightface_dir=str(canonical_dir),
        runtime_insightface_dir=str(runtime_dir),
        canonical_inswapper=str(canonical_inswapper),
        runtime_inswapper=str(runtime_inswapper),
        canonical_buffalo=str(canonical_buffalo),
        runtime_buffalo=str(runtime_buffalo),
        dry_run=dry_run,
    )

    if not comfyui_runtime.is_dir():
        result.errors.append(f"ERROR: ComfyUI runtime missing: {comfyui_runtime}")
        return result

    if not canonical_dir.is_dir():
        result.errors.append(
            f"ERROR: Canonical InsightFace directory missing on Drive: {canonical_dir}"
        )
        return result

    models_dir = comfyui_runtime / "models"
    if not models_dir.exists():
        if dry_run:
            result.messages.append(f"DRY-RUN: would create {models_dir}")
        else:
            models_dir.mkdir(parents=True, exist_ok=True)

    if not _ensure_real_insightface_dir(runtime_dir, dry_run=dry_run, result=result):
        return result

    if require_inswapper or canonical_inswapper.is_file():
        if not canonical_inswapper.is_file():
            result.errors.append(
                f"ERROR: Canonical inswapper missing (manual placement only): {canonical_inswapper}"
            )
            if require_inswapper:
                return result
        elif not _ensure_bridge_link(
            runtime_inswapper, canonical_inswapper, dry_run=dry_run, result=result
        ):
            return result

    if require_buffalo or canonical_buffalo.is_file():
        if not canonical_buffalo.is_file():
            if require_buffalo:
                result.errors.append(
                    f"ERROR: Canonical buffalo_l detector missing: {canonical_buffalo}"
                )
                return result
        else:
            if not dry_run:
                runtime_buffalo.parent.mkdir(parents=True, exist_ok=True)
            if not _ensure_bridge_link(
                runtime_buffalo, canonical_buffalo, dry_run=dry_run, result=result
            ):
                return result

    if not dry_run:
        if require_inswapper:
            if not canonical_inswapper.is_file():
                result.errors.append(
                    f"ERROR: Canonical inswapper missing (manual placement only): {canonical_inswapper}"
                )
                return result
            if not runtime_inswapper.exists():
                result.errors.append(
                    f"ERROR: ReActor runtime inswapper missing after bridge: {runtime_inswapper}"
                )
                return result
            if not _paths_content_match(runtime_inswapper, canonical_inswapper):
                result.errors.append(
                    "ERROR: Runtime inswapper does not resolve to canonical Drive asset "
                    f"(runtime={runtime_inswapper}, canonical={canonical_inswapper})"
                )
                return result
            if not reactor_glob_discovers_inswapper(comfyui_runtime):
                discovered = reactor_style_list_swap_models(comfyui_runtime)
                result.errors.append(
                    "ERROR: ReActor-style glob discovery does not see "
                    f"{INSWAPPER_FILENAME} under models/insightface/* "
                    f"(discovered={discovered}). Frontend object_info would omit the model."
                )
                return result
            result.reactor_glob_discoverable = True
            result.inswapper_verified = True
        elif runtime_inswapper.exists() and canonical_inswapper.is_file():
            result.inswapper_verified = _paths_content_match(runtime_inswapper, canonical_inswapper)
            result.reactor_glob_discoverable = reactor_glob_discovers_inswapper(comfyui_runtime)

        if require_buffalo:
            if not canonical_buffalo.is_file():
                result.errors.append(f"ERROR: Canonical buffalo_l missing: {canonical_buffalo}")
                return result
            if not runtime_buffalo.exists():
                result.errors.append(
                    f"ERROR: ReActor runtime buffalo missing after bridge: {runtime_buffalo}"
                )
                return result
            if not _paths_content_match(runtime_buffalo, canonical_buffalo):
                result.errors.append(
                    "ERROR: Runtime buffalo does not resolve to canonical Drive asset "
                    f"(runtime={runtime_buffalo}, canonical={canonical_buffalo})"
                )
                return result
            result.buffalo_verified = True
        elif runtime_buffalo.exists() and canonical_buffalo.is_file():
            result.buffalo_verified = _paths_content_match(runtime_buffalo, canonical_buffalo)
    else:
        result.inswapper_verified = canonical_inswapper.is_file()
        result.buffalo_verified = canonical_buffalo.is_file()
        result.messages.append("DRY-RUN: bridge actions planned; no filesystem changes.")

    result.ok = not result.errors
    if result.ok:
        result.messages.append(
            "ReActor InsightFace file-level bridge ready "
            f"(real dir {runtime_dir}; glob-discoverable={result.reactor_glob_discoverable})"
        )
    return result


def assess_reactor_runtime_asset(
    *,
    canonical_path: Path,
    runtime_path: Path,
) -> dict[str, Any]:
    """Readiness row for a single ReActor-visible asset vs Drive canonical."""
    canonical_path = Path(canonical_path)
    runtime_path = Path(runtime_path)
    row: dict[str, Any] = {
        "canonical_path": str(canonical_path),
        "runtime_path": str(runtime_path),
        "canonical_present": canonical_path.is_file(),
        "runtime_present": False,
        "runtime_is_symlink": runtime_path.is_symlink()
        if runtime_path.exists() or runtime_path.is_symlink()
        else False,
        "runtime_resolves": False,
        "matches_canonical": False,
        "reactor_glob_discoverable": False,
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
    if runtime_path.is_symlink():
        row["runtime_is_symlink"] = True
        try:
            target = Path(os.readlink(runtime_path))
            row["runtime_link_target"] = str(target)
            if not runtime_path.exists():
                row["status"] = "RUNTIME_BROKEN_LINK"
                return row
        except OSError:
            row["status"] = "RUNTIME_BROKEN_LINK"
            return row

    parent = runtime_path.parent
    if parent.is_symlink():
        row["status"] = "RUNTIME_DIR_SYMLINK"
        row["notes"] = (
            "Parent insightface path is a directory symlink; ReActor glob discovery "
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

    comfy_models = parent.parent
    comfy_runtime = comfy_models.parent
    if parent.name == "insightface" and comfy_models.name == "models":
        row["reactor_glob_discoverable"] = reactor_glob_discovers_inswapper(comfy_runtime)
        if not row["reactor_glob_discoverable"]:
            row["status"] = "RUNTIME_NOT_GLOB_DISCOVERABLE"
            return row

    row["matches_canonical"] = True
    row["status"] = "VERIFIED"
    row["verified"] = True
    return row
