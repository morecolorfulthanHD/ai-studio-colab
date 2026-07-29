#!/usr/bin/env python3
"""Package 4.8.2 prepared workflow integration hotfix simulations."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest.mock
from pathlib import Path

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.comfyui_userdata import (
    sanitize_workflow_userdata_filename,
    userdata_workflows_relpath,
)
from core.runtime.comfyui_workflow_loading import (
    PACKAGE_VERSION,
    build_comfyui_load_workflow,
    open_prepared_workflow_for_comfyui,
    validate_comfyui_ui_workflow_schema,
)
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import find_repo_root
from core.runtime.workflow_library_preparation import prepare_library_workflow
from core.runtime.workflow_manifest import load_workflow_manifest
from core.scripts.workflow_catalog import build_catalog


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


def _comfy_object_info(manifest: dict) -> dict[str, dict]:
    return {str(node): {} for node in (manifest.get("required_nodes") or [])}


MODEL_FILES_PRESENT = {
    "sd15.safetensors": True,
    "vae-ft-mse-840000-ema-pruned.safetensors": True,
}


def _prep_paths(root: Path) -> dict[str, Path]:
    drive = root / "drive"
    comfy = root / "ComfyUI"
    runtime = root / "runtime"
    for path in (
        drive / "workflows" / "prepared",
        drive / "models" / "checkpoints",
        drive / "inputs",
        drive / "settings",
        comfy / "input",
        comfy / "user" / "default" / "workflows",
        runtime / "prepared_workflows",
    ):
        path.mkdir(parents=True, exist_ok=True)
    ckpt = drive / "models" / "checkpoints" / "sd15.safetensors"
    if not ckpt.is_file():
        ckpt.write_bytes(b"PK482-SIM-MODEL")
    return {
        "drive": drive,
        "drive_prepared": drive / "workflows" / "prepared",
        "comfy_root": comfy,
        "comfy_input": comfy / "input",
        "runtime_root": runtime,
        "runtime_prepared": runtime / "prepared_workflows",
    }


def main() -> int:
    results: list[tuple[str, str]] = []
    repo_root = find_repo_root(script_file=Path(__file__))
    print("AI Studio — Package 4.8.2 Prepared Workflow Integration Simulations")
    print("=" * 50)

    try:
        # Catalog discovery includes BENCHMARK ONLY without hardcoding IDs into menu.
        catalog = build_catalog(repo_root)
        sections = {str(e.get("production_status") or "") for e in catalog}
        _assert_true("catalog has ready", "ready" in sections)
        _assert_true("catalog has partial", "partial" in sections)
        _assert_true("catalog has experimental", "experimental" in sections)
        _assert_true("catalog has benchmark_only", "benchmark_only" in sections)
        ids = {e["workflow_identifier"] for e in catalog}
        _assert_true("qwen discovered", "reference/qwen_image_edit" in ids)
        _assert_true("flux discovered", "reference/flux_fill" in ids)
        _pass(results, "workflow catalog includes BENCHMARK ONLY via discovery")
        _pass(results, "Qwen and FLUX appear under discovered benchmark workflows")

        hidden = build_catalog(repo_root, include_benchmark=False)
        hidden_ids = {e["workflow_identifier"] for e in hidden}
        _assert_true("exclude-benchmark still works", "reference/flux_fill" not in hidden_ids)
        _pass(results, "catalog --exclude-benchmark still hides benchmark workflows")

        # Expanded workflow_info presentation.
        info_script = repo_root / "core" / "scripts" / "workflow_info.py"
        text = info_script.read_text(encoding="utf-8")
        for needle in (
            "Workflow identifier:",
            "Display name:",
            "Description:",
            "Capability:",
            "Implementation status:",
            "Runtime status:",
            "Quality status:",
            "Production status:",
            "Readiness status:",
            "Required checkpoint:",
            "Required nodes:",
            "Canonical path:",
            "Canonical hash:",
            "Hash type:",
            "Supported parameters:",
            "Default parameter values:",
        ):
            _assert_true(f"workflow_info contains {needle}", needle in text)
        _pass(results, "workflow_info prints expanded human-readable fields")

        list_script = repo_root / "core" / "scripts" / "list_prepared_workflows.py"
        list_text = list_script.read_text(encoding="utf-8")
        for needle in ("Global path:", "Project path:", "Readiness:", "Project:", "Created:"):
            _assert_true(f"list_prepared contains {needle}", needle in list_text)
        _pass(results, "list_prepared_workflows prints expanded recent preparation fields")

        # Frontend path encoding / API alignment.
        rel = userdata_workflows_relpath("ai_studio_prep_demo.json")
        _assert_equal("relpath", rel, "workflows/ai_studio_prep_demo.json")
        _assert_equal(
            "sanitize ok",
            sanitize_workflow_userdata_filename("ai_studio_prep_demo.json"),
            "ai_studio_prep_demo.json",
        )
        _pass(results, "userdata path encoding matches frontend workflows/<file>.json")

        # Schema + load conversion.
        archival = json.loads(
            (repo_root / "workflows" / "base" / "txt2img" / "workflow.json").read_text(encoding="utf-8")
        )
        archival_copy = json.loads(json.dumps(archival))
        load = build_comfyui_load_workflow(archival)
        _assert_equal("archival unchanged", archival, archival_copy)
        _assert_true("load has id", isinstance(load.get("id"), str) and len(load["id"]) > 10)
        _assert_equal("schema clean", validate_comfyui_ui_workflow_schema(load), [])
        _assert_equal("node count preserved", len(load["nodes"]), len(archival["nodes"]))
        _assert_equal("link count preserved", len(load["links"]), len(archival["links"]))
        _assert_equal("txt2img nodes", len(load["nodes"]), 7)
        _assert_equal("txt2img links", len(load["links"]), 9)
        _assert_equal("package open stamp", load["extra"]["ai_studio"]["package_version_open"], PACKAGE_VERSION)
        _pass(results, "build_comfyui_load_workflow preserves graph and stamps schema/id")
        _pass(results, "validate_comfyui_ui_workflow_schema accepts txt2img UI workflow")
        _pass(results, "txt2img loading representation has 7 nodes and 9 links")

        # Registration + discovery + server-side open verification (mocked HTTP).
        with tempfile.TemporaryDirectory() as tmp:
            paths = _prep_paths(Path(tmp))
            workspace = ProjectWorkspace(paths["drive"])
            workspace.create_project(display_name="Mountain Demo", slug="mountain-demo", set_active=True)
            manifest = load_workflow_manifest(repo_root, "base/txt2img")
            prep = prepare_library_workflow(
                repo_root,
                workflow_identifier="base/txt2img",
                parameters={
                    "positive_prompt": "alpine observatory",
                    "seed": 246813579,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "checkpoint": "sd15.safetensors",
                },
                runtime_prepared_root=paths["runtime_prepared"],
                drive_prepared_root=paths["drive_prepared"],
                comfyui_input_dir=paths["comfy_input"],
                drive_root=paths["drive"],
                active_project=workspace.get_active_project(),
                comfy_object_info=_comfy_object_info(manifest),
                model_files_present=MODEL_FILES_PRESENT,
            )
            _assert_true("prep ok", prep.ok)
            source = Path(prep.runtime_workflow_path)
            load_name = f"ai_studio_{prep.preparation_id}.json"
            load_bytes_holder: dict[str, bytes] = {}

            def fake_reachable(_url=None, **_kwargs):
                return True

            def fake_put(*, base_url, filename, content, overwrite=True, full_info=True, timeout=15.0):
                load_bytes_holder["content"] = content
                return {
                    "ok": True,
                    "status_code": 200,
                    "url": f"{base_url}/api/userdata/workflows%2F{filename}?overwrite=true&full_info=true",
                    "relative_path": f"workflows/{filename}",
                    "error": "",
                    "response_bytes": 0,
                    "full_info": {"path": f"workflows/{filename}", "size": len(content)},
                }

            def fake_get(*, base_url, filename, timeout=10.0):
                body = load_bytes_holder.get("content", b"")
                return {
                    "ok": True,
                    "status_code": 200,
                    "url": f"{base_url}/api/userdata/workflows%2F{filename}",
                    "relative_path": f"workflows/{filename}",
                    "error": "",
                    "body": body,
                }

            def fake_list(*, base_url, timeout=10.0):
                body = load_bytes_holder.get("content", b"")
                return {
                    "ok": True,
                    "status_code": 200,
                    "url": f"{base_url}/api/userdata?dir=workflows&recurse=true&split=false&full_info=true",
                    "names": [load_name],
                    "entries": [{"name": load_name, "path": load_name, "size": len(body)}],
                    "error": "",
                }

            with (
                unittest.mock.patch(
                    "core.runtime.comfyui_workflow_loading.comfyui_reachable", fake_reachable
                ),
                unittest.mock.patch(
                    "core.runtime.comfyui_workflow_loading.userdata_put_workflow", fake_put
                ),
                unittest.mock.patch(
                    "core.runtime.comfyui_workflow_loading.userdata_get_workflow", fake_get
                ),
                unittest.mock.patch(
                    "core.runtime.comfyui_workflow_loading.userdata_list_workflows", fake_list
                ),
            ):
                opened = open_prepared_workflow_for_comfyui(
                    preparation_id=prep.preparation_id,
                    source_workflow_path=source,
                    comfyui_runtime=paths["comfy_root"],
                    base_url="http://127.0.0.1:8188",
                )

            _assert_true("open ok", opened.ok)
            _assert_true("registered", opened.userdata_registered)
            _assert_true("verified", opened.userdata_verified)
            _assert_true("listed", opened.userdata_listed)
            _assert_true("list size", opened.userdata_list_size_matches)
            _assert_true("schema", opened.schema_valid)
            _assert_equal("dest name deterministic", opened.load_filename, load_name)
            dest = Path(opened.filesystem_destination)
            _assert_true("fs copy exists", dest.is_file())
            # No collision sibling for the same prep id.
            sibling = dest.parent / f"{dest.stem}_1{dest.suffix}"
            _assert_true("no collision sibling", not sibling.exists())
            instruction = "\n".join(opened.instructions)
            _assert_true("left-click instruction", "Left-click" in instruction or "left-click" in instruction.lower())
            _assert_true("no Insert mention", "Insert" not in instruction)
            _assert_true("no drag mention", "drag" not in instruction.lower())
            _assert_true("no /prompt queue", "does not call /prompt" in instruction)
            _assert_true("hard-reload warning", "hard-reload" in instruction.lower() or "Hard-reload" in instruction)
            _pass(results, "open registers via /api userdata with full_info listing verification")
            _pass(results, "open overwrites deterministic ai_studio_<prep_id>.json loading copy")
            _pass(results, "open verifies schema + node count from userdata GET")
            _pass(results, "open instructions use left-click and omit Insert/drag")

            # Simulated frontend load path: GET → parse → schema → nodes (not browser).
            parsed = json.loads(load_bytes_holder["content"].decode("utf-8"))
            _assert_equal("sim load schema", validate_comfyui_ui_workflow_schema(parsed), [])
            _assert_equal("sim load nodes", len(parsed["nodes"]), opened.node_count)
            _pass(results, "server-side simulated frontend load parse succeeds")
            _pass(
                results,
                "browser canvas open remains explicitly unverified (verification_limits set)",
            )
            _assert_true("limits documented", bool(opened.verification_limits))

        # Notebook mentions updated open guidance.
        nb = json.loads(
            (repo_root / "colab" / "notebooks" / "AI_Studio_Control_Panel_Colab.ipynb").read_text(
                encoding="utf-8"
            )
        )
        nb_text = "".join("".join(c.get("source") or []) for c in nb["cells"])
        _assert_true("notebook hard-reload", "hard-reload" in nb_text.lower())
        _assert_true("notebook left-click", "left-click" in nb_text.lower())
        _assert_true("notebook no sidebar Refresh guidance as open method", "sidebar Refresh icon" in nb_text)
        _assert_true("notebook no right-click Insert", "right-click Insert" not in nb_text)
        _pass(results, "notebook Open instructions match verified loading action")

        # Regressions.
        for label, script in (
            ("Package 4.8.1", "simulate_package481_prepared_workflow_hotfix.py"),
            ("Package 4.8", "simulate_package48_workflow_library.py"),
        ):
            completed = __import__("subprocess").run(
                [sys.executable, str(repo_root / "core" / "scripts" / script)],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            _assert_equal(f"{label} exit", completed.returncode, 0)
            _pass(results, f"{label} simulations remain green")

        _assert_true(
            "build_review_package lists package482",
            "simulate_package482_prepared_workflow_integration.py"
            in (repo_root / "core/scripts/build_review_package.py").read_text(encoding="utf-8"),
        )
        _pass(results, "build_review_package includes package482 simulation script")
        _pass(results, "Package 4.8.2 prepared workflow integration simulations complete")

    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        print("\nRESULT: FAIL — package 4.8.2 simulations failed.")
        return 1

    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: PASS — package 4.8.2 prepared workflow integration simulations green.")
    print("\nVerified programmatically:")
    print("  - userdata registration path (/api preferred)")
    print("  - full_info discovery listing")
    print("  - GET byte/schema/node verification")
    print("  - catalog BENCHMARK ONLY discovery")
    print("  - expanded workflow_info / recent prepared listing")
    print("Not verified programmatically:")
    print("  - actual browser canvas rendering after left-click")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
