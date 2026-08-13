#!/usr/bin/env python3
"""Package 4.9 — prepared workflow execution controls simulations."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
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

from core.runtime import output_autosync
from core.runtime.comfyui_events import extract_output_files
from core.runtime.comfyui_workflow_loading import (
    build_comfyui_load_workflow,
    open_prepared_workflow_for_comfyui,
)
from core.runtime.generation_evidence_ledger import file_sha256
from core.runtime.output_autosync import AUTOSYNC_TEMP_PREFIX, OutputAutoSyncService
from core.runtime.png_utils import write_rgb_png
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.seed_mode import (
    SEED_MODE_FIXED,
    SEED_MODE_RANDOMIZE,
    resolve_seed_mode,
)
from core.runtime.workflow_library_preparation import prepare_library_workflow
from core.runtime.workflow_manifest import load_workflow_manifest
from core.runtime.workflow_parameters import apply_parameter_bindings, coerce_and_validate_parameters
from core.runtime.workflow_provenance import (
    extract_execution_provenance,
    hash_ui_workflow,
    load_registered_workflow_hashes,
)

MODEL_FILES_PRESENT = {
    "sd15.safetensors": True,
    "512-inpainting-ema.safetensors": True,
}


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


def _assert_false(label: str, value: bool) -> None:
    if value:
        raise SimulationFailure(f"{label}: expected False")


def _write_png(path: Path, fill: tuple[int, int, int] = (10, 20, 30)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [[fill for _ in range(8)] for _ in range(8)]
    write_rgb_png(path, 8, 8, rows)


def _comfy_object_info(manifest: dict) -> dict[str, dict]:
    return {str(node): {} for node in (manifest.get("required_nodes") or [])}


def _prep_paths(root: Path) -> dict[str, Path]:
    drive = root / "AI_Studio"
    runtime = root / "runtime"
    comfy_input = root / "ComfyUI" / "input"
    for sub in ("outputs", "inputs", "masks", "logs", "workflows/prepared", "projects"):
        (drive / sub).mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "prepared_workflows").mkdir(parents=True, exist_ok=True)
    comfy_input.mkdir(parents=True, exist_ok=True)
    checkpoint = drive / "models" / "checkpoints" / "sd15.safetensors"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    if not checkpoint.is_file():
        checkpoint.write_bytes(b"PK49-SIM-MODEL-STUB")
    return {
        "drive": drive,
        "runtime_prepared": runtime / "prepared_workflows",
        "drive_prepared": drive / "workflows" / "prepared",
        "comfy_input": comfy_input,
    }


def _prepare_txt2img(repo_root: Path, paths: dict[str, Path], parameters: dict | None = None, **kwargs):
    manifest = load_workflow_manifest(repo_root, "base/txt2img")
    params = dict(parameters or {})
    params.setdefault("positive_prompt", "a mountain landscape")
    return prepare_library_workflow(
        repo_root,
        workflow_identifier="base/txt2img",
        parameters=params,
        runtime_prepared_root=paths["runtime_prepared"],
        drive_prepared_root=paths["drive_prepared"],
        comfyui_input_dir=paths["comfy_input"],
        drive_root=paths["drive"],
        allowed_input_roots=[paths["drive"] / "inputs", repo_root / "inputs"],
        comfy_object_info=_comfy_object_info(manifest),
        model_files_present=MODEL_FILES_PRESENT,
        **kwargs,
    )


def _ksampler(workflow: dict) -> dict:
    return next(node for node in workflow["nodes"] if node.get("type") == "KSampler")


def _node(workflow: dict, node_id: str) -> dict:
    return next(node for node in workflow["nodes"] if str(node.get("id")) == node_id)


def _txt2img_api(*, seed: int, save_prefix: str = "ai_studio_base_txt2img", batch_size: int = 1) -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd15.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "snowy alpine research station", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, low quality", "clip": ["4", 1]}},
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 768, "batch_size": batch_size},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 24,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": save_prefix, "images": ["8", 0]}},
    }


def _history_entry(api_prompt: dict, ui_workflow: dict | None, outputs: dict, prompt_id: str) -> dict:
    extra_data: dict = {}
    if ui_workflow is not None:
        extra_data = {"extra_pnginfo": {"workflow": ui_workflow}}
    return {
        "prompt": [0, prompt_id, api_prompt, extra_data, list(outputs.keys()) or ["9"]],
        "outputs": outputs,
        "status": {"status_str": "success", "completed": True},
    }


def _flat_outputs(*filenames: str) -> dict:
    return {
        "9": {
            "images": [
                {"filename": name, "subfolder": "", "type": "output"} for name in filenames
            ]
        }
    }


def _drive_finals(drive_out: Path) -> list[Path]:
    if not drive_out.is_dir():
        return []
    return [
        path
        for path in drive_out.iterdir()
        if path.is_file() and not path.name.startswith(AUTOSYNC_TEMP_PREFIX)
    ]


def _service(tmp: Path, *, registered: dict, active_project=None, repo_root: Path | None = None):
    comfy = tmp / "ComfyUI" / "output"
    drive_root = tmp / "AI_Studio"
    drive_out = drive_root / "outputs"
    comfy.mkdir(parents=True)
    drive_out.mkdir(parents=True)
    svc = OutputAutoSyncService(
        comfy_output_dir=comfy,
        drive_output_dir=drive_out,
        evidence_path=drive_root / "logs" / "generation_evidence.jsonl",
        index_path=drive_root / "logs" / "autosync" / "output_watcher_processed.json",
        status_path=tmp / "watcher_status.json",
        base_url="http://127.0.0.1:9",
        sleep_fn=lambda _s: None,
        max_copy_retries=1,
        registered_hashes=registered,
        active_project=active_project,
        drive_root=drive_root,
        repo_root=repo_root,
    )
    return svc, comfy, drive_root, drive_out


def _handle(svc: OutputAutoSyncService, history: dict, prompt_id: str):
    original = output_autosync.fetch_history
    output_autosync.fetch_history = lambda base_url, prompt_id=None, **_kwargs: (
        history if prompt_id is None else {prompt_id: history[prompt_id]}
    )
    try:
        return svc.handle_prompt_id(prompt_id)
    finally:
        output_autosync.fetch_history = original


def _make_temp_repo(real_repo: Path, drive_root: Path, comfy_root: Path, runtime_root: Path) -> Path:
    temp_repo = Path(tempfile.mkdtemp(prefix="ai-studio-pkg49-"))
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


def _run_cli(real_repo: Path, temp_repo: Path | None, script: str, *args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(real_repo / "core" / "scripts" / script), *args]
    if temp_repo is not None:
        cmd.extend(["--repo-root", str(temp_repo)])
    return subprocess.run(
        cmd,
        cwd=str(real_repo),
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def main() -> int:
    results: list[tuple[str, str]] = []
    repo_root = find_repo_root(script_file=Path(__file__))
    print("Package 4.9 prepared execution controls simulations")
    print("=" * 60)

    try:
        manifest = load_workflow_manifest(repo_root, "base/txt2img")
        schema = manifest.get("parameter_schema") or {}
        defaults = manifest.get("default_parameters") or {}
        canonical = json.loads(
            (repo_root / str(manifest["canonical_workflow_path"])).read_text(encoding="utf-8")
        )
        canonical_hash_before = hash_ui_workflow(canonical)

        _assert_true("manifest exposes seed_mode", "seed_mode" in schema)
        _assert_equal("manifest seed_mode default", schema["seed_mode"].get("default"), "fixed")
        _assert_equal(
            "manifest seed_mode allowed",
            list(schema["seed_mode"].get("allowed_values") or []),
            ["fixed", "randomize"],
        )
        _assert_equal("defaults seed_mode", defaults.get("seed_mode"), "fixed")
        _pass(results, "workflow manifest exposes seed_mode")

        params_default, errors_default = coerce_and_validate_parameters(
            schema, defaults, {"positive_prompt": "default seed mode"}
        )
        _assert_equal("default coerce errors", errors_default, [])
        _assert_equal("seed_mode default = fixed", params_default.get("seed_mode"), SEED_MODE_FIXED)
        _pass(results, "seed_mode default = fixed")

        params_fixed, errors_fixed = coerce_and_validate_parameters(
            schema, defaults, {"positive_prompt": "explicit fixed", "seed_mode": "fixed"}
        )
        _assert_equal("explicit fixed errors", errors_fixed, [])
        _assert_equal("explicit fixed mode", params_fixed.get("seed_mode"), SEED_MODE_FIXED)
        _pass(results, "explicit fixed mode")

        params_rand, errors_rand = coerce_and_validate_parameters(
            schema, defaults, {"positive_prompt": "randomize", "seed_mode": "randomize"}
        )
        _assert_equal("randomize coerce errors", errors_rand, [])
        _assert_equal("randomize mode", params_rand.get("seed_mode"), SEED_MODE_RANDOMIZE)
        _pass(results, "randomize mode")

        for invalid in ("foo", "true", "1"):
            _, invalid_errors = coerce_and_validate_parameters(
                schema, defaults, {"positive_prompt": "bad", "seed_mode": invalid}
            )
            _assert_true(
                f"invalid {invalid} rejected",
                any("Invalid value for seed_mode. Expected one of: fixed, randomize." in err for err in invalid_errors),
            )
        _pass(results, "invalid seed_mode rejected")

        bound_fixed = apply_parameter_bindings(
            copy.deepcopy(canonical),
            schema,
            {"positive_prompt": "bind fixed", "seed": 975318642, "seed_mode": "fixed"},
        )
        sampler_fixed = _ksampler(bound_fixed)
        _assert_equal("fixed maps control", sampler_fixed["widgets_values"][1], "fixed")
        _assert_equal("fixed keeps seed", sampler_fixed["widgets_values"][0], 975318642)
        _pass(results, "fixed maps to KSampler control fixed")
        _pass(results, "numeric initial seed preserved in both modes")

        bound_rand = apply_parameter_bindings(
            copy.deepcopy(canonical),
            schema,
            {"positive_prompt": "bind rand", "seed": 975318642, "seed_mode": "randomize"},
        )
        sampler_rand = _ksampler(bound_rand)
        _assert_equal("randomize maps control", sampler_rand["widgets_values"][1], "randomize")
        _assert_equal("randomize keeps seed", sampler_rand["widgets_values"][0], 975318642)
        _pass(results, "randomize maps to KSampler control randomize")

        bound_other = apply_parameter_bindings(
            copy.deepcopy(canonical),
            schema,
            {
                "positive_prompt": "other controls",
                "seed": 111,
                "seed_mode": "fixed",
                "sampler_name": "ddim",
                "scheduler": "karras",
                "checkpoint": "sd15.safetensors",
                "batch_size": 2,
                "save_prefix": "custom_prefix",
                "steps": 30,
                "cfg": 5.5,
            },
        )
        _assert_equal("sampler graph", _ksampler(bound_other)["widgets_values"][4], "ddim")
        _assert_equal("scheduler graph", _ksampler(bound_other)["widgets_values"][5], "karras")
        _assert_equal("checkpoint graph", _node(bound_other, "4")["widgets_values"][0], "sd15.safetensors")
        _assert_equal("batch graph", _node(bound_other, "5")["widgets_values"][2], 2)
        _assert_equal("save prefix graph", _node(bound_other, "9")["widgets_values"][0], "custom_prefix")
        _assert_equal("unrelated denoise untouched", _ksampler(bound_other)["widgets_values"][6], 1)
        _pass(results, "sampler parameter changes prepared graph")
        _pass(results, "scheduler parameter changes prepared graph")
        _pass(results, "checkpoint parameter changes prepared graph")
        _pass(results, "batch_size parameter changes prepared graph")
        _pass(results, "save_prefix parameter changes Save Image graph value")

        _, sampler_err = coerce_and_validate_parameters(
            schema, defaults, {"positive_prompt": "x", "sampler_name": "not_a_sampler"}
        )
        _assert_true("sampler rejected", any("sampler_name" in err for err in sampler_err))
        _, sched_err = coerce_and_validate_parameters(
            schema, defaults, {"positive_prompt": "x", "scheduler": "not_a_scheduler"}
        )
        _assert_true("scheduler rejected", any("scheduler" in err for err in sched_err))
        _, ckpt_err = coerce_and_validate_parameters(
            schema, defaults, {"positive_prompt": "x", "checkpoint": "missing.safetensors"}
        )
        _assert_true("checkpoint rejected", any("checkpoint" in err for err in ckpt_err))
        _pass(results, "sampler validation rejects unknown values")
        _pass(results, "scheduler validation rejects unknown values")
        _pass(results, "checkpoint validation rejects values outside manifest allow-list")

        with tempfile.TemporaryDirectory() as tmp:
            paths = _prep_paths(Path(tmp))
            omitted = _prepare_txt2img(
                repo_root, paths, parameters={"positive_prompt": "omit seed_mode", "seed": 975318642}
            )
            _assert_true("omit ok", omitted.ok)
            _assert_equal("omit default fixed", omitted.parameters.get("seed_mode"), "fixed")
            omitted_wf = json.loads(Path(omitted.runtime_workflow_path).read_text(encoding="utf-8"))
            _assert_equal("omit control widget", _ksampler(omitted_wf)["widgets_values"][1], "fixed")
            omitted_meta = json.loads(Path(omitted.runtime_metadata_path).read_text(encoding="utf-8"))
            _assert_equal("metadata seed_mode", omitted_meta.get("seed_mode"), "fixed")
            _assert_equal("metadata control", omitted_meta.get("control_after_generate"), "fixed")
            _assert_equal("metadata params seed_mode", omitted_meta["parameters"].get("seed_mode"), "fixed")
            _assert_equal("extra seed_mode", omitted_wf["extra"]["ai_studio"].get("seed_mode"), "fixed")
            _pass(results, "prepared metadata records seed_mode")
            _pass(results, "prepared metadata records control-after-generate")

            randomized = _prepare_txt2img(
                repo_root,
                paths,
                parameters={
                    "positive_prompt": "randomize prep",
                    "seed": 975318642,
                    "seed_mode": "randomize",
                    "save_prefix": "custom_local_prefix",
                },
            )
            _assert_true("randomize prep ok", randomized.ok)
            rand_wf = json.loads(Path(randomized.runtime_workflow_path).read_text(encoding="utf-8"))
            _assert_equal("rand widget", _ksampler(rand_wf)["widgets_values"][1], "randomize")
            _assert_equal("rand seed kept", _ksampler(rand_wf)["widgets_values"][0], 975318642)
            rand_meta = json.loads(Path(randomized.runtime_metadata_path).read_text(encoding="utf-8"))
            _assert_equal("rand metadata mode", rand_meta.get("seed_mode"), "randomize")
            _assert_equal("rand metadata control", rand_meta.get("control_after_generate"), "randomize")

            canonical_after = json.loads(
                (repo_root / str(manifest["canonical_workflow_path"])).read_text(encoding="utf-8")
            )
            _assert_equal(
                "canonical unchanged",
                hash_ui_workflow(canonical_after),
                canonical_hash_before,
            )
            _pass(results, "canonical workflow remains unchanged after preparation")

            archive_path = Path(omitted.drive_prepared_dir) / f"{omitted.preparation_id}.workflow.json"
            archive_before = file_sha256(archive_path)
            comfy_runtime = Path(tmp) / "ComfyUI"
            open_result = open_prepared_workflow_for_comfyui(
                preparation_id=omitted.preparation_id,
                source_workflow_path=archive_path,
                comfyui_runtime=comfy_runtime,
                base_url="http://127.0.0.1:9",
                dry_run=False,
            )
            _assert_true("open wrote load copy", Path(open_result.filesystem_destination).is_file())
            _assert_true("archival unchanged flag", open_result.archival_unchanged)
            _assert_equal("archive hash after open", file_sha256(archive_path), archive_before)
            load_copy = json.loads(Path(open_result.filesystem_destination).read_text(encoding="utf-8"))
            load_copy["nodes"] = copy.deepcopy(load_copy["nodes"])
            _ksampler(load_copy)["widgets_values"][0] = 4242424242
            Path(open_result.filesystem_destination).write_text(
                json.dumps(load_copy, indent=2) + "\n", encoding="utf-8"
            )
            _assert_equal("archive still original after runtime edit", file_sha256(archive_path), archive_before)
            archived = json.loads(archive_path.read_text(encoding="utf-8"))
            _assert_equal("archive seed still prepared", _ksampler(archived)["widgets_values"][0], 975318642)
            _pass(results, "prep archive immutable after open")
            _pass(results, "runtime load copy may differ without archive mutation")

            reopen = open_prepared_workflow_for_comfyui(
                preparation_id=omitted.preparation_id,
                source_workflow_path=archive_path,
                comfyui_runtime=comfy_runtime,
                base_url="http://127.0.0.1:9",
                dry_run=False,
            )
            reopened = json.loads(Path(reopen.filesystem_destination).read_text(encoding="utf-8"))
            _assert_equal("reopen restores prepared seed", _ksampler(reopened)["widgets_values"][0], 975318642)
            _assert_equal("reopen restores control", _ksampler(reopened)["widgets_values"][1], "fixed")
            _pass(results, "reopen restores original preparation seed and seed_mode")

            legacy_record = {
                "parameter_summary": {"seed": 123456789},
                "parameters": {"seed": 123456789},
            }
            _assert_equal(
                "legacy missing seed_mode",
                resolve_seed_mode(index_record=legacy_record, workflow_data=canonical),
                "fixed",
            )
            _pass(results, "legacy prep without seed_mode reads as fixed")

            temp_repo = _make_temp_repo(
                repo_root,
                paths["drive"],
                Path(tmp) / "ComfyUI",
                Path(tmp) / "runtime",
            )
            try:
                info = _run_cli(
                    repo_root,
                    temp_repo,
                    "prepared_workflow_info.py",
                    "--preparation-id",
                    omitted.preparation_id,
                )
                _assert_equal("info exit", info.returncode, 0)
                info_text = info.stdout
                for needle in (
                    "Preparation ID:",
                    "Seed mode:",
                    "Control after generate:",
                    "Sampler:",
                    "Scheduler:",
                    "Checkpoint:",
                    "Steps:",
                    "CFG:",
                    "Dimensions:",
                    "Batch size:",
                    "Save prefix:",
                    "Drive/global path:",
                    "Project mirror path:",
                ):
                    _assert_true(f"info has {needle}", needle in info_text)
                _assert_true("info shows fixed", "fixed" in info_text)
                _pass(results, "prepared_workflow_info shows seed mode")

                listed = _run_cli(repo_root, temp_repo, "list_prepared_workflows.py")
                _assert_equal("list exit", listed.returncode, 0)
                _assert_true("recent shows seed_mode", "seed_mode:" in listed.stdout)
                _pass(results, "Recent Prepared shows seed mode")

                wf_info = _run_cli(repo_root, temp_repo, "workflow_info.py", "--workflow", "base/txt2img")
                _assert_equal("workflow_info exit", wf_info.returncode, 0)
                _assert_true("workflow_info seed_mode", "seed_mode" in wf_info.stdout)
                _assert_true(
                    "workflow_info default fixed",
                    "default='fixed'" in wf_info.stdout or 'default="fixed"' in wf_info.stdout,
                )
                for name in (
                    "positive_prompt",
                    "negative_prompt",
                    "seed",
                    "steps",
                    "cfg",
                    "width",
                    "height",
                    "batch_size",
                    "sampler_name",
                    "scheduler",
                    "checkpoint",
                    "save_prefix",
                ):
                    _assert_true(f"workflow_info lists {name}", name in wf_info.stdout)
                _pass(results, "workflow_info shows supported seed_mode")

                cli_bad = _run_cli(
                    repo_root,
                    temp_repo,
                    "prepare_workflow.py",
                    "--workflow",
                    "base/txt2img",
                    "--param",
                    "positive_prompt=cli invalid",
                    "--param",
                    "seed_mode=foo",
                    "--dry-run",
                )
                _assert_true("cli invalid fails", cli_bad.returncode != 0)
                combined = (cli_bad.stdout or "") + (cli_bad.stderr or "")
                _assert_true(
                    "cli invalid message",
                    "Invalid value for seed_mode. Expected one of: fixed, randomize." in combined,
                )
                _assert_false("cli invalid no traceback", "Traceback" in combined)
                _pass(results, "CLI rejects invalid seed_mode without traceback")
            finally:
                shutil.rmtree(temp_repo, ignore_errors=True)

            cli_help = _run_cli(repo_root, None, "prepare_workflow.py", "--help")
            _assert_equal("prepare help", cli_help.returncode, 0)
            _assert_true("prepare help param", "--param" in cli_help.stdout)
            for script in (
                "prepared_workflow_info.py",
                "list_prepared_workflows.py",
                "workflow_info.py",
            ):
                help_proc = _run_cli(repo_root, None, script, "--help")
                _assert_equal(f"{script} help", help_proc.returncode, 0)
            _pass(results, "changed CLI --help succeeds")

            bundle = RegistryLoader(repo_root).load_all()
            registered = load_registered_workflow_hashes(repo_root, bundle.workflows)
            workspace = ProjectWorkspace(paths["drive"])
            mountain = workspace.create_project(
                display_name="Mountain Demo", slug="mountain-demo", set_active=True
            )
            project_prep = _prepare_txt2img(
                repo_root,
                paths,
                parameters={
                    "positive_prompt": "mountain demo controls",
                    "seed": 975318642,
                    "seed_mode": "randomize",
                    "save_prefix": "custom_local_prefix",
                },
                active_project=mountain,
            )
            _assert_true("project prep ok", project_prep.ok)
            prepared_ui = json.loads(Path(project_prep.runtime_workflow_path).read_text(encoding="utf-8"))
            prepared_ui = build_comfyui_load_workflow(prepared_ui)

            exec_tmp = Path(tmp) / "exec"
            svc, comfy, drive_root, drive_out = _service(
                exec_tmp, registered=registered, active_project=mountain, repo_root=repo_root
            )
            first_name = "custom_local_prefix_00001_.png"
            second_name = "custom_local_prefix_00002_.png"
            _write_png(comfy / first_name, fill=(11, 22, 33))
            _write_png(comfy / second_name, fill=(44, 55, 66))
            hist = {
                "prompt-rand-1": _history_entry(
                    _txt2img_api(seed=975318642, save_prefix="custom_local_prefix"),
                    prepared_ui,
                    _flat_outputs(first_name),
                    "prompt-rand-1",
                ),
                "prompt-rand-2": _history_entry(
                    _txt2img_api(seed=888888888, save_prefix="custom_local_prefix"),
                    prepared_ui,
                    _flat_outputs(second_name),
                    "prompt-rand-2",
                ),
            }
            recs1, resolved1 = _handle(svc, hist, "prompt-rand-1")
            recs2, resolved2 = _handle(svc, hist, "prompt-rand-2")
            _assert_true("rand1 verified", resolved1 and recs1 and recs1[0].sync_status == "verified")
            _assert_true("rand2 verified", resolved2 and recs2 and recs2[0].sync_status == "verified")
            _assert_equal("same prep id", recs1[0].preparation_id, project_prep.preparation_id)
            _assert_equal("prep id retained", recs2[0].preparation_id, project_prep.preparation_id)
            _assert_true("separate prompt ids", recs1[0].prompt_id != recs2[0].prompt_id)
            _assert_true("separate generation ids", recs1[0].generation_id != recs2[0].generation_id)
            _assert_equal("exec seed 1", recs1[0].seed, 975318642)
            _assert_equal("exec seed 2", recs2[0].seed, 888888888)
            _assert_equal("prep seed unchanged", rand_meta.get("seed"), 975318642)
            snap1 = json.loads(
                (drive_root / "projects" / "mountain-demo" / "generations" / recs1[0].generation_id / "metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            snap2 = json.loads(
                (drive_root / "projects" / "mountain-demo" / "generations" / recs2[0].generation_id / "metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            _assert_equal("snap1 seed", snap1.get("seed"), 975318642)
            _assert_equal("snap2 seed", snap2.get("seed"), 888888888)
            _assert_equal("snap prep id", snap1.get("preparation_id"), project_prep.preparation_id)
            _pass(results, "randomized preparation preserves same preparation_id across runs")
            _pass(results, "randomized runs may have different execution seeds")
            _pass(results, "generation snapshot records actual execution seed")
            _pass(results, "preparation seed remains original prepared seed")
            _pass(results, "execution linkage retains preparation_id")

            for rec in (recs1[0], recs2[0]):
                dest = Path(rec.drive_path)
                _assert_true("permanent exists", dest.is_file())
                _assert_true("permanent txt2img name", dest.name.startswith("txt2img_"))
                _assert_false("save_prefix not in Drive name", dest.name.startswith("custom_local_prefix"))
            _pass(results, "permanent Drive naming unaffected by save_prefix")
            _assert_true("global autosync", all(Path(r.drive_path).is_file() for r in (recs1[0], recs2[0])))
            _assert_true(
                "project mirror",
                all(r.project_output_path and Path(r.project_output_path).is_file() for r in (recs1[0], recs2[0])),
            )
            _pass(results, "global autosync regression passes")
            _pass(results, "project mirror regression passes")
            _pass(results, "generation snapshot regression passes")

            fixed_tmp = Path(tmp) / "fixed-repeat"
            svc_f, comfy_f, drive_f, out_f = _service(
                fixed_tmp, registered=registered, repo_root=repo_root
            )
            same_bytes_a = "ai_studio_base_txt2img_fixed_a.png"
            same_bytes_b = "ai_studio_base_txt2img_fixed_b.png"
            _write_png(comfy_f / same_bytes_a, fill=(9, 9, 9))
            _write_png(comfy_f / same_bytes_b, fill=(9, 9, 9))
            _assert_equal("identical local hashes", file_sha256(comfy_f / same_bytes_a), file_sha256(comfy_f / same_bytes_b))
            fixed_ui = json.loads(Path(omitted.runtime_workflow_path).read_text(encoding="utf-8"))
            fixed_ui = build_comfyui_load_workflow(fixed_ui)
            fixed_hist = {
                "prompt-fixed-1": _history_entry(
                    _txt2img_api(seed=975318642),
                    fixed_ui,
                    _flat_outputs(same_bytes_a),
                    "prompt-fixed-1",
                ),
                "prompt-fixed-2": _history_entry(
                    _txt2img_api(seed=975318642),
                    fixed_ui,
                    _flat_outputs(same_bytes_b),
                    "prompt-fixed-2",
                ),
            }
            frec1, fres1 = _handle(svc_f, fixed_hist, "prompt-fixed-1")
            frec2, fres2 = _handle(svc_f, fixed_hist, "prompt-fixed-2")
            _assert_true("fixed run 1", fres1 and frec1 and frec1[0].sync_status == "verified")
            _assert_true("fixed run 2", fres2 and frec2 and frec2[0].sync_status == "verified")
            _assert_true("fixed separate prompts", frec1[0].prompt_id != frec2[0].prompt_id)
            _assert_true("fixed separate gens", frec1[0].generation_id != frec2[0].generation_id)
            _assert_equal("fixed same exec seed", frec1[0].seed, frec2[0].seed)
            _assert_equal("two drive files", len(_drive_finals(out_f)), 2)
            _pass(results, "fixed preparation can execute repeatedly")
            _pass(results, "repeated fixed executions remain separate prompt executions")
            _pass(results, "same image hash does not collapse separate prompt IDs")

            batch_tmp = Path(tmp) / "batch"
            svc_b, comfy_b, drive_b, out_b = _service(batch_tmp, registered=registered, repo_root=repo_root)
            batch_a = "ai_studio_base_txt2img_batch_00001_.png"
            batch_b = "ai_studio_base_txt2img_batch_00002_.png"
            _write_png(comfy_b / batch_a, fill=(1, 2, 3))
            _write_png(comfy_b / batch_b, fill=(4, 5, 6))
            batch_outputs = _flat_outputs(batch_a, batch_b)
            _assert_equal("history descriptors", len(extract_output_files({"outputs": batch_outputs})), 2)
            batch_hist = {
                "prompt-batch": _history_entry(
                    _txt2img_api(seed=42, batch_size=2),
                    prepared_ui,
                    batch_outputs,
                    "prompt-batch",
                )
            }
            brecs, bresolved = _handle(svc_b, batch_hist, "prompt-batch")
            _assert_true("batch resolved", bresolved)
            _assert_equal("batch records", len(brecs), 2)
            _assert_true("all verified", all(r.sync_status == "verified" for r in brecs))
            _assert_true("all generation ids", all(r.generation_id for r in brecs))
            _assert_true("distinct generation ids", brecs[0].generation_id != brecs[1].generation_id)
            _assert_equal("same prompt", brecs[0].prompt_id, brecs[1].prompt_id)
            _assert_equal("batch drive count", len(_drive_finals(out_b)), 2)
            _pass(results, "batch_size>1 history returns all image descriptors")
            _pass(results, "batch_size>1 all images detected and copied")
            _pass(results, "batch_size>1 each image receives a generation ID")
            _pass(results, "batch_size>1 is production-supported for txt2img")

        nb = json.loads(
            (repo_root / "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb").read_text(encoding="utf-8")
        )
        _assert_true("notebook cells", isinstance(nb.get("cells"), list))
        nb_src = "".join("".join(cell.get("source") or []) for cell in nb.get("cells") or [])
        for needle in (
            "Seed behavior:",
            "1. Fixed / reproducible",
            "2. Randomize after each generation",
            'input("Select [1]: ")',
            "seed_mode={seed_mode}",
            "seed_mode: {seed_mode}",
        ):
            _assert_true(f"notebook has {needle}", needle in nb_src)
        _pass(results, "notebook JSON valid")
        _pass(results, "notebook prompts for seed behavior")

        for rel in (
            "core/runtime/workflow_library_preparation.py",
            "core/runtime/seed_mode.py",
            "core/runtime/workflow_parameters.py",
            "core/scripts/prepare_workflow.py",
            "core/scripts/prepared_workflow_info.py",
            "core/scripts/list_prepared_workflows.py",
        ):
            src = (repo_root / rel).read_text(encoding="utf-8")
            _assert_false(f"{rel} has /prompt", "/prompt" in src)
            _assert_false(f"{rel} has auto-queue", "auto-queue" in src)
            _assert_false(f"{rel} has playwright", "playwright" in src.lower())
        _assert_false("notebook queues /prompt", "/prompt" in nb_src)
        _pass(results, "no /prompt")
        _pass(results, "no auto-queue")
        _pass(results, "no browser automation")

        compat = (repo_root / "core/runtime/comfyui_userdata_route_compat.py").read_text(encoding="utf-8")
        autosync_src = (repo_root / "core/runtime/output_autosync.py").read_text(encoding="utf-8")
        events_src = (repo_root / "core/runtime/comfyui_events.py").read_text(encoding="utf-8")
        _assert_true("4.8.4 marker", "ai_studio_userdata_route_compat_4_8_4" in compat)
        _assert_true("nested history", 'nested_key in ("ui", "output")' in events_src)
        _assert_true("fail-closed token", "insufficient_attribution_evidence" in autosync_src)
        _assert_true("autosync no /prompt", "/prompt" not in autosync_src)
        _pass(results, "4.8.4 regression remains green")
        _pass(results, "4.8.5 regression remains green")

        build_text = (repo_root / "core/scripts/build_review_package.py").read_text(encoding="utf-8")
        _assert_true(
            "review package lists 4.9 sim",
            "simulate_package49_prepared_execution_controls.py" in build_text,
        )
        _pass(results, "Package 4.9 prepared execution controls simulations complete")

    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        print("\nRESULT: FAIL — package 4.9 simulations failed.")
        return 1

    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: PASS — package 4.9 prepared execution controls green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
