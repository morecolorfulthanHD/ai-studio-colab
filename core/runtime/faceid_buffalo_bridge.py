#!/usr/bin/env python3
"""FaceID buffalo_l InsightFace pack contract, bridge, and initialization probe.

Pinned IPAdapter FaceID (a0f451a…) executes::

    insightface_loader(provider)
      → FaceAnalysis(name="buffalo_l", root=<ComfyUI>/models/insightface, ...)
      → glob(<root>/models/buffalo_l/*.onnx) + model_zoo.get_model
      → assert "detection" in self.models

A directory containing only ``w600k_r50.onnx`` passes filesystem/SHA checks for the
recognition weight but **fails** FaceAnalysis initialization because the detection
model (``det_10g.onnx``) is absent.

AI Studio bridges canonical Drive files into ``ComfyUI/models/insightface/models/buffalo_l/``
and probes FaceAnalysis under the ComfyUI interpreter with auto-download disabled.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .faceid_python_deps import FACEID_PYTHON_PROBE_PROVIDER, default_comfy_python_executable
from .generation_evidence_ledger import file_sha256
from .reactor_model_bridge import (
    BridgeAction,
    _ensure_bridge_link,
    _paths_content_match,
    default_canonical_insightface_dir,
    default_runtime_insightface_dir,
)

BUFFALO_L_PACK_NAME = "buffalo_l"
BUFFALO_L_REL = Path("models") / BUFFALO_L_PACK_NAME
DETECTION_FILENAME = "det_10g.onnx"
RECOGNITION_FILENAME = "w600k_r50.onnx"

OPTIONAL_BUFFALO_FILENAMES = (
    "2d106det.onnx",
    "1k3d68.onnx",
    "genderage.onnx",
)

# InsightFace 0.7.3 bindings intercepted by the init probe (verified upstream):
# face_analysis.py: from ..utils import ensure_available
# utils/__init__.py: from .storage import download, ensure_available
# storage.ensure_available -> storage.download -> download.download_file (network)
FACEANALYSIS_DOWNLOAD_BLOCK_BINDINGS = (
    "insightface.utils.storage.download",
    "insightface.utils.storage.ensure_available",
    "insightface.utils.download.download_file",
    "insightface.utils.download",
    "insightface.utils.ensure_available",
    "insightface.app.face_analysis.ensure_available",
)
INSIGHTFACE_DOWNLOAD_PROHIBITED_MESSAGE = "InsightFace auto-download prohibited by AI Studio"


_DOWNLOAD_BLOCK_PREAMBLE = """\
import os
import os.path as osp

download_block_invoked = False

def _blocked_insightface_pack_download(sub_dir, name, force=False, root='~/.insightface'):
    global download_block_invoked
    dir_path = os.path.join(os.path.expanduser(root), sub_dir, name)
    if osp.exists(dir_path) and not force:
        return dir_path
    download_block_invoked = True
    raise RuntimeError(__DOWNLOAD_MSG__)

def _blocked_insightface_network_download(*args, **kwargs):
    global download_block_invoked
    download_block_invoked = True
    raise RuntimeError(__DOWNLOAD_MSG__)

# Patch storage + network layer before FaceAnalysis import (insightface 0.7.3 path).
import insightface.utils.storage as _if_storage
_if_storage.download = _blocked_insightface_pack_download
_if_storage.ensure_available = _blocked_insightface_pack_download

import insightface.utils.download as _if_download_mod
_if_download_mod.download_file = _blocked_insightface_network_download

import insightface.utils as _if_utils
_if_utils.download = _blocked_insightface_pack_download
_if_utils.ensure_available = _blocked_insightface_pack_download

import insightface.app.face_analysis as _if_face_analysis
_if_face_analysis.ensure_available = _blocked_insightface_pack_download

from insightface.app.face_analysis import FaceAnalysis
"""


@dataclass(frozen=True)
class BuffaloArtifactSpec:
    filename: str
    task: str
    required_for_faceid: bool
    registry_name: str | None = None
    notes: str = ""


FACEID_BUFFALO_REQUIRED: tuple[BuffaloArtifactSpec, ...] = (
    BuffaloArtifactSpec(
        DETECTION_FILENAME,
        "detection",
        True,
        registry_name="insightface_buffalo_det",
        notes="SCRFD/RetinaFace detection; required by FaceAnalysis __init__ assert.",
    ),
    BuffaloArtifactSpec(
        RECOGNITION_FILENAME,
        "recognition",
        True,
        registry_name="insightface",
        notes="ResNet50@WebFace600K recognition; required for FaceID normed_embedding.",
    ),
)

FACEID_BUFFALO_OPTIONAL: tuple[BuffaloArtifactSpec, ...] = (
    BuffaloArtifactSpec("2d106det.onnx", "landmark_2d", False, notes="Optional alignment landmark model."),
    BuffaloArtifactSpec("1k3d68.onnx", "landmark_3d", False, notes="Optional 3D landmark model."),
    BuffaloArtifactSpec("genderage.onnx", "genderage", False, notes="Optional attribute model."),
)


@dataclass
class FaceidBuffaloBridgeResult:
    ok: bool
    canonical_insightface_dir: str = ""
    runtime_insightface_dir: str = ""
    dry_run: bool = False
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    actions: list[BridgeAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["actions"] = [asdict(a) for a in self.actions]
        return payload


def canonical_buffalo_artifact_path(canonical_insightface_dir: Path, filename: str) -> Path:
    return Path(canonical_insightface_dir) / BUFFALO_L_REL / filename


def runtime_buffalo_artifact_path(comfyui_runtime: Path, filename: str) -> Path:
    return default_runtime_insightface_dir(comfyui_runtime) / BUFFALO_L_REL / filename


def runtime_buffalo_pack_dir(comfyui_runtime: Path) -> Path:
    return default_runtime_insightface_dir(comfyui_runtime) / BUFFALO_L_REL


def _registry_row(bundle_models: list[dict[str, Any]], registry_name: str | None) -> dict[str, Any]:
    if not registry_name:
        return {}
    for entry in bundle_models:
        if str(entry.get("name") or "") == registry_name:
            return dict(entry)
    return {}


def assess_buffalo_artifact(
    *,
    spec: BuffaloArtifactSpec,
    canonical_insightface_dir: Path,
    comfyui_runtime: Path | None,
    registry_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical_dir = Path(canonical_insightface_dir)
    canonical_path = canonical_buffalo_artifact_path(canonical_dir, spec.filename)
    runtime_path = (
        runtime_buffalo_artifact_path(comfyui_runtime, spec.filename)
        if comfyui_runtime is not None
        else None
    )
    row: dict[str, Any] = {
        "filename": spec.filename,
        "task": spec.task,
        "required_for_faceid": spec.required_for_faceid,
        "registry_name": spec.registry_name,
        "canonical_path": str(canonical_path),
        "runtime_path": str(runtime_path) if runtime_path is not None else None,
        "canonical_present": canonical_path.is_file(),
        "runtime_present": False,
        "runtime_verified": False,
        "status": "MISSING",
        "verified": False,
        "notes": spec.notes,
    }
    entry = registry_entry or {}
    registry_path = str(entry.get("runtime_path") or "").strip()
    if registry_path:
        row["registry_path"] = registry_path
        if Path(registry_path) != canonical_path:
            row["registry_path_matches_canonical"] = False
        else:
            row["registry_path_matches_canonical"] = True
    if not canonical_path.is_file():
        row["status"] = "CANONICAL_MISSING"
        row["notes"] = (
            f"Manual placement required: {canonical_path} "
            f"({spec.task} buffalo_l component; no auto-download)."
        )
        return row
    try:
        row["canonical_size_bytes"] = canonical_path.stat().st_size
        row["canonical_sha256"] = file_sha256(canonical_path)
    except OSError as exc:
        row["status"] = "UNREADABLE"
        row["notes"] = f"Canonical file unreadable: {exc}"
        return row
    expected_sha = str(entry.get("expected_sha256") or "").strip()
    expected_size = entry.get("expected_size_bytes")
    if expected_sha and row["canonical_sha256"] != expected_sha:
        row["status"] = "SHA256_MISMATCH"
        row["notes"] = "Canonical SHA256 mismatch vs registry metadata."
        return row
    if expected_size is not None and row["canonical_size_bytes"] != int(expected_size):
        row["status"] = "SIZE_MISMATCH"
        row["notes"] = "Canonical size mismatch vs registry metadata."
        return row
    if runtime_path is None:
        row["status"] = "RUNTIME_UNCHECKED"
        return row
    if not runtime_path.exists() and not runtime_path.is_symlink():
        row["status"] = "RUNTIME_MISSING"
        return row
    row["runtime_present"] = True
    try:
        row["runtime_size_bytes"] = runtime_path.stat().st_size
        row["runtime_sha256"] = file_sha256(runtime_path)
    except OSError as exc:
        row["status"] = "RUNTIME_UNREADABLE"
        row["notes"] = f"Runtime bridge unreadable: {exc}"
        return row
    if not _paths_content_match(runtime_path, canonical_path):
        row["status"] = "RUNTIME_MISMATCH"
        row["notes"] = "Runtime bridge does not match canonical Drive content."
        return row
    row["runtime_verified"] = True
    row["status"] = "VERIFIED"
    row["verified"] = True
    return row


def assess_faceid_buffalo_inventory(
    *,
    bundle_models: list[dict[str, Any]] | None = None,
    canonical_insightface_dir: Path,
    comfyui_runtime: Path | None,
) -> dict[str, Any]:
    """Assess required/optional buffalo_l artifacts on Drive and runtime bridges."""
    artifacts: list[dict[str, Any]] = []
    missing_required: list[str] = []
    for spec in FACEID_BUFFALO_REQUIRED:
        entry = _registry_row(bundle_models or [], spec.registry_name)
        row = assess_buffalo_artifact(
            spec=spec,
            canonical_insightface_dir=canonical_insightface_dir,
            comfyui_runtime=comfyui_runtime,
            registry_entry=entry or None,
        )
        artifacts.append(row)
        if spec.required_for_faceid and not row.get("verified"):
            missing_required.append(spec.filename)
    for spec in FACEID_BUFFALO_OPTIONAL:
        row = assess_buffalo_artifact(
            spec=spec,
            canonical_insightface_dir=canonical_insightface_dir,
            comfyui_runtime=comfyui_runtime,
            registry_entry=None,
        )
        artifacts.append(row)
    required_rows = [a for a in artifacts if a.get("required_for_faceid")]
    all_required_verified = all(bool(a.get("verified")) for a in required_rows)
    status = "VERIFIED" if all_required_verified else "MISSING"
    if not all_required_verified and any(a.get("status") == "CANONICAL_MISSING" for a in required_rows):
        status = "MISSING"
    elif not all_required_verified:
        status = "INCOMPLETE"
    det_row = next((a for a in artifacts if a.get("filename") == DETECTION_FILENAME), {})
    rec_row = next((a for a in artifacts if a.get("filename") == RECOGNITION_FILENAME), {})
    return {
        "status": status,
        "verified": all_required_verified,
        "pack_name": BUFFALO_L_PACK_NAME,
        "runtime_root": str(default_runtime_insightface_dir(comfyui_runtime)) if comfyui_runtime else None,
        "runtime_pack_dir": str(runtime_buffalo_pack_dir(comfyui_runtime)) if comfyui_runtime else None,
        "artifacts": artifacts,
        "missing_required": missing_required,
        "detection_status": det_row.get("status"),
        "detection_verified": bool(det_row.get("verified")),
        "recognition_status": rec_row.get("status"),
        "recognition_verified": bool(rec_row.get("verified")),
        "notes": (
            "All required buffalo_l artifacts verified on Drive and runtime."
            if all_required_verified
            else (
                "Missing required buffalo_l artifacts: "
                + ", ".join(missing_required)
                + " (manual Drive placement only; no auto-download)."
            )
        ),
        "benchmark_execution_tested": False,
    }


_INIT_PROBE_SCRIPT = """\
import json
import os
import sys

payload = {
    "ok": False,
    "detection_verified": False,
    "recognition_verified": False,
    "initialization_verified": False,
    "tasks": {},
    "error": None,
    "download_blocked": True,
    "download_block_invoked": False,
}
root = __ROOT__
provider = __PROVIDER__
try:
__DOWNLOAD_BLOCK__
    app = FaceAnalysis(
        name=__PACK__,
        root=root,
        providers=[provider + "ExecutionProvider"],
    )
    payload["download_block_invoked"] = bool(download_block_invoked)
    payload["tasks"] = {name: True for name in app.models.keys()}
    payload["detection_verified"] = "detection" in app.models
    payload["recognition_verified"] = "recognition" in app.models
    if not payload["detection_verified"]:
        raise AssertionError("detection model missing from FaceAnalysis.models")
    if not payload["recognition_verified"]:
        raise AssertionError("recognition model missing from FaceAnalysis.models")
    app.prepare(ctx_id=-1, det_size=(640, 640))
    payload["initialization_verified"] = True
    payload["ok"] = True
except Exception as exc:
    payload["download_block_invoked"] = bool(globals().get("download_block_invoked"))
    payload["error"] = f"{type(exc).__name__}: {exc}"
try:
    import insightface.utils.download as _net_probe
    payload["network_calls"] = len(getattr(_net_probe, "NETWORK_CALLS", []))
except Exception:
    payload["network_calls"] = None
print(json.dumps(payload))
sys.exit(0 if payload["ok"] else 1)
"""


def build_faceanalysis_init_probe_script(
    *,
    insightface_root: Path | str,
    provider: str = FACEID_PYTHON_PROBE_PROVIDER,
    pack_name: str = BUFFALO_L_PACK_NAME,
) -> str:
    """Build the subprocess FaceAnalysis probe with deterministic download blocking."""
    preamble = _DOWNLOAD_BLOCK_PREAMBLE.replace(
        "__DOWNLOAD_MSG__",
        repr(INSIGHTFACE_DOWNLOAD_PROHIBITED_MESSAGE),
    )
    indented_preamble = "\n".join(
        f"    {line}" if line.strip() else line for line in preamble.splitlines()
    )
    return (
        _INIT_PROBE_SCRIPT.replace("__ROOT__", repr(str(insightface_root)))
        .replace("__PROVIDER__", repr(provider))
        .replace("__PACK__", repr(pack_name))
        .replace("__DOWNLOAD_BLOCK__", indented_preamble)
    )


def _run_faceanalysis_init_probe(
    python_executable: str,
    *,
    insightface_root: Path,
    provider: str = FACEID_PYTHON_PROBE_PROVIDER,
    timeout: float = 120.0,
) -> tuple[bool, dict[str, Any], str]:
    script = build_faceanalysis_init_probe_script(
        insightface_root=insightface_root,
        provider=provider,
    )
    env = os.environ.copy()
    # Do not rely on INSIGHTFACE_DISABLE_DOWNLOAD — upstream 0.7.3 does not honor it
    # for FaceAnalysis model-pack resolution; explicit binding patches are required.
    env.pop("INSIGHTFACE_DISABLE_DOWNLOAD", None)
    try:
        proc = subprocess.run(
            [python_executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, {}, f"{type(exc).__name__}: {exc}"
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if not stdout:
        return False, {}, stderr or f"init probe exit {proc.returncode} with no stdout"
    try:
        payload = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        return False, {}, f"invalid init probe JSON ({exc}); tail={stdout[-400:]!r}"
    ok = bool(payload.get("ok")) and proc.returncode == 0
    if not ok and not payload.get("error"):
        payload["error"] = stderr or f"init probe exit {proc.returncode}"
    return ok, payload, str(payload.get("error") or "")


def assess_faceid_buffalo_runtime(
    *,
    bundle_models: list[dict[str, Any]] | None = None,
    canonical_insightface_dir: Path,
    comfyui_runtime: Path | None,
    python_executable: str | None = None,
    provider: str = FACEID_PYTHON_PROBE_PROVIDER,
) -> dict[str, Any]:
    """Inventory + bounded FaceAnalysis initialization probe (no auto-download)."""
    inventory = assess_faceid_buffalo_inventory(
        bundle_models=bundle_models,
        canonical_insightface_dir=canonical_insightface_dir,
        comfyui_runtime=comfyui_runtime,
    )
    result = dict(inventory)
    result["python_executable"] = str(python_executable or default_comfy_python_executable())
    result["initialization_status"] = "UNCHECKED"
    result["initialization_verified"] = False
    result["faceanalysis_tasks"] = {}
    if not inventory.get("verified"):
        result["status"] = "MISSING"
        result["verified"] = False
        result["initialization_status"] = "SKIPPED"
        result["notes"] = inventory.get("notes") or "Required buffalo_l artifacts incomplete."
        return result
    if comfyui_runtime is None:
        result["initialization_status"] = "RUNTIME_UNCHECKED"
        result["notes"] = "Required buffalo_l artifacts verified on Drive; runtime init unchecked."
        return result
    ok, payload, err = _run_faceanalysis_init_probe(
        result["python_executable"],
        insightface_root=default_runtime_insightface_dir(comfyui_runtime),
        provider=provider,
    )
    result["faceanalysis_tasks"] = dict(payload.get("tasks") or {})
    result["detection_verified"] = bool(payload.get("detection_verified"))
    result["recognition_verified"] = bool(payload.get("recognition_verified"))
    result["initialization_verified"] = bool(payload.get("initialization_verified"))
    if ok:
        result["status"] = "VERIFIED"
        result["verified"] = True
        result["initialization_status"] = "VERIFIED"
        result["notes"] = (
            "FaceAnalysis buffalo_l initialized under ComfyUI models/insightface "
            f"with detection+recognition ({provider}ExecutionProvider); auto-download blocked."
        )
    else:
        err_l = (err or "").lower()
        if "assertionerror" in err_l or "detection model missing" in err_l:
            init_status = "DETECTION_MISSING"
        elif "recognition model missing" in err_l:
            init_status = "RECOGNITION_MISSING"
        elif "auto-download prohibited" in err_l or "download prohibited" in err_l:
            init_status = "DOWNLOAD_REQUIRED"
        else:
            init_status = "ERROR"
        result["status"] = "INCOMPLETE"
        result["verified"] = False
        result["initialization_status"] = init_status
        result["notes"] = err or "FaceAnalysis buffalo_l initialization probe failed."
    return result


def ensure_faceid_buffalo_bridge(
    *,
    comfyui_runtime: Path,
    canonical_insightface_dir: Path,
    bundle_models: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> FaceidBuffaloBridgeResult:
    """Bridge required buffalo_l artifacts from Drive to ComfyUI runtime (file-level only)."""
    comfyui_runtime = Path(comfyui_runtime)
    canonical_dir = Path(canonical_insightface_dir)
    runtime_dir = default_runtime_insightface_dir(comfyui_runtime)
    result = FaceidBuffaloBridgeResult(
        ok=False,
        canonical_insightface_dir=str(canonical_dir),
        runtime_insightface_dir=str(runtime_dir),
        dry_run=dry_run,
    )
    if not comfyui_runtime.is_dir():
        result.errors.append(f"ERROR: ComfyUI runtime missing: {comfyui_runtime}")
        return result
    if not canonical_dir.is_dir():
        result.errors.append(f"ERROR: Canonical InsightFace directory missing: {canonical_dir}")
        return result
    runtime_pack = runtime_buffalo_pack_dir(comfyui_runtime)
    if not dry_run:
        runtime_pack.mkdir(parents=True, exist_ok=True)
    else:
        result.messages.append(f"DRY-RUN: would ensure {runtime_pack}")

    for spec in FACEID_BUFFALO_REQUIRED:
        entry = _registry_row(bundle_models or [], spec.registry_name)
        canonical_path = canonical_buffalo_artifact_path(canonical_dir, spec.filename)
        runtime_path = runtime_buffalo_artifact_path(comfyui_runtime, spec.filename)
        artifact_row = assess_buffalo_artifact(
            spec=spec,
            canonical_insightface_dir=canonical_dir,
            comfyui_runtime=None,
            registry_entry=entry or None,
        )
        result.artifacts.append(artifact_row)
        if not canonical_path.is_file():
            result.errors.append(
                f"ERROR: Required canonical buffalo_l artifact missing (manual only): {canonical_path}"
            )
            continue
        if not _ensure_bridge_link(
            runtime_path, canonical_path, dry_run=dry_run, result=result
        ):
            return result

    if dry_run:
        result.ok = not result.errors
        result.messages.append("DRY-RUN: FaceID buffalo_l bridge planned; no filesystem changes.")
        return result

    post = assess_faceid_buffalo_inventory(
        bundle_models=bundle_models,
        canonical_insightface_dir=canonical_dir,
        comfyui_runtime=comfyui_runtime,
    )
    result.artifacts = list(post.get("artifacts") or [])
    if not post.get("verified"):
        result.errors.append(
            "ERROR: Required buffalo_l runtime bridge incomplete after apply: "
            + ", ".join(post.get("missing_required") or [])
        )
        return result
    result.ok = True
    result.messages.append("FaceID buffalo_l runtime bridge verified (det_10g + w600k_r50).")
    return result
