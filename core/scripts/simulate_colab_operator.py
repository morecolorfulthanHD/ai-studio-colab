#!/usr/bin/env python3
"""Deterministic Colab operator state-machine simulations."""

from __future__ import annotations

import sys
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.colab_operator import (
    ColabOperatorSession,
    OperatorEvent,
    OperatorState,
    assert_expected_menu_title,
    is_never_auto,
    load_operator_config,
    may_auto_reconnect,
    may_change_gpu_without_asking,
    navigation_sequence,
    recommend_next_action,
)
from core.runtime.registry_loader import find_repo_root


def _pass(results: list[tuple[str, str]], label: str) -> None:
    results.append(("PASS", label))
    print(f"  [PASS] {label}")


def _assert_true(label: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {label}")


def _assert_equal(label: str, a: object, b: object) -> None:
    if a != b:
        raise AssertionError(f"FAIL: {label} ({a!r} != {b!r})")


def _run(session: ColabOperatorSession, event: OperatorEvent) -> None:
    result = session.apply(event)
    if not result.ok:
        raise AssertionError(f"FAIL: transition {event.value}: {result.errors}")


def main() -> int:
    results: list[tuple[str, str]] = []
    repo_root = find_repo_root(script_file=Path(__file__))
    cfg = load_operator_config(repo_root)
    url = (cfg.get("canonical_notebook") or {}).get("colab_url") or ""
    _assert_true("canonical colab URL configured", "colab.research.google.com" in url)
    _assert_true(
        "canonical path is GitHub notebook",
        "AI_Studio_Control_Panel_Colab.ipynb" in url,
    )
    _assert_true("may_auto_reconnect", may_auto_reconnect(cfg))
    _assert_true("GPU change requires ask", not may_change_gpu_without_asking(cfg))
    _assert_true("Full Reset never auto", is_never_auto("Full Reset", cfg))
    _assert_true("Drive deletion never auto", is_never_auto("drive_deletion", cfg))
    _assert_true("history deletion never auto", is_never_auto("history_deletion", cfg))
    _pass(results, "operator config loads; destructive actions protected")

    # 1. notebook opens
    s = ColabOperatorSession(config=cfg)
    _assert_equal("start NOT_OPEN", s.state, OperatorState.NOT_OPEN)
    _run(s, OperatorEvent.NOTEBOOK_OPENED)
    _assert_equal("1 notebook opens", s.state, OperatorState.COLAB_OPEN)
    _pass(results, "1. notebook opens -> COLAB_OPEN")

    # 2. disconnected -> connect click does NOT imply connected
    s2 = ColabOperatorSession(config=cfg)
    _run(s2, OperatorEvent.NOTEBOOK_OPENED)
    _run(s2, OperatorEvent.RUNTIME_DISCONNECTED)
    _assert_equal("disconnected", s2.state, OperatorState.DISCONNECTED)
    r_click = s2.apply(OperatorEvent.CONNECT_CLICKED)
    _assert_true("2 connect click ok", r_click.ok)
    _assert_equal("2 still DISCONNECTED after click", s2.state, OperatorState.DISCONNECTED)
    _assert_true(
        "2 wait-for-evidence message",
        any("wait for runtime-connected" in m.lower() for m in r_click.messages),
    )
    _run(s2, OperatorEvent.RUNTIME_CONNECTED)
    _assert_equal("2 connected after evidence", s2.state, OperatorState.CONNECTED)
    _pass(results, "2. disconnected -> CONNECT_CLICKED stays; RUNTIME_CONNECTED -> CONNECTED")

    # 3. connected -> repo sync
    _run(s2, OperatorEvent.REPO_SYNC_OK)
    _assert_equal("3 repo synced", s2.state, OperatorState.REPO_SYNCED)
    _pass(results, "3. connected -> repo sync -> REPO_SYNCED")

    # 4. repo synced -> Run all
    _run(s2, OperatorEvent.RUN_ALL_DONE)
    _assert_equal("4 AI Studio ready", s2.state, OperatorState.AI_STUDIO_READY)
    _pass(results, "4. repo synced -> Run all -> AI_STUDIO_READY")

    # 5. Full Launch warning but no fail -> proceed
    _run(s2, OperatorEvent.FULL_LAUNCH_STARTED)
    r5 = s2.apply(OperatorEvent.FULL_LAUNCH_WARNINGS)
    _assert_true("5 ok", r5.ok)
    _assert_equal("5 ready despite warnings", s2.state, OperatorState.FULL_LAUNCH_READY)
    _assert_true("5 not failed", s2.state != OperatorState.FAILED)
    _pass(results, "5. Full Launch warnings -> FULL_LAUNCH_READY")

    # 6. Full Launch fail -> stop
    s6 = ColabOperatorSession(config=cfg)
    for ev in (
        OperatorEvent.NOTEBOOK_OPENED,
        OperatorEvent.RUNTIME_CONNECTED,
        OperatorEvent.REPO_SYNC_OK,
        OperatorEvent.RUN_ALL_DONE,
        OperatorEvent.FULL_LAUNCH_STARTED,
    ):
        _run(s6, ev)
    r6 = s6.apply(OperatorEvent.FULL_LAUNCH_FAILED)
    _assert_true("6 transition ok", r6.ok)
    _assert_equal("6 FAILED", s6.state, OperatorState.FAILED)
    _assert_true("6 stopped", r6.stopped)
    _pass(results, "6. Full Launch fail -> FAILED stop")

    # 7. auth required -> stop
    s7 = ColabOperatorSession(config=cfg)
    _run(s7, OperatorEvent.NOTEBOOK_OPENED)
    r7 = s7.apply(OperatorEvent.AUTH_BLOCKER_SEEN)
    _assert_equal("7 AUTH_REQUIRED", s7.state, OperatorState.AUTH_REQUIRED)
    _assert_true("7 human required", r7.human_required and r7.stopped)
    _pass(results, "7. auth required -> AUTH_REQUIRED stop")

    # 8. auth resolved -> resume
    r8 = s7.apply(OperatorEvent.AUTH_RESOLVED)
    _assert_true("8 ok", r8.ok)
    _assert_equal("8 resume COLAB_OPEN", s7.state, OperatorState.COLAB_OPEN)
    _pass(results, "8. auth resolved -> resume COLAB_OPEN")

    # 9. runtime dies mid-run -> reconnect/relaunch path
    s9 = ColabOperatorSession(config=cfg)
    for ev in (
        OperatorEvent.NOTEBOOK_OPENED,
        OperatorEvent.RUNTIME_CONNECTED,
        OperatorEvent.REPO_SYNC_OK,
        OperatorEvent.RUN_ALL_DONE,
        OperatorEvent.FULL_LAUNCH_STARTED,
    ):
        _run(s9, ev)
    _run(s9, OperatorEvent.RUNTIME_DIED)
    _assert_equal("9 disconnected after death", s9.state, OperatorState.DISCONNECTED)
    _run(s9, OperatorEvent.CONNECT_CLICKED)
    _assert_equal("9 still disconnected after click", s9.state, OperatorState.DISCONNECTED)
    _run(s9, OperatorEvent.RUNTIME_CONNECTED)
    _run(s9, OperatorEvent.REPO_SYNC_OK)
    _run(s9, OperatorEvent.RUN_ALL_DONE)
    _run(s9, OperatorEvent.FULL_LAUNCH_STARTED)
    _run(s9, OperatorEvent.FULL_LAUNCH_OK)
    _assert_equal("9 relaunch ready", s9.state, OperatorState.FULL_LAUNCH_READY)
    _pass(results, "9. runtime dies mid-run -> reconnect/relaunch")

    # 10. live QA HUMAN_REVIEW_REQUIRED -> stop
    s10 = ColabOperatorSession(config=cfg)
    for ev in (
        OperatorEvent.NOTEBOOK_OPENED,
        OperatorEvent.RUNTIME_CONNECTED,
        OperatorEvent.REPO_SYNC_OK,
        OperatorEvent.RUN_ALL_DONE,
        OperatorEvent.FULL_LAUNCH_STARTED,
        OperatorEvent.FULL_LAUNCH_OK,
        OperatorEvent.LIVE_QA_STARTED,
    ):
        _run(s10, ev)
    r10 = s10.apply(OperatorEvent.LIVE_QA_HUMAN_REVIEW)
    _assert_equal("10 human review", s10.state, OperatorState.HUMAN_REVIEW_REQUIRED)
    _assert_true("10 stop", r10.stopped and r10.human_required)
    _pass(results, "10. live QA HUMAN_REVIEW_REQUIRED -> stop")

    # 11. live QA completes -> COMPLETE
    s11 = ColabOperatorSession(config=cfg)
    for ev in (
        OperatorEvent.NOTEBOOK_OPENED,
        OperatorEvent.RUNTIME_CONNECTED,
        OperatorEvent.REPO_SYNC_OK,
        OperatorEvent.RUN_ALL_DONE,
        OperatorEvent.FULL_LAUNCH_STARTED,
        OperatorEvent.FULL_LAUNCH_OK,
        OperatorEvent.LIVE_QA_STARTED,
    ):
        _run(s11, ev)
    _run(s11, OperatorEvent.LIVE_QA_OK)
    _assert_equal("11 COMPLETE", s11.state, OperatorState.COMPLETE)
    _pass(results, "11. live QA completes -> COMPLETE")

    # 12. destructive action never auto-invoked
    s12 = ColabOperatorSession(config=cfg)
    _run(s12, OperatorEvent.NOTEBOOK_OPENED)
    r12 = s12.apply(OperatorEvent.DESTRUCTIVE_ACTION_REQUESTED)
    _assert_true("12 refused", not r12.ok and r12.refused_destructive)
    _assert_equal("12 state unchanged", s12.state, OperatorState.COLAB_OPEN)
    _assert_true("12 recommend mentions open/connect", "Open" in recommend_next_action(s12.state, cfg) or "Detect" in recommend_next_action(s12.state, cfg))
    _pass(results, "12. destructive action never auto-invoked")

    # FaceID / 4.13 policy markers present in config
    never = " ".join(str(x) for x in (cfg.get("never_auto") or []))
    _assert_true("FaceID re-run blocked in policy", "FaceID" in never or "ReActor" in never)
    _assert_true("4.13 blocked in policy", "4.13" in never)
    _pass(results, "policy blocks FaceID reruns and Package 4.13")

    # Live-navigation hierarchy: main 9 -> workspace 13 -> characters 11 (one-action)
    from core.runtime.colab_operator import may_satisfy_benchmark_confirmation

    cp = cfg.get("control_panel_menu") or {}
    ws = cfg.get("workspace_projects_menu") or {}
    ch = cfg.get("characters_menu") or {}
    _assert_equal("main option 9 workspace", (cp.get("workspace_projects") or {}).get("select"), "9")
    _assert_true(
        "main has no top-level characters",
        "characters" not in cp or (cp.get("characters") or {}).get("select") in (None, ""),
    )
    _assert_equal("workspace option 13 characters", (ws.get("characters") or {}).get("select"), "13")
    run_item = ch.get("run_production_identity_benchmark") or ch.get("run_instantid") or {}
    _assert_equal("characters option 11 one-action", run_item.get("select"), "11")
    _assert_equal(
        "characters option 12 status/report",
        (ch.get("status_report") or ch.get("architecture_report") or {}).get("select"),
        "12",
    )
    _assert_equal("characters option 13 advanced", (ch.get("advanced") or {}).get("select"), "13")
    seq = navigation_sequence("run_production_identity_benchmark", cfg)
    _assert_equal("nav len 3", len(seq), 3)
    _assert_equal("nav step0 menu", seq[0].get("menu"), "control_panel")
    _assert_equal("nav step0 select 9", seq[0].get("select"), "9")
    _assert_equal("nav step1 menu", seq[1].get("menu"), "workspace_projects")
    _assert_equal("nav step1 select 13", seq[1].get("select"), "13")
    _assert_equal("nav step2 menu", seq[2].get("menu"), "characters")
    _assert_equal("nav step2 select 11", seq[2].get("select"), "11")
    selects = [s.get("select") for s in seq]
    _assert_equal("nav selects 9-13-11", selects, ["9", "13", "11"])
    _assert_true("nav is not flat 13-11", selects != ["13", "11"])
    _assert_true(
        "verify workspace title helper",
        assert_expected_menu_title(
            "noise\n=== Workspace / Projects ===\n1. List",
            "=== Workspace / Projects ===",
        ),
    )
    _assert_true(
        "verify characters title helper",
        assert_expected_menu_title(
            "=== Characters (Package 4.12 / 4.12.3) ===",
            (seq[1].get("verify_title") or ""),
        ),
    )
    _assert_true(
        "missing title fails closed",
        not assert_expected_menu_title("=== AI Studio Control Panel ===", "=== Workspace / Projects ==="),
    )
    _assert_true(
        "explicit live-run may satisfy routine confirm",
        may_satisfy_benchmark_confirmation(explicit_live_run_request=True),
    )
    _assert_true(
        "opening Characters alone does not authorize GPU",
        not may_satisfy_benchmark_confirmation(explicit_live_run_request=False),
    )
    never = " ".join(str(x) for x in (cfg.get("never_auto") or []))
    _assert_true(
        "policy blocks Characters-open GPU inference",
        "Characters" in never or "opening Characters" in never,
    )
    _pass(results, "live nav hierarchy 9 -> 13 -> 11 with submenu title checks + GPU intent gates")
    print()
    passed = sum(1 for status, _ in results if status == "PASS")
    print(f"RESULT: {passed}/{len(results)} Colab operator simulations passed.")
    failed = [label for status, label in results if status != "PASS"]
    if failed:
        print("FAILED:", "; ".join(failed), file=sys.stderr)
        return 1
    print("NOTE: Operator simulation does not open a live Colab session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
