#!/usr/bin/env python3
"""Regression simulations for safe Colab CDP cell-entry primitives."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.colab_cdp_cells import (
    CellWriteMode,
    js_click_cell_run,
    js_set_cell_source,
    normalize_cell_source,
    plan_cell_source_write,
    sources_equivalent,
    verify_cell_source_before_run,
    would_duplicate_on_append,
)


def _pass(results: list[tuple[str, str]], label: str) -> None:
    results.append(("PASS", label))
    print(f"  [PASS] {label}")


def _assert_true(label: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {label}")


def main() -> int:
    results: list[tuple[str, str]] = []

    # a) replacing existing source -> atomic REPLACE (setText path), never caret append
    broken = "control_panel()control_panel()"
    plan_fix = plan_cell_source_write(broken, "control_panel()")
    _assert_true("a replace mode", plan_fix.mode == CellWriteMode.REPLACE_SELECT_ALL)
    _assert_true("a setText helper emits setText()", "setText(" in js_set_cell_source(14, "control_panel()"))
    _assert_true(
        "a setText payload exact",
        '"control_panel()"' in js_set_cell_source(14, "control_panel()"),
    )
    _pass(results, "a. replacing existing source uses atomic setText plan")

    # b) running without source mutation
    plan_run = plan_cell_source_write(
        'print("CDP_SAFE_CELL_EXEC_OK")', 'print("CDP_SAFE_CELL_EXEC_OK")'
    )
    _assert_true("b RUN_EXISTING", plan_run.mode == CellWriteMode.RUN_EXISTING)
    ok, _ = verify_cell_source_before_run(
        'print("CDP_SAFE_CELL_EXEC_OK")', 'print("CDP_SAFE_CELL_EXEC_OK")'
    )
    _assert_true("b verify gate", ok)
    run_js = js_click_cell_run(14)
    _assert_true("b uses colab-run-button", "colab-run-button" in run_js)
    _assert_true("b does not insertText", "insertText" not in run_js)
    _assert_true("b does not setText during run", "setText(" not in run_js)
    _pass(results, "b. running without source mutation (RUN_EXISTING + run button)")

    # c) retry/run twice leaves source unchanged (idempotent plan)
    src = 'print("CDP_SAFE_CELL_EXEC_OK")'
    p1 = plan_cell_source_write(src, src)
    p2 = plan_cell_source_write(src, src)
    _assert_true("c first RUN_EXISTING", p1.mode == CellWriteMode.RUN_EXISTING)
    _assert_true("c second RUN_EXISTING", p2.mode == CellWriteMode.RUN_EXISTING)
    _assert_true("c source identity", sources_equivalent(src, src))
    _pass(results, "c. retry/run twice leaves source unchanged (idempotent)")

    # d) duplicated control_panel() cannot recur via planned writes
    _assert_true(
        "d append would duplicate detected",
        would_duplicate_on_append("control_panel()", "control_panel()"),
    )
    equal = plan_cell_source_write("control_panel()", "control_panel()")
    _assert_true("d equal => no typing", equal.mode == CellWriteMode.RUN_EXISTING)
    repair = plan_cell_source_write("control_panel()control_panel()", "control_panel()")
    _assert_true("d broken => replace not append", repair.mode == CellWriteMode.REPLACE_SELECT_ALL)
    naive = normalize_cell_source("control_panel()") + "control_panel()"
    _assert_true("d naive append is the defect", naive == "control_panel()control_panel()")
    # Simulated correct replace outcome
    after_replace = "control_panel()"
    _assert_true(
        "d post-replace is RUN_EXISTING",
        plan_cell_source_write(after_replace, "control_panel()").mode
        == CellWriteMode.RUN_EXISTING,
    )
    bad_verify, _ = verify_cell_source_before_run(
        "control_panel()control_panel()", "control_panel()"
    )
    _assert_true("d verify blocks dup before run", not bad_verify)
    _pass(results, "d. duplicated control_panel() cannot recur via planned path")

    # extras kept from prior suite
    abort = plan_cell_source_write("x", "")
    _assert_true("empty desired aborts", abort.mode == CellWriteMode.ABORT_AMBIGUOUS)
    _pass(results, "empty desired source aborts")

    print(f"\nsimulate_colab_cdp_cells: {len(results)} checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
