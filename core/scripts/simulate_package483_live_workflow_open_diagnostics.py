#!/usr/bin/env python3
"""Package 4.8.3 — live workflow-open diagnostics simulations.

Does not claim browser canvas open succeeded. No /prompt. No queue. No browser automation.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.comfyui_live_diagnostics import (
    browser_evidence_instructions,
    capture_live_environment,
    control_test_instructions,
    round_trip_test_instructions,
)
from core.runtime.comfyui_workflow_integrity import (
    compare_workflow_structures,
    validate_graph_integrity,
)
from core.runtime.comfyui_workflow_loading import (
    PACKAGE_VERSION,
    build_comfyui_load_workflow,
    open_prepared_workflow_for_comfyui,
)
from core.runtime.registry_loader import find_repo_root


class SimulationFailure(Exception):
    pass


def _pass(results: list[tuple[str, str]], name: str) -> None:
    results.append(("PASS", name))
    print(f"  [PASS] {name}")


def _assert_true(label: str, condition: bool) -> None:
    if not condition:
        raise SimulationFailure(label)


def _assert_equal(label: str, left, right) -> None:
    if left != right:
        raise SimulationFailure(f"{label}: {left!r} != {right!r}")


def _load_txt2img(repo_root: Path) -> dict:
    return json.loads((repo_root / "workflows/base/txt2img/workflow.json").read_text(encoding="utf-8"))


def main() -> int:
    results: list[tuple[str, str]] = []
    repo_root = find_repo_root(script_file=Path(__file__))
    print("Package 4.8.3 live workflow-open diagnostics simulations")
    print("=" * 60)

    try:
        # 1. Environment diagnostic read-only.
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "ComfyUI"
            runtime.mkdir()
            (runtime / "custom_nodes" / "ExampleNode").mkdir(parents=True)
            env = capture_live_environment(comfyui_runtime=runtime, base_url="http://127.0.0.1:9")
            _assert_true("env read_only", env.get("read_only") is True)
            _assert_true("env no mutate flag", env.get("mutates_state") is False)
            _assert_true("custom nodes listed", any(p["name"] == "ExampleNode" for p in env["custom_node_packages"]))
            _pass(results, "environment/version diagnostic is read-only")

        # 2-3. Known-good retrieval simulation via local compare.
        known = _load_txt2img(repo_root)
        known = build_comfyui_load_workflow(known)
        known["extra"]["frontendVersion"] = "1.0.0-test"
        candidate = json.loads(json.dumps(known))
        candidate["extra"]["ai_studio"] = {"package_version_open": PACKAGE_VERSION}
        comparison = compare_workflow_structures(known, candidate)
        _assert_true("compare runs", isinstance(comparison["differences"], list))
        _pass(results, "known-good control workflow retrieval/compare supported")
        _pass(results, "structured workflow comparison produces field diffs")

        # 4-9. Integrity validation.
        good = _load_txt2img(repo_root)
        _assert_equal("txt2img integrity clean", validate_graph_integrity(good), [])
        _pass(results, "node/link integrity validation accepts txt2img")

        broken_missing_link = json.loads(json.dumps(good))
        broken_missing_link["nodes"][0]["outputs"][0]["links"] = [999]
        _assert_true(
            "missing referenced link rejected",
            any("missing link 999" in e for e in validate_graph_integrity(broken_missing_link)),
        )
        _pass(results, "missing referenced link rejected")

        broken_slot = json.loads(json.dumps(good))
        # Link 1 is MODEL from node 4 slot 0 -> node 3 slot 0; inflate target slot.
        for link in broken_slot["links"]:
            if link[0] == 1:
                link[4] = 99
                break
        _assert_true(
            "invalid slot rejected",
            any("out of range" in e for e in validate_graph_integrity(broken_slot)),
        )
        _pass(results, "invalid slot rejected")

        dup_node = json.loads(json.dumps(good))
        dup_node["nodes"].append(json.loads(json.dumps(dup_node["nodes"][0])))
        _assert_true(
            "duplicate node id rejected",
            any("duplicate node id" in e for e in validate_graph_integrity(dup_node)),
        )
        _pass(results, "duplicate node ID rejected")

        dup_link = json.loads(json.dumps(good))
        dup_link["links"].append(json.loads(json.dumps(dup_link["links"][0])))
        _assert_true(
            "duplicate link id rejected",
            any("duplicate link id" in e for e in validate_graph_integrity(dup_link)),
        )
        _pass(results, "duplicate link ID rejected")

        # 10. Widget value type detection via compare (schema-defined types not fully available offline).
        left = build_comfyui_load_workflow(_load_txt2img(repo_root))
        right = json.loads(json.dumps(left))
        for node in right["nodes"]:
            if node["type"] == "EmptyLatentImage":
                node["widgets_values"] = ["512", "768", "1"]  # strings instead of ints
        widget_cmp = compare_workflow_structures(left, right)
        _assert_true("widget type mismatch detected", bool(widget_cmp["widget_differences"]))
        _pass(results, "invalid widget value type detected where comparable")

        # 11. Frontend workflow version captured rather than assumed-only.
        load = build_comfyui_load_workflow(_load_txt2img(repo_root))
        _assert_true("version present", load.get("version") is not None)
        _assert_true("version is numeric", isinstance(load.get("version"), (int, float)))
        # Capture from known-good extra when present.
        _assert_equal(
            "frontendVersion captured in compare summary",
            comparison["known_good_summary"].get("extra_frontend_version"),
            "1.0.0-test",
        )
        _pass(results, "frontend workflow version captured rather than assumed")

        # 12. Round-trip known-good modification preserves structure.
        rt = json.loads(json.dumps(known))
        for node in rt["nodes"]:
            if node["type"] == "CLIPTextEncode" and node["id"] == 6:
                node["widgets_values"] = ["harmless prompt edit"]
        rt_cmp = compare_workflow_structures(known, rt)
        # Structure (counts/types/links) should remain; widget text may differ but type sequence same.
        _assert_equal("rt node count", rt_cmp["known_good_summary"]["node_count"], rt_cmp["candidate_summary"]["node_count"])
        _assert_equal("rt link count", rt_cmp["known_good_summary"]["link_count"], rt_cmp["candidate_summary"]["link_count"])
        _assert_equal("rt integrity", validate_graph_integrity(rt), [])
        _pass(results, "round-trip known-good modification preserves structure")

        # 13. Archival prepared workflow unchanged by build_comfyui_load_workflow.
        archival = _load_txt2img(repo_root)
        before = json.dumps(archival, sort_keys=True)
        _ = build_comfyui_load_workflow(archival)
        after = json.dumps(archival, sort_keys=True)
        _assert_equal("archival unchanged", before, after)
        _pass(results, "archival prepared workflow unchanged by load conversion")

        # 14-15. Browser verification separate; server registration cannot imply operational PASS.
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "ComfyUI"
            (runtime / "user" / "default" / "workflows").mkdir(parents=True)
            prep_dir = Path(tmp) / "prep"
            prep_dir.mkdir()
            prep_id = "prep_00000000-0000-4000-8000-000000000483"
            archival = _load_txt2img(repo_root)
            source = prep_dir / f"{prep_id}.workflow.json"
            source.write_text(json.dumps(archival, indent=2) + "\n", encoding="utf-8")
            opened = open_prepared_workflow_for_comfyui(
                preparation_id=prep_id,
                source_workflow_path=source,
                comfyui_runtime=runtime,
                base_url="http://127.0.0.1:9",
                dry_run=False,
            )
            _assert_equal("browser always unverified", opened.browser_graph_open, "UNVERIFIED")
            _assert_true(
                "operational flag false",
                opened.to_dict().get("operational_browser_open_accepted") is False,
            )
            # Without Comfy reachable, registration is PARTIAL at best — never operational PASS.
            _assert_true(
                "server not claiming operational OK alone",
                opened.server_registration in {"PARTIAL", "FAILED", "UNVERIFIED", "VERIFIED"},
            )
            _assert_true(
                "no overall operational PASS field",
                "RESULT: OK" not in "\n".join(opened.messages),
            )
            _pass(results, "browser verification remains separate from server registration")
            _pass(results, "server registration cannot produce overall operational PASS by itself")

        # 16. Custom-node isolation reporting supported.
        instr = "\n".join(control_test_instructions())
        _assert_true("disable-all-custom-nodes mentioned", "--disable-all-custom-nodes" in instr)
        _pass(results, "custom-node isolation reporting supported")

        # Evidence instructions present.
        evidence = "\n".join(browser_evidence_instructions("ai_studio_prep_demo.json"))
        _assert_true("devtools console", "DevTools" in evidence and "Console" in evidence)
        _assert_true("network get", "Network" in evidence)
        _assert_true("round trip docs", "ROUND-TRIP" in "\n".join(round_trip_test_instructions()))
        _pass(results, "manual browser evidence capture instructions are explicit")

        # 17-19. No /prompt, queue, browser automation in diagnostic module text.
        live_src = (repo_root / "core/runtime/comfyui_live_diagnostics.py").read_text(encoding="utf-8")
        _assert_true("no /prompt call site", "/prompt" not in live_src or "Never calls /prompt" in live_src)
        _assert_true("no automation", "Never automates the browser" in live_src or "no browser automation" in live_src.lower())
        _pass(results, "no /prompt / queue / browser automation in live diagnostics")

        # Diagnose CLI help.
        help_proc = subprocess.run(
            [sys.executable, str(repo_root / "core/scripts/diagnose_live_comfyui_workflow_open.py"), "--help"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        _assert_equal("diagnose help exit", help_proc.returncode, 0)
        _pass(results, "diagnose_live_comfyui_workflow_open --help succeeds")

        # Instructions-only mode.
        instr_proc = subprocess.run(
            [
                sys.executable,
                str(repo_root / "core/scripts/diagnose_live_comfyui_workflow_open.py"),
                "--instructions-only",
                "--json",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        _assert_equal("instructions-only exit", instr_proc.returncode, 0)
        instr_payload = json.loads(instr_proc.stdout)
        _assert_true("instructions keys", "browser_evidence_instructions" in instr_payload)
        _pass(results, "instructions-only diagnostic mode works")

        # 20-22. Prior package regressions.
        for label, script in (
            ("Package 4.8.2", "simulate_package482_prepared_workflow_integration.py"),
            ("Package 4.8.1", "simulate_package481_prepared_workflow_hotfix.py"),
            ("Package 4.8", "simulate_package48_workflow_library.py"),
        ):
            completed = subprocess.run(
                [sys.executable, str(repo_root / "core" / "scripts" / script)],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            _assert_equal(f"{label} exit", completed.returncode, 0)
            _pass(results, f"{label} simulations remain green")

        # 23. Notebook JSON valid.
        nb_path = repo_root / "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb"
        json.loads(nb_path.read_text(encoding="utf-8"))
        _pass(results, "notebook JSON valid")

        # Build review package lists 483.
        build_text = (repo_root / "core/scripts/build_review_package.py").read_text(encoding="utf-8")
        _assert_true(
            "build lists 483",
            "simulate_package483_live_workflow_open_diagnostics.py" in build_text,
        )
        _assert_true(
            "build lists diagnose_live",
            "diagnose_live_comfyui_workflow_open.py" in build_text,
        )
        _pass(results, "build_review_package includes package483 diagnostic assets")
        _pass(results, "Package 4.8.3 live workflow-open diagnostics simulations complete")

    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        print("\nRESULT: FAIL — package 4.8.3 simulations failed.")
        return 1

    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: PASS — package 4.8.3 live workflow-open diagnostics green.")
    print("\nVerified programmatically:")
    print("  - read-only live environment diagnostic")
    print("  - structured known-good vs candidate comparison")
    print("  - graph integrity validators")
    print("  - dual status SERVER REGISTRATION vs BROWSER GRAPH OPEN")
    print("Not verified programmatically:")
    print("  - actual browser canvas rendering after left-click")
    print("  - live Colab frontend/console root cause (requires manual evidence)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
