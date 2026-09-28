#!/usr/bin/env python3
"""Durable ComfyUI process launch: core HTTP readiness decoupled from Colab proxy.

Background-capable. Does not require eval_js / proxyPort for core startup.
Proxy URL acquisition is optional and must never invalidate a healthy local process.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .comfyui_userdata import DEFAULT_COMFY_BASE_URL, comfyui_reachable, normalize_comfy_base_url

DEFAULT_COMFY_PORT = 8188
DEFAULT_HEALTH_TIMEOUT_S = 300.0
DEFAULT_HEALTH_POLL_S = 1.0
PROCESS_STATE_NAME = "comfyui_process.json"


@dataclass
class ComfyCoreLaunchResult:
    ok: bool
    pid: int | None = None
    port: int = DEFAULT_COMFY_PORT
    base_url: str = DEFAULT_COMFY_BASE_URL
    log_path: str | None = None
    state_path: str | None = None
    http_status: int | None = None
    already_running: bool = False
    proxy_url: str | None = None
    proxy_error: str | None = None
    timed_out: bool = False
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_runtime_state_dir() -> Path:
    return Path("/content/ai-studio-runtime")


def comfy_process_state_path(runtime_dir: Path | None = None) -> Path:
    return (runtime_dir or default_runtime_state_dir()) / PROCESS_STATE_NAME


def probe_comfy_http(
    base_url: str = DEFAULT_COMFY_BASE_URL,
    *,
    timeout: float = 3.0,
) -> int | None:
    """Return HTTP status for /system_stats, or None if unreachable."""
    base = normalize_comfy_base_url(base_url)
    for url in (f"{base}/system_stats", f"{base}/api/system_stats"):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return int(resp.status)
        except urllib.error.HTTPError as exc:
            return int(exc.code)
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return None


def wait_for_comfy_http(
    base_url: str = DEFAULT_COMFY_BASE_URL,
    *,
    timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
    poll_s: float = DEFAULT_HEALTH_POLL_S,
    proc: subprocess.Popen | None = None,
    probe_fn: Callable[[str], int | None] | None = None,
) -> tuple[int | None, bool]:
    """Poll until HTTP 200 or timeout / process exit.

    Returns (status_or_None, timed_out).
    """
    deadline = time.time() + max(0.1, float(timeout_s))
    last: int | None = None

    def _default_probe(url: str) -> int | None:
        remaining = max(0.05, deadline - time.time())
        return probe_comfy_http(url, timeout=min(1.0, remaining))

    probe = probe_fn or _default_probe
    while time.time() < deadline:
        last = probe(base_url)
        if last == 200:
            return last, False
        if proc is not None and proc.poll() is not None:
            return last, False
        time.sleep(max(0.05, float(poll_s)))
    return last, True


def write_process_state(
    state_path: Path,
    *,
    pid: int | None,
    port: int,
    log_path: Path | None,
    http_status: int | None,
    extra: dict[str, Any] | None = None,
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "service": "comfyui",
        "pid": pid,
        "port": port,
        "log_path": str(log_path) if log_path else None,
        "http_status": http_status,
        "base_url": f"http://127.0.0.1:{port}",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if extra:
        payload.update(extra)
    state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_process_state(state_path: Path) -> dict[str, Any] | None:
    if not state_path.is_file():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def pid_is_alive(pid: int | None) -> bool:
    if pid is None or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def try_obtain_colab_proxy_url(
    port: int,
    *,
    eval_js_fn: Callable[[str], Any] | None = None,
) -> tuple[str | None, str | None]:
    """Optional Colab proxy URL. Failure must not affect core health."""
    if eval_js_fn is None:
        return None, "eval_js_unavailable"
    try:
        url = eval_js_fn(f"google.colab.kernel.proxyPort({int(port)})")
    except Exception as exc:  # noqa: BLE001 — proxy is optional
        return None, f"{type(exc).__name__}:{exc}"
    text = str(url or "").strip()
    if not text:
        return None, "empty_proxy_url"
    return text, None


def stop_comfyui_process(
    *,
    proc: subprocess.Popen | None = None,
    state_path: Path | None = None,
    grace_s: float = 20.0,
) -> dict[str, Any]:
    """Terminate a tracked ComfyUI process (Popen and/or state-file PID)."""
    out: dict[str, Any] = {"stopped": False, "pid": None, "messages": []}
    pid = None
    if proc is not None and proc.poll() is None:
        pid = proc.pid
        out["pid"] = pid
        try:
            proc.terminate()
            proc.wait(timeout=grace_s)
            out["stopped"] = True
            out["messages"].append("terminated_popen")
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
            out["stopped"] = True
            out["messages"].append("killed_popen")
        except Exception as exc:  # noqa: BLE001
            out["messages"].append(f"popen_stop_error:{exc}")
    state_path = state_path or comfy_process_state_path()
    state = read_process_state(state_path)
    if state and state.get("pid") and not out["stopped"]:
        pid = int(state["pid"])
        out["pid"] = pid
        if pid_is_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                deadline = time.time() + grace_s
                while time.time() < deadline and pid_is_alive(pid):
                    time.sleep(0.2)
                if pid_is_alive(pid):
                    os.kill(pid, signal.SIGKILL)
                out["stopped"] = True
                out["messages"].append("signaled_state_pid")
            except OSError as exc:
                out["messages"].append(f"signal_error:{exc}")
    if state_path.is_file():
        try:
            state_path.unlink()
            out["messages"].append("cleared_state_file")
        except OSError:
            pass
    return out


def start_comfyui_core(
    *,
    comfyui_dir: Path,
    port: int = DEFAULT_COMFY_PORT,
    log_path: Path | None = None,
    runtime_dir: Path | None = None,
    python_executable: str | None = None,
    repo_root: Path | None = None,
    health_timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
    health_poll_s: float = DEFAULT_HEALTH_POLL_S,
    stop_existing: bool = True,
    obtain_proxy: bool = False,
    eval_js_fn: Callable[[str], Any] | None = None,
    start_new_session: bool = True,
    popen_fn: Callable[..., subprocess.Popen] | None = None,
    probe_fn: Callable[[str], int | None] | None = None,
    wait_fn: Callable[..., tuple[int | None, bool]] | None = None,
) -> ComfyCoreLaunchResult:
    """Start ComfyUI and wait for local HTTP 200. Proxy is optional."""
    result = ComfyCoreLaunchResult(ok=False, port=int(port))
    comfyui_dir = Path(comfyui_dir)
    runtime_dir = Path(runtime_dir) if runtime_dir else default_runtime_state_dir()
    state_path = comfy_process_state_path(runtime_dir)
    result.state_path = str(state_path)
    base_url = f"http://127.0.0.1:{int(port)}"
    result.base_url = base_url
    probe = probe_fn or probe_comfy_http
    popen = popen_fn or subprocess.Popen

    if not comfyui_dir.is_dir():
        result.errors.append(f"ComfyUI directory missing: {comfyui_dir}")
        return result

    existing = probe(base_url)
    if existing == 200:
        result.ok = True
        result.already_running = True
        result.http_status = 200
        result.messages.append("ComfyUI already healthy on local HTTP")
        write_process_state(
            state_path,
            pid=(read_process_state(state_path) or {}).get("pid"),
            port=int(port),
            log_path=Path(log_path) if log_path else None,
            http_status=200,
            extra={"already_running": True},
        )
        if obtain_proxy:
            url, err = try_obtain_colab_proxy_url(int(port), eval_js_fn=eval_js_fn)
            result.proxy_url = url
            result.proxy_error = err
            if err:
                result.messages.append(f"proxy optional failure (core still healthy): {err}")
        return result

    if stop_existing:
        stop_comfyui_process(state_path=state_path)

    logs_dir = runtime_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(log_path) if log_path else (logs_dir / "comfyui.log")
    result.log_path = str(log_path)
    log_file = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 — owned by child lifetime

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if repo_root is not None:
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")

    cmd = [
        python_executable or sys.executable,
        "main.py",
        "--listen",
        "127.0.0.1",
        "--port",
        str(int(port)),
    ]
    try:
        proc = popen(
            cmd,
            cwd=str(comfyui_dir),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=bool(start_new_session),
        )
    except OSError as exc:
        result.errors.append(f"Popen failed: {exc}")
        try:
            log_file.close()
        except Exception:
            pass
        return result

    result.pid = int(proc.pid)
    result.messages.append(f"spawned ComfyUI pid={proc.pid} start_new_session={start_new_session}")
    if wait_fn is not None:
        status, timed_out = wait_fn(
            base_url,
            timeout_s=health_timeout_s,
            poll_s=health_poll_s,
            proc=proc,
        )
    else:
        status, timed_out = wait_for_comfy_http(
            base_url,
            timeout_s=health_timeout_s,
            poll_s=health_poll_s,
            proc=proc,
            probe_fn=probe,
        )
    result.http_status = status
    result.timed_out = bool(timed_out)
    write_process_state(
        state_path,
        pid=result.pid,
        port=int(port),
        log_path=log_path,
        http_status=status,
        extra={"start_new_session": bool(start_new_session)},
    )

    if status == 200:
        result.ok = True
        result.messages.append("local HTTP readiness: system_stats=200")
    else:
        if timed_out:
            result.errors.append(
                f"ComfyUI HTTP health timed out after {health_timeout_s}s "
                f"(last_status={status!r}). Check {log_path}"
            )
        elif proc.poll() is not None:
            result.errors.append(
                f"ComfyUI exited early rc={proc.returncode}. Check {log_path}"
            )
        else:
            result.errors.append(f"ComfyUI not healthy (status={status!r}). Check {log_path}")

    # Proxy is informational only — never flip ok=False for proxy failures.
    if obtain_proxy:
        url, err = try_obtain_colab_proxy_url(int(port), eval_js_fn=eval_js_fn)
        result.proxy_url = url
        result.proxy_error = err
        if err:
            result.messages.append(f"proxy optional failure (core health unchanged): {err}")
        elif url:
            result.messages.append("proxy URL obtained")

    # Retain Popen on result for callers that want the handle; process is detached
    # via start_new_session so returning from this function does not kill it.
    result._proc = proc  # type: ignore[attr-defined]
    return result


def core_readiness_ok(
    *,
    comfy_http_status: int | None,
    watcher_status: dict[str, Any] | None,
) -> bool:
    """Background readiness: local Comfy HTTP 200 + OW current_runtime (+ fresh heartbeat)."""
    if comfy_http_status != 200:
        return False
    if not watcher_status:
        return False
    if watcher_status.get("ownership_state") != "current_runtime":
        return False
    if watcher_status.get("watcher") not in ("OK", "WARN"):
        return False
    # Prefer fresh heartbeat when the field is present.
    if "heartbeat_fresh" in watcher_status and watcher_status.get("heartbeat_fresh") is not True:
        return False
    return True
