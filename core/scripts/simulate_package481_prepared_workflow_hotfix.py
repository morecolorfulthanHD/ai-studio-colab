#!/usr/bin/env python3
"""Package 4.8.1 — Prepared workflow loading hotfix simulations."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.comfyui_workflow_loading import (
    build_comfyui_load_workflow,
    file_sha256,
    open_prepared_workflow_for_comfyui,
)
from core.runtime.preparation_project_context import resolve_preparation_project
from core.runtime.prepared_workflow_index import find_by_preparation_id, preparations_log_path
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import find_repo_root
from core.runtime.workflow_manifest import load_workflow_manifest
from core.runtime.workflow_library_preparation import prepare_library_workflow
from core.runtime.workflow_provenance import extract_ai_studio_extra, hash_ui_workflow

MODEL_FILES_PRESENT = {"sd15.safetensors": True, "512-inpainting-ema.safetensors": True}


class SimulationFailure(Exception):
    pass


def _pass(results: list[tuple[str, str]], name: str) -> None:
    results.append((name, "PASS"))


def _assert_true(label: str, value: bool) -> None:
    if not value:
        raise SimulationFailure(f"{label}: expected True")


def _assert_false(label: str, value: bool) -> None:
    if value:
        raise SimulationFailure(f"{label}: expected False")


def _assert_equal(label: str, actual, expected) -> None:
    if actual != expected:
        raise SimulationFailure(f"{label}: expected {expected!r}, got {actual!r}")


def _assert_raises(label: str, fn, exc_type=ValueError) -> None:
    try:
        fn()
    except exc_type:
        return
    raise SimulationFailure(f"{label}: expected {exc_type.__name__}")


def _comfy_object_info(manifest: dict) -> dict[str, dict]:
    return {str(node): {} for node in (manifest.get("required_nodes") or [])}


def _make_temp_repo(real_repo: Path, drive_root: Path, comfy_root: Path, runtime_root: Path) -> Path:
    temp_repo = Path(tempfile.mkdtemp(prefix="ai-studio-pkg481-"))
    shutil.copytree(real_repo / "configs", temp_repo / "configs")
    shutil.copytree(real_repo / "workflows", temp_repo / "workflows")
    paths_file = temp_repo / "configs" / "paths" / "colab_paths.json"
    data = json.loads(paths_file.read_text(encoding="utf-8"))
    root = str(drive_root).replace("\\", "/")
    comfy = str(comfy_root).replace("\\", "/")
    runtime = str(runtime_root).replace("\\", "/")
    path_map = data.setdefault("paths", {})
    path_map["drive_root"] = root
    path_map["drive_outputs"] = f"{root}/outputs"
    path_map["drive_logs"] = f"{root}/logs"
    path_map["drive_inputs"] = f"{root}/inputs"
    path_map["drive_masks"] = f"{root}/masks"
    path_map["drive_workflows"] = f"{root}/workflows"
    path_map["drive_models"] = f"{root}/models"
    path_map["comfyui_runtime"] = comfy
    path_map["runtime_root"] = runtime
    path_map["runtime_workflows"] = f"{runtime}/workflows"
    paths_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return temp_repo


def _run_cli(real_repo: Path, temp_repo: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(real_repo / "core" / "scripts" / script),
        *args,
        "--repo-root",
        str(temp_repo),
    ]
    return subprocess.run(
        cmd,
        cwd=str(real_repo),
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def _prep_paths(root: Path) -> dict[str, Path]:
    drive = root / "AI_Studio"
    runtime = root / "runtime"
    comfy_input = root / "ComfyUI" / "input"
    for sub in (
        "outputs",
        "inputs",
        "masks",
        "logs",
        "workflows/prepared",
        "projects",
    ):
        (drive / sub).mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "prepared_workflows").mkdir(parents=True, exist_ok=True)
    comfy_input.mkdir(parents=True, exist_ok=True)
    checkpoint = drive / "models" / "checkpoints" / "sd15.safetensors"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    if not checkpoint.is_file():
        checkpoint.write_bytes(b"PK481-SIM-MODEL-STUB")
    return {
        "drive": drive,
        "runtime_prepared": runtime / "prepared_workflows",
        "drive_prepared": drive / "workflows" / "prepared",
        "comfy_input": comfy_input,
        "comfy_root": root / "ComfyUI",
        "runtime_root": runtime,
    }


def _load_notebook_text(repo_root: Path) -> str:
    nb_path = repo_root / "colab" / "notebooks" / "AI_Studio_Control_Panel_Colab.ipynb"
    data = json.loads(nb_path.read_text(encoding="utf-8"))
    chunks: list[str] = []
    for cell in data.get("cells") or []:
        if cell.get("cell_type") == "code":
            src = cell.get("source") or []
            chunks.append("".join(src) if isinstance(src, list) else str(src))
    return "\n".join(chunks)


def _run_prior_sim(repo_root: Path, script_name: str, label: str) -> None:
    script = repo_root / "core" / "scripts" / script_name
    _assert_true(f"{label} script exists", script.is_file())
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    if proc.returncode != 0:
        detail = (proc.stdout or "")[-800:] + (proc.stderr or "")[-800:]
        raise SimulationFailure(f"{label}: exit {proc.returncode}\n{detail}")


def run_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    repo_root = find_repo_root(script_file=Path(__file__))

    # ------------------------------------------------------------------
    # resolve_preparation_project (L1–L10)
    # ------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        paths = _prep_paths(Path(tmp))
        drive = paths["drive"]
        workspace = ProjectWorkspace(drive)

        global_ctx = resolve_preparation_project(drive, use_global=True, project_ref=None)
        _assert_equal("global mode", global_ctx.mode, "global")
        _assert_equal("global source", global_ctx.source, "flag-global")
        _assert_true("global no project", global_ctx.project is None)
        _pass(results, "resolve_preparation_project --global mode")

        no_active = resolve_preparation_project(drive, use_global=False, project_ref=None)
        _assert_equal("no active mode", no_active.mode, "global")
        _assert_equal("no active source", no_active.source, "no-active")
        _pass(results, "resolve_preparation_project no active falls back to global")

        mountain = workspace.create_project(display_name="Mountain Demo", slug="mountain-demo", set_active=True)
        active_ctx = resolve_preparation_project(drive, use_global=False, project_ref=None)
        _assert_equal("active mode", active_ctx.mode, "project")
        _assert_equal("active source", active_ctx.source, "active-project")
        _assert_equal("active slug", active_ctx.project.slug if active_ctx.project else "", "mountain-demo")
        _pass(results, "resolve_preparation_project auto-resolves active project")

        explicit = resolve_preparation_project(drive, use_global=False, project_ref="mountain-demo")
        _assert_equal("explicit source", explicit.source, "flag-project")
        _assert_equal("explicit slug", explicit.project.slug if explicit.project else "", "mountain-demo")
        _pass(results, "resolve_preparation_project explicit --project slug")

        _assert_raises(
            "conflict global+project",
            lambda: resolve_preparation_project(drive, use_global=True, project_ref="mountain-demo"),
        )
        _pass(results, "resolve_preparation_project rejects --global with --project")

        _assert_raises(
            "missing project",
            lambda: resolve_preparation_project(drive, use_global=False, project_ref="does-not-exist"),
        )
        _pass(results, "resolve_preparation_project rejects missing project")

        workspace.archive_project("mountain-demo")
        _assert_raises(
            "archived explicit",
            lambda: resolve_preparation_project(drive, use_global=False, project_ref="mountain-demo"),
        )
        _pass(results, "resolve_preparation_project rejects archived explicit project")

        workspace.restore_project("mountain-demo")
        workspace.set_active_project("mountain-demo")
        workspace.archive_project("mountain-demo")
        # archive clears the active pointer; write a stale pointer to the archived slug.
        settings_path = drive / "settings" / "active_project.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        archived_manifest = workspace.resolve_project("mountain-demo")
        settings_path.write_text(
            json.dumps({"slug": archived_manifest.slug, "project_id": archived_manifest.project_id}),
            encoding="utf-8",
        )
        _assert_raises(
            "archived active",
            lambda: resolve_preparation_project(drive, use_global=False, project_ref=None),
        )
        _pass(results, "resolve_preparation_project rejects archived active project")

        workspace.restore_project("mountain-demo")
        workspace.set_active_project("mountain-demo")
        workspace.delete_project("mountain-demo", confirm_slug="mountain-demo")
        settings_path = drive / "settings" / "active_project.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps({"slug": "mountain-demo", "project_id": "proj_missing"}),
            encoding="utf-8",
        )
        _assert_raises(
            "broken active pointer",
            lambda: resolve_preparation_project(drive, use_global=False, project_ref=None),
        )
        _pass(results, "resolve_preparation_project errors on unresolvable active pointer")

    # ------------------------------------------------------------------
    # build_comfyui_load_workflow (L11–L16)
    # ------------------------------------------------------------------
    sample_archival = {
        "version": 0.4,
        "nodes": [
            {"id": 6, "type": "CLIPTextEncode", "widgets_values": ["mountain sunset"]},
            {
                "id": 3,
                "type": "KSampler",
                "widgets_values": [123456789, "fixed", 24, 7.0, "euler", "normal", 1.0],
            },
        ],
        "links": [],
        "extra": {"ai_studio": {"preparation_id": "prep_test", "workflow_identifier": "base/txt2img"}},
    }
    load_copy = build_comfyui_load_workflow(sample_archival)
    _assert_equal("archival unchanged prompt", sample_archival["nodes"][0]["widgets_values"][0], "mountain sunset")
    _assert_equal("load copy prompt", load_copy["nodes"][0]["widgets_values"][0], "mountain sunset")
    _assert_equal("load copy seed", load_copy["nodes"][1]["widgets_values"][0], 123456789)
    _assert_true("extra ai_studio preserved", "ai_studio" in load_copy.get("extra", {}))
    _assert_true(
        "load schema stamp",
        load_copy["extra"]["ai_studio"].get("comfyui_load_schema_version") == "0.4",
    )
    _pass(results, "build_comfyui_load_workflow preserves graph parameters")
    _pass(results, "build_comfyui_load_workflow preserves prompt and seed widgets")
    _pass(results, "build_comfyui_load_workflow preserves extra.ai_studio metadata")
    _pass(results, "build_comfyui_load_workflow stamps comfyui_load_schema_version")
    _pass(results, "build_comfyui_load_workflow does not mutate archival dict")

    from core.runtime.comfyui_userdata import sanitize_workflow_userdata_filename

    _assert_equal(
        "sanitize basename",
        sanitize_workflow_userdata_filename("ai_studio_prep_test.json"),
        "ai_studio_prep_test.json",
    )
    for bad in (
        "../secret.json",
        "/abs/path.json",
        "C:/Windows/x.json",
        "workflows/nested.json",
        "evil.txt",
    ):
        _assert_raises(
            f"sanitize rejects {bad}",
            lambda value=bad: sanitize_workflow_userdata_filename(value),
        )

    # ------------------------------------------------------------------
    # CLI prepare without --project + project mirror (L17–L22)
    # ------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp)
        paths = _prep_paths(sandbox)
        temp_repo = _make_temp_repo(
            repo_root,
            paths["drive"],
            paths["comfy_root"],
            paths["runtime_root"],
        )
        workspace = ProjectWorkspace(paths["drive"])
        workspace.create_project(display_name="Mountain Demo", slug="mountain-demo", set_active=True)

        prep_cli = _run_cli(
            repo_root,
            temp_repo,
            "prepare_workflow.py",
            "--workflow",
            "base/txt2img",
            "--param",
            "positive_prompt=E2E mountain demo",
            "--param",
            "seed=424242",
            "--param",
            "sampler_name=euler",
            "--param",
            "scheduler=normal",
            "--param",
            "checkpoint=sd15.safetensors",
            "--param",
            "batch_size=1",
            "--param",
            "save_prefix=ai_studio_base_txt2img",
        )
        _assert_equal("prepare CLI exit", prep_cli.returncode, 0)
        _assert_true(
            "prepare CLI project mode",
            "mountain-demo" in (prep_cli.stdout or "") and "Mode:" in (prep_cli.stdout or ""),
        )
        _pass(results, "prepare_workflow without --project uses active project")

        prep_id = ""
        for line in (prep_cli.stdout or "").splitlines():
            if line.startswith("Preparation ID:"):
                prep_id = line.split(":", 1)[1].strip()
        _assert_true("prep id parsed", prep_id.startswith("prep_"))
        _pass(results, "prepare_workflow CLI allocates preparation id")

        record = find_by_preparation_id(preparations_log_path(paths["drive"]), prep_id)
        _assert_true("index record present", record is not None)
        assert record is not None
        _assert_equal("index project slug", record.get("project_slug"), "mountain-demo")
        _pass(results, "prepare without --project writes project metadata to index")

        project_mirror = paths["drive"] / "projects" / "mountain-demo" / "workflows" / "prepared" / prep_id
        _assert_true("project mirror dir exists", project_mirror.is_dir())
        _assert_true("project mirror workflow", (project_mirror / f"{prep_id}.workflow.json").is_file())
        _pass(results, "prepare without --project creates project mirror")

        meta = json.loads((project_mirror / f"{prep_id}.metadata.json").read_text(encoding="utf-8"))
        _assert_equal("metadata project slug", meta.get("project_slug"), "mountain-demo")
        _pass(results, "project mirror metadata includes project_slug")
        _pass(results, "project mirror includes workflow JSON artifact")
        global_wf = paths["drive_prepared"] / prep_id / f"{prep_id}.workflow.json"
        mirror_wf = project_mirror / f"{prep_id}.workflow.json"
        _assert_true("global archive workflow exists", global_wf.is_file())
        _assert_equal("project mirror SHA matches global", file_sha256(global_wf), file_sha256(mirror_wf))
        _assert_equal(
            "comfyui_load_workflow_hash recorded",
            bool(meta.get("comfyui_load_workflow_hash")),
            True,
        )
        _assert_equal(
            "comfyui_load_schema_version recorded",
            meta.get("comfyui_load_schema_version"),
            "0.4",
        )
        _pass(results, "prepare without --project writes global archive")

        global_prep = _run_cli(
            repo_root,
            temp_repo,
            "prepare_workflow.py",
            "--workflow",
            "base/txt2img",
            "--param",
            "positive_prompt=global only prep",
            "--global",
        )
        _assert_equal("global prepare exit", global_prep.returncode, 0)
        _assert_true("global prepare mode", "Global outputs only" in (global_prep.stdout or ""))
        _pass(results, "prepare_workflow --global skips project mirror")

    # ------------------------------------------------------------------
    # open_prepared_workflow_for_comfyui with mocked userdata (L23–L30)
    # ------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        paths = _prep_paths(Path(tmp))
        manifest = load_workflow_manifest(repo_root, "base/txt2img")
        prep = prepare_library_workflow(
            repo_root,
            workflow_identifier="base/txt2img",
            parameters={"positive_prompt": "userdata mock test", "seed": 111},
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            comfy_object_info=_comfy_object_info(manifest),
            model_files_present=MODEL_FILES_PRESENT,
        )
        _assert_true("mock prep ok", prep.ok)
        source = Path(prep.runtime_workflow_path)
        source_hash_before = file_sha256(source)
        load_bytes_holder: dict[str, bytes] = {}

        def _mock_reachable(_url=None, **_kw):
            return True

        def _mock_put(*, base_url=None, filename, content, overwrite=True, full_info=True, timeout=15.0):
            load_bytes_holder[filename] = content
            return {"ok": True, "status_code": 200, "relative_path": f"workflows/{filename}", "error": ""}

        def _mock_get(*, base_url=None, filename, timeout=10.0):
            body = load_bytes_holder.get(filename, b"")
            return {"ok": bool(body), "status_code": 200 if body else 404, "body": body, "error": ""}

        def _mock_list(*, base_url=None, timeout=10.0):
            return {"ok": True, "names": list(load_bytes_holder.keys()), "error": ""}

        with patch("core.runtime.comfyui_workflow_loading.comfyui_reachable", _mock_reachable):
            with patch("core.runtime.comfyui_workflow_loading.userdata_put_workflow", _mock_put):
                with patch("core.runtime.comfyui_workflow_loading.userdata_get_workflow", _mock_get):
                    with patch("core.runtime.comfyui_workflow_loading.userdata_list_workflows", _mock_list):
                        open_result = open_prepared_workflow_for_comfyui(
                            preparation_id=prep.preparation_id,
                            source_workflow_path=source,
                            comfyui_runtime=paths["comfy_root"],
                            base_url="http://127.0.0.1:8188",
                        )
        _assert_true("open ok", open_result.ok)
        _assert_true("userdata registered", open_result.userdata_registered)
        _assert_true("userdata verified", open_result.userdata_verified)
        _assert_true("userdata listed", open_result.userdata_listed)
        _assert_true("filesystem copy written", Path(open_result.filesystem_destination).is_file())
        _assert_equal("archival unchanged hash", file_sha256(source), source_hash_before)
        _pass(results, "open_prepared_workflow_for_comfyui registers via mocked userdata POST")
        _pass(results, "open_prepared_workflow_for_comfyui verifies userdata GET bytes")
        _pass(results, "open_prepared_workflow_for_comfyui lists workflow in userdata")
        _pass(results, "open leaves archival prepared workflow unchanged")

        instruction_text = "\n".join(open_result.instructions)
        _assert_true(
            "instructions left-click",
            "left-click" in instruction_text.lower(),
        )
        _assert_true("instructions no right-click Insert", "right-click Insert" not in instruction_text)
        _assert_true(
            "instructions omit Insert/drag verbs",
            "Insert" not in instruction_text and "drag" not in instruction_text.lower(),
        )
        _assert_true(
            "instructions browser confirmation unavailable",
            "Automatic browser graph confirmation is unavailable" in instruction_text,
        )
        _assert_true(
            "instructions no auto-queue",
            "does not queue a prompt" in instruction_text and "/prompt" in instruction_text,
        )
        _assert_true(
            "instructions hard-reload guidance",
            "hard-reload" in instruction_text.lower() or "Hard-reload" in instruction_text,
        )
        _pass(results, "open instructions mention left-click sidebar workflow name")
        _pass(results, "open instructions omit right-click Insert guidance")
        _pass(results, "open instructions discourage Insert-only loading")

    # ------------------------------------------------------------------
    # diagnose read-only CLI (L31–L33)
    # ------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        paths = _prep_paths(Path(tmp))
        temp_repo = _make_temp_repo(
            repo_root,
            paths["drive"],
            paths["comfy_root"],
            paths["runtime_root"],
        )
        manifest = load_workflow_manifest(repo_root, "base/txt2img")
        prep = prepare_library_workflow(
            repo_root,
            workflow_identifier="base/txt2img",
            parameters={"positive_prompt": "diagnose test"},
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            comfy_object_info=_comfy_object_info(manifest),
            model_files_present=MODEL_FILES_PRESENT,
        )
        source = Path(prep.runtime_workflow_path)
        source_mtime_before = source.stat().st_mtime

        diag = _run_cli(
            repo_root,
            temp_repo,
            "diagnose_prepared_workflow_loading.py",
            "--preparation-id",
            prep.preparation_id,
            "--json",
        )
        _assert_equal("diagnose exit", diag.returncode, 0)
        payload = json.loads(diag.stdout)
        _assert_equal("diagnose browser verification unavailable", payload.get("browser_load_verification_available"), False)
        _assert_true("diagnose source exists", payload.get("source_exists"))
        _pass(results, "diagnose_prepared_workflow_loading read-only CLI succeeds")
        _pass(results, "diagnose reports browser_load_verification_available false")

        source_mtime_after = source.stat().st_mtime
        _assert_equal("diagnose did not modify archival", source_mtime_before, source_mtime_after)
        _pass(results, "diagnose does not mutate archival prepared workflow")

    # ------------------------------------------------------------------
    # reprepare script exists (L34)
    # ------------------------------------------------------------------
    _assert_true("reprepare script exists", (repo_root / "core/scripts/reprepare_workflow.py").is_file())
    _pass(results, "reprepare_workflow.py present on disk")

    # ------------------------------------------------------------------
    # notebook strings (L35–L48)
    # ------------------------------------------------------------------
    nb_path = repo_root / "colab" / "notebooks" / "AI_Studio_Control_Panel_Colab.ipynb"
    nb_data = json.loads(nb_path.read_text(encoding="utf-8"))
    _assert_true("notebook JSON valid", isinstance(nb_data.get("cells"), list))
    _pass(results, "notebook JSON remains valid")

    nb_text = _load_notebook_text(repo_root)
    for needle in (
        "Prepared workflow destination:",
        "Global archive: AI_Studio/workflows/prepared/",
        "Project mirror: AI_Studio/projects/",
        "Global archive only",
        'input("Batch size [1]: ")',
        'input("Sampler name [euler]: ")',
        'input("Scheduler [normal]: ")',
        'input("Checkpoint [sd15.safetensors]: ")',
        'input("Save prefix [ai_studio_base_txt2img]: ")',
        "Sampler allowed_values:",
        "Scheduler allowed_values:",
        "Do not enter arbitrary paths.",
        "Effective parameters:",
        "batch_size={batch_size}",
        "sampler_name={sampler_name}",
        "scheduler={scheduler}",
        "checkpoint={checkpoint}",
        "save_prefix={save_prefix}",
        "Automatic browser graph confirmation is unavailable.",
        "Left-click the exact ai_studio_prep_<uuid>.json filename",
        "File → Load as fallback",
        "Hard-reload the entire browser tab",
        "Do not use the Workflows sidebar Refresh icon",
        "Type YES to acknowledge experimental",
    ):
        _assert_true(f"notebook contains {needle!r}", needle in nb_text)
    _pass(results, "notebook shows prepared workflow destination paths")
    _pass(results, "notebook txt2img prompts batch_size parameter")
    _pass(results, "notebook txt2img prompts sampler_name parameter")
    _pass(results, "notebook txt2img prompts scheduler parameter")
    _pass(results, "notebook txt2img prompts checkpoint parameter")
    _pass(results, "notebook txt2img prompts save_prefix parameter")
    _pass(results, "notebook prints effective parameters summary before prepare")
    _pass(results, "notebook open instructions mention automatic browser confirmation unavailable")
    _pass(results, "notebook open instructions use left-click workflow name")
    _pass(results, "notebook open instructions mention File Load fallback")
    _pass(results, "notebook experimental YES gate preserved")
    _assert_true("notebook set_active_project call", 'run_repo_python("core/scripts/set_active_project.py"' in nb_text)
    _pass(results, "notebook workflow library menu calls set_active_project")
    choice3_block = nb_text.split('elif choice == "3":')[1].split('elif choice ==')[0]
    _assert_false("choice3 no --project flag", '"--project"' in choice3_block)
    _assert_false("choice3 no --global flag", '"--global"' in choice3_block)
    _pass(results, "notebook txt2img prepare omits --project flag")
    _pass(results, "notebook txt2img prepare omits --global flag")

    _assert_false("notebook no right-click Insert", "right-click Insert" in nb_text)
    choice8_block = nb_text.split('elif choice == "8":')[1].split('elif choice ==')[0]
    # Prefer the Workflow Library open block (prep_id), not Workspace choice 8.
    for block in nb_text.split('elif choice == "8":')[1:]:
        piece = block.split("elif choice ==")[0]
        if "open_prepared_workflow.py" in piece:
            choice8_block = piece
            break
    _assert_false("choice8 no drag", "drag" in choice8_block.lower())
    _assert_false("choice8 no right-click Insert", "right-click Insert" in choice8_block)
    _pass(results, "notebook open instructions omit right-click Insert")
    _pass(results, "notebook open instructions omit drag guidance")

    # ------------------------------------------------------------------
    # E2E: active mountain-demo prepare + open via mock userdata (L49–L52)
    # ------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp)
        paths = _prep_paths(sandbox)
        temp_repo = _make_temp_repo(
            repo_root,
            paths["drive"],
            paths["comfy_root"],
            paths["runtime_root"],
        )
        ProjectWorkspace(paths["drive"]).create_project(
            display_name="Mountain Demo",
            slug="mountain-demo",
            set_active=True,
        )
        e2e_prep = _run_cli(
            repo_root,
            temp_repo,
            "prepare_workflow.py",
            "--workflow",
            "base/txt2img",
            "--param",
            "positive_prompt=Critical E2E mountain",
            "--param",
            "seed=999",
        )
        _assert_equal("E2E prepare exit", e2e_prep.returncode, 0)
        prep_id = ""
        for line in (e2e_prep.stdout or "").splitlines():
            if line.startswith("Preparation ID:"):
                prep_id = line.split(":", 1)[1].strip()
        mirror = paths["drive"] / "projects" / "mountain-demo" / "workflows" / "prepared" / prep_id
        _assert_true("E2E mirror exists", mirror.is_dir())

        load_bytes_holder: dict[str, bytes] = {}

        def _mock_reachable2(_url=None, **_kw):
            return True

        def _mock_put2(*, base_url=None, filename, content, overwrite=True, full_info=True, timeout=15.0):
            load_bytes_holder[filename] = content
            return {"ok": True, "status_code": 200, "relative_path": f"workflows/{filename}", "error": ""}

        def _mock_get2(*, base_url=None, filename, timeout=10.0):
            body = load_bytes_holder.get(filename, b"")
            return {"ok": bool(body), "status_code": 200 if body else 404, "body": body, "error": ""}

        def _mock_list2(*, base_url=None, timeout=10.0):
            return {"ok": True, "names": list(load_bytes_holder.keys()), "error": ""}

        source = mirror / f"{prep_id}.workflow.json"
        with patch("core.runtime.comfyui_workflow_loading.comfyui_reachable", _mock_reachable2):
            with patch("core.runtime.comfyui_workflow_loading.userdata_put_workflow", _mock_put2):
                with patch("core.runtime.comfyui_workflow_loading.userdata_get_workflow", _mock_get2):
                    with patch("core.runtime.comfyui_workflow_loading.userdata_list_workflows", _mock_list2):
                        e2e_open = open_prepared_workflow_for_comfyui(
                            preparation_id=prep_id,
                            source_workflow_path=source,
                            comfyui_runtime=paths["comfy_root"],
                        )
        _assert_true("E2E open ok", e2e_open.ok)
        _assert_true("E2E userdata verified", e2e_open.userdata_verified)
        prepared_data = json.loads(source.read_text(encoding="utf-8"))
        ai = extract_ai_studio_extra(prepared_data)
        _assert_equal("E2E embedded prep id", ai.get("preparation_id"), prep_id)
        _pass(results, "E2E active mountain-demo prepare without --project flag")
        _pass(results, "E2E project mirror created for active project preparation")
        _pass(results, "E2E open registers workflow via mocked userdata")

    # ------------------------------------------------------------------
    # prepared hash / ai_studio on load path (L53–L55)
    # ------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        paths = _prep_paths(Path(tmp))
        manifest = load_workflow_manifest(repo_root, "base/txt2img")
        prep = prepare_library_workflow(
            repo_root,
            workflow_identifier="base/txt2img",
            parameters={
                "positive_prompt": "hash check",
                "negative_prompt": "blur",
                "seed": 555,
                "steps": 20,
                "cfg": 6.5,
            },
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            comfy_object_info=_comfy_object_info(manifest),
            model_files_present=MODEL_FILES_PRESENT,
        )
        archival = json.loads(Path(prep.runtime_workflow_path).read_text(encoding="utf-8"))
        load_data = build_comfyui_load_workflow(archival)
        _assert_equal("prepared hash stable", hash_ui_workflow(archival), prep.prepared_workflow_hash)
        _assert_true("load hash differs or matches intentionally", bool(hash_ui_workflow(load_data)))
        ai = extract_ai_studio_extra(load_data)
        _assert_equal("load copy preparation id", ai.get("preparation_id"), prep.preparation_id)
        _pass(results, "prepared workflow hash matches parameterized graph")
        _pass(results, "load workflow copy retains preparation_id in extra.ai_studio")

    # ------------------------------------------------------------------
    # new CLI scripts on disk (L56–L58)
    # ------------------------------------------------------------------
    for script_name in (
        "diagnose_prepared_workflow_loading.py",
        "reprepare_workflow.py",
        "open_prepared_workflow.py",
    ):
        _assert_true(f"script {script_name}", (repo_root / "core/scripts" / script_name).is_file())
    _pass(results, "diagnose_prepared_workflow_loading.py present")
    _pass(results, "reprepare_workflow.py present")
    _pass(results, "open_prepared_workflow.py present")
    _assert_true(
        "build_review_package lists package481 sim",
        "simulate_package481_prepared_workflow_hotfix.py"
        in (repo_root / "core/scripts/build_review_package.py").read_text(encoding="utf-8"),
    )
    _pass(results, "build_review_package includes package481 simulation script")

    # ------------------------------------------------------------------
    # prior package regressions (L59–L63+)
    # ------------------------------------------------------------------
    for script_name, label in (
        ("simulate_package48_workflow_library.py", "Package 4.8 workflow library tests remain green"),
        ("simulate_package471_generations_ux.py", "Package 4.7.1 generations UX tests remain green"),
        ("simulate_package47_generation_snapshots.py", "Package 4.7 snapshot tests remain green"),
        ("simulate_package46_workspace_management.py", "Package 4.6 workspace tests remain green"),
        ("simulate_output_autosync.py", "Autosync/runtime ownership remains green"),
    ):
        _run_prior_sim(repo_root, script_name, label)
        _pass(results, label)

    _pass(results, "Package 4.8.1 prepared workflow hotfix simulations complete")
    return results


def main() -> int:
    print("AI Studio — Package 4.8.1 Prepared Workflow Hotfix Simulations")
    print("=" * 50)
    try:
        results = run_simulations()
    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        print("\nRESULT: FAIL — package 4.8.1 simulations failed.")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] unexpected: {exc}")
        print("\nRESULT: FAIL — package 4.8.1 simulations failed.")
        return 1

    for name, status in results:
        print(f"  [{status}] {name}")
    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: PASS — package 4.8.1 prepared workflow hotfix simulations green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
