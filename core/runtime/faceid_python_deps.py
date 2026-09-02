#!/usr/bin/env python3
"""Managed Python runtime dependencies for pinned IPAdapter FaceID execution.

Pinned ComfyUI_IPAdapter_plus (a0f451a…) loads FaceID at execution time via
``utils.insightface_loader``:

    from insightface.app import FaceAnalysis

That import is **lazy** (not at custom-node import time), so ComfyUI ``object_info``
can register ``IPAdapterUnifiedLoaderFaceID`` while execution still fails with
``No module named 'insightface'``.

Upstream documents manual ``insightface`` installation (README; issue #162). The
pinned commit has no requirements.txt; pyproject.toml lists no Python deps.
``insightface`` itself requires ``onnxruntime`` (import guard in insightface).

AI Studio installs audited packages into the **same interpreter** that launches
ComfyUI (``PYTHON`` / ``sys.executable``), not into model weights.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Upstream FaceID guidance (ComfyUI_IPAdapter_plus README + issue #162).
INSIGHTFACE_PACKAGE_VERSION = "0.7.3"
# CPU onnxruntime for benchmark workflow provider=CPU; avoids gpu/cpu package clash.
ONNXRUNTIME_MIN_VERSION = "1.16.0"
FACEID_PYTHON_PROBE_PROVIDER = "CPU"


_PROBE_SCRIPT = """\
import json
import sys

payload = {
    "ok": False,
    "insightface_version": None,
    "onnxruntime_version": None,
    "providers": [],
    "error": None,
}
try:
    import onnxruntime

    payload["onnxruntime_version"] = getattr(onnxruntime, "__version__", None)
    payload["providers"] = list(onnxruntime.get_available_providers())
    provider = __PROVIDER__
    if f"{provider}ExecutionProvider" not in payload["providers"]:
        raise RuntimeError(
            f"{provider}ExecutionProvider missing (providers={payload['providers']})"
        )
    import insightface
    from insightface.app import FaceAnalysis

    payload["insightface_version"] = getattr(insightface, "__version__", None)
    payload["ok"] = True
except Exception as exc:
    payload["error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(payload))
sys.exit(0 if payload["ok"] else 1)
"""


@dataclass
class FaceidPythonDepsResult:
    ok: bool
    python_executable: str = ""
    dry_run: bool = False
    installed: bool = False
    skipped_already_satisfied: bool = False
    assessment_before: dict[str, Any] = field(default_factory=dict)
    assessment_after: dict[str, Any] = field(default_factory=dict)
    pip_command: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_comfy_python_executable() -> str:
    """Return the Python interpreter AI Studio uses for ComfyUI launch/install."""
    return os.environ.get("PYTHON", sys.executable)


def _faceid_python_packages() -> tuple[str, ...]:
    return (
        f"insightface=={INSIGHTFACE_PACKAGE_VERSION}",
        f"onnxruntime>={ONNXRUNTIME_MIN_VERSION}",
    )


def _run_python_probe(
    python_executable: str,
    *,
    provider: str = FACEID_PYTHON_PROBE_PROVIDER,
    timeout: float = 60.0,
) -> tuple[bool, dict[str, Any], str]:
    script = _PROBE_SCRIPT.replace("__PROVIDER__", repr(provider))
    try:
        proc = subprocess.run(
            [python_executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, {}, f"{type(exc).__name__}: {exc}"

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if not stdout:
        err = stderr or f"probe exited {proc.returncode} with no stdout"
        return False, {}, err
    try:
        payload = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        tail = stdout[-500:]
        err = f"invalid probe JSON ({exc}); stdout tail={tail!r}"
        if stderr:
            err += f"; stderr={stderr!r}"
        return False, {}, err
    ok = bool(payload.get("ok")) and proc.returncode == 0
    if not ok and not payload.get("error"):
        payload["error"] = stderr or f"probe exit code {proc.returncode}"
    return ok, payload, str(payload.get("error") or "")


def assess_faceid_python_runtime(
    *,
    python_executable: str | None = None,
    provider: str = FACEID_PYTHON_PROBE_PROVIDER,
) -> dict[str, Any]:
    """Assess importability of FaceID Python deps in the ComfyUI interpreter."""
    exe = str(python_executable or default_comfy_python_executable())
    ok, payload, err = _run_python_probe(exe, provider=provider)
    insightface_version = payload.get("insightface_version")
    onnxruntime_version = payload.get("onnxruntime_version")
    if ok:
        return {
            "status": "VERIFIED",
            "verified": True,
            "notes": (
                f"insightface {insightface_version or INSIGHTFACE_PACKAGE_VERSION} importable "
                f"via {exe}; onnxruntime {onnxruntime_version or '?'} "
                f"with {provider}ExecutionProvider"
            ),
            "python_executable": exe,
            "insightface_version": insightface_version,
            "onnxruntime_version": onnxruntime_version,
            "providers": list(payload.get("providers") or []),
            "required_provider": provider,
            "benchmark_execution_tested": False,
        }
    err_l = (err or "").lower()
    if "modulenotfounderror" in err_l or "no module named" in err_l:
        status = "MISSING"
    elif "importerror" in err_l:
        status = "IMPORT_ERROR"
    else:
        status = "ERROR"
    return {
        "status": status,
        "verified": False,
        "notes": err or "FaceID Python runtime probe failed",
        "python_executable": exe,
        "insightface_version": insightface_version,
        "onnxruntime_version": onnxruntime_version,
        "providers": list(payload.get("providers") or []),
        "required_provider": provider,
        "benchmark_execution_tested": False,
    }


def ensure_faceid_python_runtime(
    *,
    python_executable: str | None = None,
    provider: str = FACEID_PYTHON_PROBE_PROVIDER,
    dry_run: bool = False,
) -> FaceidPythonDepsResult:
    """Install audited FaceID Python packages when missing (idempotent)."""
    exe = str(python_executable or default_comfy_python_executable())
    result = FaceidPythonDepsResult(ok=False, python_executable=exe, dry_run=dry_run)
    before = assess_faceid_python_runtime(python_executable=exe, provider=provider)
    result.assessment_before = before
    if before.get("verified"):
        result.ok = True
        result.skipped_already_satisfied = True
        result.assessment_after = before
        result.messages.append("FaceID Python runtime already satisfied; no pip install needed.")
        return result

    packages = list(_faceid_python_packages())
    pip_cmd = [exe, "-m", "pip", "install", "-q", *packages]
    result.pip_command = pip_cmd
    if dry_run:
        result.messages.append(
            "DRY-RUN: would install audited FaceID Python packages: "
            + ", ".join(packages)
        )
        result.ok = not result.errors
        return result

    try:
        proc = subprocess.run(pip_cmd, capture_output=True, text=True, check=False, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result.errors.append(f"ERROR: FaceID Python dependency install failed: {exc}")
        return result
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        result.errors.append(
            "ERROR: pip install failed for FaceID Python runtime "
            f"(exit {proc.returncode}): {detail or 'no output'}"
        )
        return result

    result.installed = True
    after = assess_faceid_python_runtime(python_executable=exe, provider=provider)
    result.assessment_after = after
    if after.get("verified"):
        result.ok = True
        result.messages.append(
            "FaceID Python runtime installed and verified "
            f"(insightface {after.get('insightface_version') or INSIGHTFACE_PACKAGE_VERSION})."
        )
    else:
        result.errors.append(
            "ERROR: FaceID Python packages installed but import probe still failed: "
            f"{after.get('notes')}"
        )
    return result
