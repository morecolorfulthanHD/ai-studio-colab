#!/usr/bin/env python3
"""PATH C background launch hardening simulations (deterministic, no GPU/Colab).

Proves:
  A. PATH C launch dependency graph excludes FaceID/InsightFace/InstantID/ReActor
  B. PATH C does not execute FaceID albucore/median_blur probe
  C. Comfy core launch succeeds when proxy/eval_js raises
  D. proxy URL failure leaves local Comfy healthy
  E. launched Comfy process remains alive after launcher returns
  F. HTTP health timeout fails cleanly and boundedly
  G. OutputWatcher readiness requires current_runtime + heartbeat
  H. InstantID remains BLOCKED_FOR_COMMERCIAL
  I. option 11 remains blocked (menu refuse / InstantID gates)
  J. Package 4.12.3 related simulations remain green (suite registered)
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.comfyui_process import (  # noqa: E402
    core_readiness_ok,
    start_comfyui_core,
    try_obtain_colab_proxy_url,
    wait_for_comfy_http,
)
from core.runtime.identity_architecture_plugin import (  # noqa: E402
    ARCHITECTURE_IPADAPTER_PLUS_FACE,
    STATUS_BLOCKED_FOR_COMMERCIAL,
    is_instantid_production_blocked,
)
from core.runtime.launch_profiles import (  # noqa: E402
    FACEID_ERA_CAPABILITIES,
    FORBIDDEN_FOR_PATH_C_LAUNCH,
    install_sh_skip_faceid_era,
    launch_profile_for_architecture,
    path_c_forbidden_capabilities_present,
    path_c_launch_excludes_forbidden_deps,
    resolve_launch_architecture,
)
from core.runtime.registry_loader import find_repo_root  # noqa: E402


def _pass(results: list[tuple[str, str]], label: str) -> None:
    results.append(("PASS", label))
    print(f"  [PASS] {label}")


def _assert_true(label: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {label}")


def _assert_equal(label: str, a: object, b: object) -> None:
    if a != b:
        raise AssertionError(f"FAIL: {label} ({a!r} != {b!r})")


def _assert_false(label: str, cond: bool) -> None:
    if cond:
        raise AssertionError(f"FAIL: {label}")


class _FakeProc:
    def __init__(self, pid: int = 4242):
        self.pid = pid
        self._alive = True
        self.returncode = None

    def poll(self):
        return None if self._alive else (self.returncode or 1)

    def terminate(self):
        self._alive = False
        self.returncode = 0

    def kill(self):
        self._alive = False
        self.returncode = -9

    def wait(self, timeout=None):
        self._alive = False
        return self.returncode or 0


def main() -> int:
    results: list[tuple[str, str]] = []
    repo_root = find_repo_root(Path(__file__))

    # --- A: PATH C dependency graph excludes forbidden deps ---
    profile = launch_profile_for_architecture(ARCHITECTURE_IPADAPTER_PLUS_FACE)
    _assert_true("A skip faceid era", profile.skip_faceid_era_probes)
    _assert_false("A require faceid python", profile.require_faceid_python_deps)
    _assert_false("A require faceid bridge", profile.require_faceid_runtime_bridge)
    _assert_false("A require buffalo", profile.require_faceid_buffalo_bridge)
    _assert_false("A require reactor", profile.require_reactor_insightface_bridge)
    _assert_true("A excludes helper", path_c_launch_excludes_forbidden_deps(profile))
    _assert_false(
        "A no forbidden caps",
        path_c_forbidden_capabilities_present(set()),
    )
    _assert_true(
        "A detects forbidden",
        path_c_forbidden_capabilities_present({"faceid", "insightface"}),
    )
    for name in ("faceid", "insightface", "instantid", "reactor", "buffalo", "antelope"):
        _assert_true(f"A forbidden contains {name}", name in FORBIDDEN_FOR_PATH_C_LAUNCH)
    _assert_true("A faceid_python in era set", "faceid_python_deps" in FACEID_ERA_CAPABILITIES)
    _pass(results, "A: PATH C launch graph excludes FaceID/InsightFace/InstantID/ReActor")

    # --- B: PATH C does not execute albucore/median_blur probe ---
    _assert_true(
        "B install_sh skip",
        install_sh_skip_faceid_era(ARCHITECTURE_IPADAPTER_PLUS_FACE),
    )
    install_sh = (repo_root / "core/comfyui/install.sh").read_text(encoding="utf-8")
    _assert_true("B has --identity-architecture", "--identity-architecture" in install_sh)
    _assert_true("B has SKIP_FACEID_ERA", "SKIP_FACEID_ERA" in install_sh)
    _assert_true(
        "B skips albucore probe text",
        "albucore median_blur probe" in install_sh
        or "albucore/median_blur" in install_sh
        or "Skipping FaceID Python deps" in install_sh,
    )
    # Simulate the bash gate: PATH C must not invoke ensure_faceid_python_deps.
    # Prove by parsing the skip branch precedes the die gate when SKIP=1.
    skip_pos = install_sh.find('SKIP_FACEID_ERA}" == "1"')
    if skip_pos < 0:
        skip_pos = install_sh.find('SKIP_FACEID_ERA" == "1"')
    py_deps_pos = install_sh.find("ensure_faceid_python_deps.py")
    _assert_true("B skip gate present", skip_pos >= 0)
    _assert_true("B python deps still exist for legacy", py_deps_pos >= 0)
    _assert_true("B skip before python deps branch", skip_pos < py_deps_pos)
    nodes_src = (repo_root / "core/comfyui/install_nodes.py").read_text(encoding="utf-8")
    _assert_true("B install_nodes architecture flag", "--identity-architecture" in nodes_src)
    _assert_true("B install_nodes skip branch", "skip_faceid_era_probes" in nodes_src)
    _pass(results, "B: PATH C skips FaceID albucore/median_blur probe")

    # --- C/D: core launch succeeds when proxy/eval_js raises ---
    def _raising_eval_js(_code: str):
        raise RuntimeError("MessageError: eval_js unavailable in background kernel.execute")

    fake = _FakeProc(pid=9001)
    probes = {"n": 0}

    def _probe(_url: str):
        probes["n"] += 1
        return 200 if probes["n"] >= 2 else None

    def _popen(*_a, **_k):
        return fake

    comfy_dir = repo_root / "core"  # any existing dir; spawn is mocked
    result = start_comfyui_core(
        comfyui_dir=comfy_dir,
        port=8188,
        runtime_dir=repo_root / ".tmp_sim_comfy_state",
        health_timeout_s=5.0,
        health_poll_s=0.01,
        obtain_proxy=True,
        eval_js_fn=_raising_eval_js,
        start_new_session=True,
        stop_existing=False,
        popen_fn=_popen,
        probe_fn=_probe,
    )
    _assert_true("C core ok despite eval_js raise", result.ok)
    _assert_equal("C http 200", result.http_status, 200)
    _assert_true("C proxy error recorded", bool(result.proxy_error))
    _assert_equal("C pid set", result.pid, 9001)
    _assert_true("D core still ok after proxy fail", result.ok and result.http_status == 200)
    url, err = try_obtain_colab_proxy_url(8188, eval_js_fn=_raising_eval_js)
    _assert_equal("D proxy url none", url, None)
    _assert_true("D proxy err", err is not None)
    _pass(results, "C: Comfy core launch succeeds when proxy/eval_js raises")
    _pass(results, "D: proxy failure leaves local Comfy healthy")

    # --- E: process remains alive after launcher returns ---
    _assert_true("E fake still alive", fake.poll() is None)
    e_probes = {"n": 0}

    def _probe_e(_url: str):
        e_probes["n"] += 1
        # First call is pre-spawn existing check → miss; later → healthy.
        return 200 if e_probes["n"] >= 2 else None

    e_proc = _FakeProc(pid=9002)
    alive_after = start_comfyui_core(
        comfyui_dir=comfy_dir,
        port=8188,
        runtime_dir=repo_root / ".tmp_sim_comfy_state",
        health_timeout_s=2.0,
        health_poll_s=0.01,
        obtain_proxy=False,
        start_new_session=True,
        stop_existing=False,
        popen_fn=lambda *_a, **_k: e_proc,
        probe_fn=_probe_e,
    )
    retained = getattr(alive_after, "_proc", None)
    _assert_true("E retained proc", retained is not None and retained.poll() is None)
    _assert_true("E launcher returned ok", alive_after.ok)
    _assert_false("E not already_running shortcut", alive_after.already_running)
    _pass(results, "E: launched Comfy process remains alive after launcher returns")

    # --- F: HTTP health timeout fails cleanly and boundedly ---
    t0 = time.time()
    status, timed_out = wait_for_comfy_http(
        "http://127.0.0.1:9",
        timeout_s=0.35,
        poll_s=0.05,
        proc=None,
        probe_fn=lambda _u: None,
    )
    elapsed = time.time() - t0
    _assert_true("F timed out", timed_out)
    _assert_true("F bounded", elapsed < 2.0)
    fail = start_comfyui_core(
        comfyui_dir=comfy_dir,
        port=9,
        runtime_dir=repo_root / ".tmp_sim_comfy_state",
        health_timeout_s=0.3,
        health_poll_s=0.05,
        obtain_proxy=False,
        stop_existing=False,
        popen_fn=lambda *_a, **_k: _FakeProc(pid=9003),
        probe_fn=lambda _u: None,
        wait_fn=lambda *_a, **_k: (None, True),
    )
    _assert_false("F launch not ok", fail.ok)
    _assert_true("F timed_out flag", fail.timed_out)
    _assert_true("F error mentions timeout", any("timed out" in e.lower() for e in fail.errors))
    _pass(results, "F: HTTP health timeout fails cleanly and boundedly")

    # --- G: OutputWatcher readiness ---
    _assert_false(
        "G missing watcher",
        core_readiness_ok(comfy_http_status=200, watcher_status=None),
    )
    _assert_false(
        "G wrong ownership",
        core_readiness_ok(
            comfy_http_status=200,
            watcher_status={
                "watcher": "OK",
                "ownership_state": "stale_runtime",
                "heartbeat_fresh": True,
            },
        ),
    )
    _assert_false(
        "G stale heartbeat",
        core_readiness_ok(
            comfy_http_status=200,
            watcher_status={
                "watcher": "OK",
                "ownership_state": "current_runtime",
                "heartbeat_fresh": False,
            },
        ),
    )
    _assert_true(
        "G ready",
        core_readiness_ok(
            comfy_http_status=200,
            watcher_status={
                "watcher": "OK",
                "ownership_state": "current_runtime",
                "heartbeat_fresh": True,
            },
        ),
    )
    _pass(results, "G: OutputWatcher readiness requires current_runtime + heartbeat")

    # --- H: InstantID BLOCKED_FOR_COMMERCIAL ---
    blocked_flag, blocked_detail = is_instantid_production_blocked(repo_root)
    _assert_true("H blocked helper", blocked_flag is True)
    from core.runtime.identity_architecture_benchmark import assess_instantid_license_gate

    gate = assess_instantid_license_gate(repo_root)
    status = gate.get("overall_status") or gate.get("status")
    _assert_equal("H gate status", status, STATUS_BLOCKED_FOR_COMMERCIAL)
    _assert_equal("H promo", gate.get("promotion_allowed"), False)
    _pass(results, "H: InstantID remains BLOCKED_FOR_COMMERCIAL")

    # --- I: option 11 remains blocked (Characters refuse InstantID / promo false) ---
    nb = json.loads(
        (repo_root / "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb").read_text(
            encoding="utf-8"
        )
    )
    nb_src = "\n".join("".join(c.get("source", [])) for c in nb["cells"])
    _assert_true(
        "I option 11 refuse present",
        "Characters option 11 refused" in nb_src or "promotion_allowed=false" in nb_src,
    )
    _assert_true("I start_comfyui_core wired", "start_comfyui_core" in nb_src)
    _assert_true("I identity-architecture wired", "--identity-architecture" in nb_src)
    # Resolve live architecture from config defaults to PATH C
    live = resolve_launch_architecture(None, env={}, settings={}, repo_root=repo_root)
    _assert_equal("I live arch PATH C", live, ARCHITECTURE_IPADAPTER_PLUS_FACE)
    _pass(results, "I: option 11 InstantID/promo gates remain; PATH C is live launch arch")

    # --- J: package4123 suite list includes this sim ---
    from core.runtime.package4123_qa import DEFAULT_PACKAGE4123_SUITES

    _assert_true(
        "J suite registered",
        "simulate_path_c_background_launch.py" in DEFAULT_PACKAGE4123_SUITES,
    )
    _pass(results, "J: Package 4.12.3 suite list includes PATH C background launch sim")

    # cleanup temp state dir
    state_dir = repo_root / ".tmp_sim_comfy_state"
    if state_dir.is_dir():
        for p in state_dir.rglob("*"):
            if p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass

    passed = sum(1 for s, _ in results if s == "PASS")
    total = len(results)
    print(f"\nRESULT: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
