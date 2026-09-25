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
    apply_consolidated_qa_to_status,
    confirm_gpu_execution,
    derive_workflow_status,
    find_reusable_scenario_row,
    parse_production_scenarios,
    resolve_production_character,
    run_production_identity_benchmark,
    run_production_runtime_preflight,
)
from core.runtime.registry_loader import find_repo_root
from core.runtime.runtime_health import HealthCheck, HealthStatus
from core.runtime.colab_operator import load_operator_config, navigation_sequence
from core.runtime.package4123_qa import DEFAULT_PACKAGE4123_SUITES


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
        cqa_calls: list[str] = []

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

        def _preflight_ok(*_a, **_k):
            return {
                "ok": True,
                "steps": [{"step": "mock", "ok": True}],
                "errors": [],
                "messages": ["mock preflight ok"],
                "warnings": [],
                "preflight_sequence": [
                    "comfyui_reachable",
                    "instantid_live_nodes",
                    "instantid_structural",
                    "instantid_assets",
                    "license_gate",
                    "output_watcher",
                ],
            }

        def _cqa_pass(repo_root_arg, **_kwargs):
            cqa_calls.append(str(repo_root_arg))
            return {
                "ok": True,
                "all_required_suites_pass": True,
                "suites": [{"name": "mock_suite", "ok": True, "failed": 0, "exit_code": 0}],
                "timezone_checks": {"ok": True},
                "totals": {"passed": 1, "failed": 0, "tests_discovered": 1},
                "report_path": str(drive / "logs" / "qa" / "package_4_12_3_latest.json"),
                "report_paths": [str(drive / "logs" / "qa" / "package_4_12_3_latest.json")],
            }

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
                preflight_fn=_preflight_ok,
                consolidated_qa_fn=_cqa_pass,
                allow_blocked_instantid=True,
            )
        finally:
            RegistryLoader.load_all = orig  # type: ignore[method-assign]

        _assert_equal("status human review", payload["status"], STATUS_HUMAN_REVIEW)
        _assert_true("reused S1", SCENARIO_IDS[0] in payload["scenarios_skipped_reuse"])
        _assert_true("did not re-exec S1", SCENARIO_IDS[0] not in executed)
        _assert_equal("executed remaining 3", len(executed), 3)
        _assert_true("report paths", bool(payload.get("report_paths")))
        _assert_true("human instructions", "HUMAN_REVIEW_REQUIRED" in (payload.get("human_review_instructions") or ""))
        _assert_true("A. consolidated QA invoked", payload.get("consolidated_qa_ran") is True)
        _assert_equal("A. consolidated QA status PASS", payload.get("consolidated_qa_status"), "PASS")
        _assert_true("A. consolidated QA call recorded", len(cqa_calls) == 1)
        _assert_true("G. resume unchanged", SCENARIO_IDS[0] not in executed and len(executed) == 3)
    _pass(results, "I/J/K/M/A/G. one-action orchestrator reuse + HUMAN_REVIEW + consolidated QA")

    # A/B/C consolidated QA status derivation + invocation
    st_c, reason = apply_consolidated_qa_to_status(
        STATUS_COMPLETE, consolidated_ok=False, consolidated_ran=True
    )
    _assert_equal("B. consolidated fail overrides COMPLETE", st_c, STATUS_FAILED)
    _assert_true("B. failure reason set", "consolidated QA" in (reason or ""))
    st_h, _ = apply_consolidated_qa_to_status(
        STATUS_HUMAN_REVIEW, consolidated_ok=True, consolidated_ran=True
    )
    _assert_equal("C. human review preserved on QA pass", st_h, STATUS_HUMAN_REVIEW)
    st_ok, _ = apply_consolidated_qa_to_status(
        STATUS_COMPLETE, consolidated_ok=True, consolidated_ran=True
    )
    _assert_equal("C. complete preserved on QA pass", st_ok, STATUS_COMPLETE)
    _pass(results, "A/B/C. consolidated QA invocation + state derivation")

    # D/E/F preflight: unreachable ComfyUI, unhealthy watcher, healthy runtime
    class _Bundle:
        def __init__(self, root: Path):
            self.repo_root = root
            self.models = []
            self.nodes = []
            self.root = root

        def path(self, key: str) -> Path:
            mapping = {
                "drive_root": self.root / "AI_Studio",
                "comfyui_runtime": self.root / "ComfyUI",
                "drive_logs": self.root / "AI_Studio" / "logs",
                "runtime_root": self.root / "runtime",
            }
            return mapping.get(key, self.root / key)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "ComfyUI" / "custom_nodes").mkdir(parents=True)
        (root / "AI_Studio" / "logs").mkdir(parents=True)
        bundle = _Bundle(root)

        pf_bad = run_production_runtime_preflight(
            repo_root,
            bundle,
            allow_missing_models=True,
            allow_missing_nodes=True,
            allow_unverified_assets=True,
            comfy_reachable_fn=lambda *_a, **_k: False,
            watcher_check_fn=lambda _b: HealthCheck(
                "output_watcher", HealthStatus.OK, "unused", {"ownership_state": "current_runtime"}
            ),
        )
        _assert_true("D. unreachable fails", not pf_bad["ok"])
        _assert_true(
            "D. mentions ComfyUI",
            any("ComfyUI is not reachable" in e for e in pf_bad["errors"]),
        )
        _assert_true("D. no silent reset", all("Full Reset" not in e for e in pf_bad["errors"]))

        pf_watch = run_production_runtime_preflight(
            repo_root,
            bundle,
            allow_missing_models=True,
            allow_missing_nodes=True,
            allow_unverified_assets=True,
            comfy_reachable_fn=lambda *_a, **_k: True,
            object_info_fn=lambda *_a, **_k: (
                "ok",
                {
                    "InstantIDModelLoader": {},
                    "InstantIDFaceAnalysis": {},
                    "ApplyInstantIDAdvanced": {},
                },
                "ok",
                [],
            ),
            watcher_check_fn=lambda _b: HealthCheck(
                "output_watcher",
                HealthStatus.FAIL,
                "Watcher dead",
                {"ownership_state": "dead"},
            ),
        )
        _assert_true("E. unhealthy watcher fails", not pf_watch["ok"])
        _assert_true(
            "E. surfaces OutputWatcher",
            any("OutputWatcher" in e for e in pf_watch["errors"]),
        )

        pf_ok = run_production_runtime_preflight(
            repo_root,
            bundle,
            allow_missing_models=True,
            allow_missing_nodes=True,
            allow_unverified_assets=True,
            comfy_reachable_fn=lambda *_a, **_k: True,
            object_info_fn=lambda *_a, **_k: (
                "ok",
                {
                    "InstantIDModelLoader": {},
                    "InstantIDFaceAnalysis": {},
                    "ApplyInstantIDAdvanced": {},
                },
                "ok",
                [],
            ),
            watcher_check_fn=lambda _b: HealthCheck(
                "output_watcher",
                HealthStatus.OK,
                "Watcher OK",
                {"ownership_state": "current_runtime"},
            ),
        )
        _assert_true("F. healthy preflight passes", pf_ok["ok"])
        _assert_equal(
            "F. sequence",
            pf_ok["preflight_sequence"],
            [
                "comfyui_reachable",
                "instantid_live_nodes",
                "instantid_structural",
                "instantid_assets",
                "license_gate",
                "output_watcher",
            ],
        )
    _pass(results, "D/E/F. runtime preflight unreachable / watcher / healthy")

    # Orchestrator stops before execute when preflight fails
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        drive = root / "AI_Studio"
        (root / "ComfyUI" / "input").mkdir(parents=True)
        (drive / "workflows" / "prepared").mkdir(parents=True)
        face = drive / "face.png"
        _face(face)
        rec = register_character(drive, display_name="Pre", primary_face_image=face)
        executed2: list[str] = []

        class _FakeBundle2:
            def __init__(self, root: Path):
                self.root = root
                self.models = []
                self.nodes = []

            def path(self, key: str) -> Path:
                return {
                    "drive_root": self.root / "AI_Studio",
                    "comfyui_runtime": self.root / "ComfyUI",
                    "runtime_root": self.root / "runtime",
                    "drive_workflows": self.root / "AI_Studio" / "workflows",
                }[key]

        orig = RegistryLoader.load_all
        RegistryLoader.load_all = lambda self: _FakeBundle2(root)  # type: ignore[method-assign]
        try:
            bad = run_production_identity_benchmark(
                repo_root,
                character_id=rec.character.character_id,
                scenarios=[SCENARIO_IDS[0]],
                operator_live_intent=True,
                interactive=False,
                execute_fn=lambda **k: executed2.append(k["scenario"]) or ArchitectureExecutionResult(ok=True, scenario=k["scenario"]),
                preflight_fn=lambda *_a, **_k: {
                    "ok": False,
                    "errors": ["ERROR: ComfyUI is not reachable at http://127.0.0.1:8188."],
                    "messages": [],
                    "warnings": [],
                    "steps": [],
                },
                consolidated_qa_fn=lambda *_a, **_k: {"ok": True},
                allow_blocked_instantid=True,
            )
        finally:
            RegistryLoader.load_all = orig  # type: ignore[method-assign]
        _assert_equal("D. status FAILED", bad["status"], STATUS_FAILED)
        _assert_equal("D. no scenario exec", executed2, [])
        _assert_true("D. consolidated not required before preflight", bad.get("consolidated_qa_ran") is False)
    _pass(results, "D. unhealthy ComfyUI fails before scenario execution")

    # H/I/J operator nav + policy unchanged
    cfg = load_operator_config()
    seq = navigation_sequence("run_production_identity_benchmark", cfg)
    _assert_equal("H. nav 9-13-11", [s.get("select") for s in seq], ["9", "13", "11"])
    never = " ".join(str(x) for x in (cfg.get("never_auto") or []))
    _assert_true("I. no 4.13", "4.13" in never)
    _assert_true("J. no FaceID/ReActor production reruns", "FaceID" in never or "ReActor" in never)
    _assert_true(
        "consolidated suites include architecture sim",
        "simulate_package4123_identity_architecture.py" in DEFAULT_PACKAGE4123_SUITES
        and "simulate_package4123_ipadapter_plus_face_foundation.py"
        in DEFAULT_PACKAGE4123_SUITES,
    )
    _pass(results, "H/I/J. operator nav + Package 4.13/FaceID protections")

    # B. consolidated QA failure => FAILED even if scenarios provisional
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        drive = root / "AI_Studio"
        (root / "ComfyUI" / "input").mkdir(parents=True)
        (drive / "workflows" / "prepared").mkdir(parents=True)
        face = drive / "face.png"
        _face(face)
        rec = register_character(drive, display_name="CQA", primary_face_image=face)

        class _FakeBundle3:
            def __init__(self, root: Path):
                self.root = root
                self.models = []
                self.nodes = []

            def path(self, key: str) -> Path:
                return {
                    "drive_root": self.root / "AI_Studio",
                    "comfyui_runtime": self.root / "ComfyUI",
                    "runtime_root": self.root / "runtime",
                    "drive_workflows": self.root / "AI_Studio" / "workflows",
                }[key]

        def _exec_one(**kwargs):
            scenario = kwargs["scenario"]
            path = drive / f"{scenario}.png"
            path.write_bytes(b"x")
            return ArchitectureExecutionResult(
                ok=True,
                scenario=scenario,
                prompt_id="p1",
                output_path=str(path),
                output_sha256=file_sha256(path),
                automated_qa={"automated_quality_status": "provisional_pass"},
            )

        orig = RegistryLoader.load_all
        RegistryLoader.load_all = lambda self: _FakeBundle3(root)  # type: ignore[method-assign]
        try:
            failed_payload = run_production_identity_benchmark(
                repo_root,
                character_id=rec.character.character_id,
                scenarios=[SCENARIO_IDS[0]],
                operator_live_intent=True,
                interactive=False,
                execute_fn=_exec_one,
                preflight_fn=lambda *_a, **_k: {"ok": True, "errors": [], "messages": [], "warnings": [], "steps": []},
                consolidated_qa_fn=lambda *_a, **_k: {
                    "ok": False,
                    "all_required_suites_pass": False,
                    "suites": [{"name": "broken", "ok": False, "failed": 1, "exit_code": 1}],
                    "timezone_checks": {"ok": True},
                    "report_path": "/tmp/qa.json",
                },
                allow_blocked_instantid=True,
            )
        finally:
            RegistryLoader.load_all = orig  # type: ignore[method-assign]
        _assert_equal("B. FAILED on consolidated QA", failed_payload["status"], STATUS_FAILED)
        _assert_true("B. consolidated ran", failed_payload.get("consolidated_qa_ran"))
        _assert_equal("B. consolidated status FAIL", failed_payload.get("consolidated_qa_status"), "FAIL")
        _assert_true("B. failures listed", bool(failed_payload.get("consolidated_qa_failures")))
    _pass(results, "B. consolidated QA failure => FAILED")

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
    _assert_true(
        "option 11 InstantID blocked messaging",
        "BLOCKED_FOR_COMMERCIAL" in src or "option 11" in src.lower() or "blocked" in src.lower(),
    )
    _pass(results, "Characters menu one-action UX text")

    # Option 11 / InstantID production blocked by default
    from core.runtime.identity_architecture_plugin import is_instantid_production_blocked

    blocked, gate = is_instantid_production_blocked(repo_root)
    _assert_true("InstantID production blocked", blocked)
    _assert_equal("promotion_allowed false", gate.get("promotion_allowed"), False)
    _assert_equal(
        "overall BLOCKED_FOR_COMMERCIAL",
        gate.get("overall_status"),
        "BLOCKED_FOR_COMMERCIAL",
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        drive = root / "AI_Studio"
        drive.mkdir(parents=True)
        (root / "ComfyUI").mkdir(parents=True)
        (root / "runtime").mkdir(parents=True)

        class _FakeBundleBlock:
            def __init__(self, root: Path):
                self.root = root
                self.models = []
                self.nodes = []

            def path(self, key: str) -> Path:
                return {
                    "drive_root": self.root / "AI_Studio",
                    "comfyui_runtime": self.root / "ComfyUI",
                    "runtime_root": self.root / "runtime",
                    "drive_workflows": self.root / "AI_Studio" / "workflows",
                }[key]

        orig = RegistryLoader.load_all
        RegistryLoader.load_all = lambda self: _FakeBundleBlock(root)  # type: ignore[method-assign]
        try:
            refused = run_production_identity_benchmark(
                repo_root,
                character_id="char_unused",
                scenarios=[SCENARIO_IDS[0]],
                operator_live_intent=True,
                interactive=False,
                skip_preflight=True,
                skip_consolidated_qa=True,
            )
        finally:
            RegistryLoader.load_all = orig  # type: ignore[method-assign]
        _assert_true("option 11 refused", refused.get("option_11_blocked") is True)
        _assert_equal("refused status FAILED", refused["status"], STATUS_FAILED)
        _assert_true(
            "refused mentions BLOCKED",
            "BLOCKED" in str(refused.get("failure_reason") or ""),
        )
    _pass(results, "InstantID option 11 BLOCKED_FOR_COMMERCIAL fail-closed")

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
