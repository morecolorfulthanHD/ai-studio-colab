#!/usr/bin/env python3
"""Simulations for one-action production identity benchmark UX (no live GPU)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.character_identity import register_character
from core.runtime.colab_operator import may_satisfy_benchmark_confirmation
from core.runtime.generation_evidence_ledger import file_sha256
from core.runtime.identity_architecture_benchmark import (
    ARCHITECTURE_INSTANTID,
    CANDIDATE_INSTANTID,
    IdentityArchitectureRecord,
    append_architecture_benchmark_record,
    architecture_ledger_path,
)
from core.runtime.identity_benchmark import SCENARIO_IDS
from core.runtime.identity_architecture_execution import ArchitectureExecutionResult
from core.runtime.production_identity_benchmark import (
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_HUMAN_REVIEW,
    confirm_gpu_execution,
    derive_workflow_status,
    find_reusable_scenario_row,
    parse_production_scenarios,
    resolve_production_character,
    run_production_identity_benchmark,
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


def _face(path: Path) -> None:
    from PIL import Image

    Image.new("RGB", (64, 64), (180, 120, 90)).save(path)


def main() -> int:
    results: list[tuple[str, str]] = []
    repo_root = find_repo_root(script_file=Path(__file__))

    # Scenario parsing defaults to S1-S4
    sc = parse_production_scenarios("S1-S4")
    _assert_equal("default S1-S4 length", len(sc), 4)
    _assert_equal("default S1-S4 ids", sc, list(SCENARIO_IDS))
    _pass(results, "I. scenario parse defaults to S1-S4")

    # Character resolve: none / one / multi
    with tempfile.TemporaryDirectory() as td:
        drive = Path(td)
        r0 = resolve_production_character(drive, interactive=False)
        _assert_true("none fails", not r0.ok)
        _assert_true("mentions register", any("Register" in e for e in r0.errors))

        face = drive / "face.png"
        _face(face)
        rec = register_character(drive, display_name="Solo", primary_face_image=face)
        r1 = resolve_production_character(drive, interactive=False)
        _assert_true("solo ok", r1.ok and r1.auto_selected)
        _assert_equal("solo id", r1.character_id, rec.character.character_id)

        face2 = drive / "face2.png"
        _face(face2)
        register_character(drive, display_name="Two", primary_face_image=face2)
        r2 = resolve_production_character(drive, interactive=False)
        _assert_true("multi needs id", not r2.ok and r2.selection_required)
        picks: list[str] = []

        def _pick(_prompt: str) -> str:
            picks.append("1")
            return "1"

        r3 = resolve_production_character(drive, interactive=True, input_fn=_pick)
        _assert_true("interactive pick ok", r3.ok)
        _assert_equal("picked first", picks, ["1"])
    _pass(results, "character resolve none/one/multi")

    # GPU confirmation gates
    ok, _ = confirm_gpu_execution(operator_live_intent=True, interactive=False)
    _assert_true("operator intent confirms", ok)
    ok2, _ = confirm_gpu_execution(user_confirmed=True, interactive=False)
    _assert_true("user confirmed", ok2)
    ok3, msg = confirm_gpu_execution(interactive=False)
    _assert_true("non-interactive without ack fails", not ok3)
    _assert_true(
        "characters-open does not authorize",
        not may_satisfy_benchmark_confirmation(explicit_live_run_request=False),
    )
    _assert_true(
        "explicit live request authorizes routine confirm",
        may_satisfy_benchmark_confirmation(explicit_live_run_request=True),
    )
    _pass(results, "G/H. GPU confirmation + Characters does not authorize")

    # Status mapping
    st, hr, _ = derive_workflow_status(
        scenario_rows=[
            {
                "ok": True,
                "scenario": SCENARIO_IDS[0],
                "automated_qa": {"automated_quality_status": "provisional_pass"},
            }
        ],
        scenarios_requested=[SCENARIO_IDS[0]],
    )
    _assert_equal("provisional -> human review", st, STATUS_HUMAN_REVIEW)
    _assert_true("hr flag", hr)
    st2, _, fr = derive_workflow_status(
        scenario_rows=[{"ok": False, "scenario": SCENARIO_IDS[0], "errors": ["boom"]}],
        scenarios_requested=[SCENARIO_IDS[0]],
        hard_failure="boom",
    )
    _assert_equal("hard fail", st2, STATUS_FAILED)
    st3, hr3, _ = derive_workflow_status(
        scenario_rows=[
            {
                "ok": True,
                "scenario": SCENARIO_IDS[0],
                "automated_qa": {"automated_quality_status": "pass"},
            }
        ],
        scenarios_requested=[SCENARIO_IDS[0]],
    )
    _assert_equal("plain pass complete", st3, STATUS_COMPLETE)
    _assert_true("no hr", not hr3)
    _pass(results, "J/K/L. status COMPLETE / HUMAN_REVIEW / FAILED mapping")

    # Resume / reuse durable evidence without duplicate GPU call
    with tempfile.TemporaryDirectory() as td:
        drive = Path(td) / "AI_Studio"
        drive.mkdir(parents=True)
        out = drive / "artifacts" / "s1.png"
        out.parent.mkdir(parents=True)
        out.write_bytes(b"durable-bytes-s1")
        sha = file_sha256(out)
        cid = "char_test_resume"
        row = IdentityArchitectureRecord(
            candidate=CANDIDATE_INSTANTID,
            architecture=ARCHITECTURE_INSTANTID,
            scenario=SCENARIO_IDS[0],
            character_id=cid,
            preparation_id="prep_x",
            prompt_id="pid_1",
            output_node_id="9",
            output_path=str(out),
            output_sha256=sha,
            automated_qa={"automated_quality_status": "provisional_pass"},
        )
        ledger = architecture_ledger_path(drive)
        append_architecture_benchmark_record(ledger, row)
        reused, amb = find_reusable_scenario_row(
            ledger, character_id=cid, scenario=SCENARIO_IDS[0]
        )
        _assert_true("reuse found", reused is not None and amb is None)
        # Ambiguous: wrong SHA
        bad = IdentityArchitectureRecord(
            candidate=CANDIDATE_INSTANTID,
            architecture=ARCHITECTURE_INSTANTID,
            scenario=SCENARIO_IDS[1],
            character_id=cid,
            preparation_id="prep_y",
            prompt_id="pid_2",
            output_node_id="9",
            output_path=str(out),
            output_sha256="0" * 64,
            automated_qa={"automated_quality_status": "provisional_pass"},
        )
        append_architecture_benchmark_record(ledger, bad)
        _, amb2 = find_reusable_scenario_row(
            ledger, character_id=cid, scenario=SCENARIO_IDS[1]
        )
        _assert_true("sha mismatch fails closed", amb2 is not None and "SHA mismatch" in (amb2 or ""))

        calls: list[str] = []

        def _fake_exec(**kwargs):
            scenario = kwargs["scenario"]
            calls.append(scenario)
            return ArchitectureExecutionResult(
                ok=True,
                scenario=scenario,
                prompt_id=f"new_{scenario}",
                output_path=str(out),
                output_sha256=sha,
                automated_qa={"automated_quality_status": "provisional_pass"},
                queue_status="ok",
            )

        # Patch RegistryLoader paths via monkeypatch of run fn using temp repo is heavy;
        # instead unit-test reuse path only here and orchestrator call with execute_fn
        # against a minimal fake by temporarily swapping drive through execute_fn only.
        # Full orchestrator needs RegistryLoader — skip full run if drive not wired;
        # covered by reuse helper + status mapping above.
        _assert_equal("no exec yet", calls, [])
    _pass(results, "M. durable reuse + SHA mismatch fail-closed")

    # Orchestrator with mocked execute_fn + temp drive via monkeypatch RegistryLoader
    from core.runtime import production_identity_benchmark as pib
    from core.runtime.registry_loader import RegistryLoader

    class _FakeBundle:
        def __init__(self, root: Path):
            self.root = root
            self.models = []
            self.nodes = []

        def path(self, key: str) -> Path:
            mapping = {
                "drive_root": self.root / "AI_Studio",
                "comfyui_runtime": self.root / "ComfyUI",
                "runtime_root": self.root / "runtime",
                "drive_workflows": self.root / "AI_Studio" / "workflows",
            }
            return mapping[key]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        drive = root / "AI_Studio"
        (root / "ComfyUI" / "input").mkdir(parents=True)
        (root / "ComfyUI" / "output").mkdir(parents=True)
        (root / "runtime" / "prepared_workflows").mkdir(parents=True)
        (drive / "workflows" / "prepared").mkdir(parents=True)
        face = drive / "face.png"
        face.parent.mkdir(parents=True, exist_ok=True)
        _face(face)
        rec = register_character(drive, display_name="Orch", primary_face_image=face)
        durable = drive / "out_s1.png"
        durable.write_bytes(b"orch-bytes")
        sha = file_sha256(durable)
        append_architecture_benchmark_record(
            architecture_ledger_path(drive),
            IdentityArchitectureRecord(
                candidate=CANDIDATE_INSTANTID,
                architecture=ARCHITECTURE_INSTANTID,
                scenario=SCENARIO_IDS[0],
                character_id=rec.character.character_id,
                preparation_id="prep_r",
                prompt_id="pid_reused",
                output_node_id="9",
                output_path=str(durable),
                output_sha256=sha,
                automated_qa={"automated_quality_status": "provisional_pass"},
            ),
        )

        executed: list[str] = []

        def _exec(**kwargs):
            scenario = kwargs["scenario"]
            executed.append(scenario)
            path = drive / f"out_{scenario}.png"
            path.write_bytes(f"bytes-{scenario}".encode())
            return ArchitectureExecutionResult(
                ok=True,
                scenario=scenario,
                prompt_id=f"p_{scenario}",
                output_path=str(path),
                output_sha256=file_sha256(path),
                automated_qa={"automated_quality_status": "provisional_pass"},
                queue_status="ok",
            )

        orig = RegistryLoader.load_all

        def _load_all(self):  # noqa: ANN001
            return _FakeBundle(root)

        RegistryLoader.load_all = _load_all  # type: ignore[method-assign]
        try:
            payload = run_production_identity_benchmark(
                repo_root,
                character_id=rec.character.character_id,
                scenarios=list(SCENARIO_IDS),
                operator_live_intent=True,
                interactive=False,
                execute_fn=_exec,
            )
        finally:
            RegistryLoader.load_all = orig  # type: ignore[method-assign]

        _assert_equal("status human review", payload["status"], STATUS_HUMAN_REVIEW)
        _assert_true("reused S1", SCENARIO_IDS[0] in payload["scenarios_skipped_reuse"])
        _assert_true("did not re-exec S1", SCENARIO_IDS[0] not in executed)
        _assert_equal("executed remaining 3", len(executed), 3)
        _assert_true("report paths", bool(payload.get("report_paths")))
        _assert_true("human instructions", "HUMAN_REVIEW_REQUIRED" in (payload.get("human_review_instructions") or ""))
    _pass(results, "I/J/K/M. one-action orchestrator reuse + HUMAN_REVIEW + reports")

    # Notebook menu labels present
    nb = json.loads(
        (repo_root / "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb").read_text(
            encoding="utf-8"
        )
    )
    src = "".join("".join(c.get("source") or []) for c in nb["cells"])
    _assert_true("menu 11 one-action", "11. Run production identity benchmark" in src)
    _assert_true("menu 12 status", "12. Production identity benchmark status / report" in src)
    _assert_true("menu 13 advanced", "13. Advanced identity benchmark tools" in src)
    _assert_true("advanced submenu", "def advanced_identity_benchmark_menu" in src)
    _assert_true(
        "old prepare not top-level 11",
        "11. Prepare production identity benchmark" not in src,
    )
    _pass(results, "Characters menu one-action UX text")

    print()
    passed = sum(1 for s, _ in results if s == "PASS")
    print(f"RESULT: {passed}/{len(results)} production identity UX simulations passed.")
    failed = [label for s, label in results if s != "PASS"]
    if failed:
        print("FAILED:", "; ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
