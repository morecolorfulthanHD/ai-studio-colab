#!/usr/bin/env python3
"""Package 4.10.2 — generation reproduction lookup / failed-open UX simulations."""

from __future__ import annotations

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

from core.comfyui.install_nodes import build_git_clone_command
from core.runtime.generation_evidence_ledger import EvidenceRecord, file_sha256
from core.runtime.generation_identity import (
    format_generation_not_found,
    normalize_generation_id,
)
from core.runtime.generation_reproduction import (
    REPRODUCTION_SCOPE_SINGLE,
    REPRODUCTION_SCOPE_SOURCE_BATCH,
    should_prompt_open_reproduction_preparation,
)
from core.runtime.generation_snapshot import create_generation_snapshot, load_snapshot_by_id
from core.runtime.png_utils import write_rgb_png
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import find_repo_root
from core.runtime.workflow_library_preparation import prepare_library_workflow
from core.runtime.workflow_manifest import load_workflow_manifest
from core.runtime.workflow_provenance import ExecutionProvenance


# Exact IDs recorded from Package 4.9 live Case C (prompt 82a0ee4a-...).
CASE_C_PROMPT = "82a0ee4a-bc73-4613-bdea-b917b156c87b"
CASE_C_SEED = 864209753
CASE_C_GID_A = "gen_a92174af-8f69-46e7-a632-18af56b74138"
CASE_C_GID_B = "gen_07052deb-d1ec-4985-bfe6-3779f7cc7d37"
# Live Case C input that failed lookup — valid UUID shape, not a stored ID.
CASE_C_FAILED_INPUT = "gen_a92174af-8f69-46e7-a632-18f9ebf93939"

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


def _prep_paths(root: Path) -> dict[str, Path]:
    drive = root / "AI_Studio"
    runtime = root / "runtime"
    comfy_input = root / "ComfyUI" / "input"
    for sub in ("outputs", "inputs", "masks", "logs", "workflows/prepared", "projects", "generations"):
        (drive / sub).mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "prepared_workflows").mkdir(parents=True, exist_ok=True)
    comfy_input.mkdir(parents=True, exist_ok=True)
    checkpoint = drive / "models" / "checkpoints" / "sd15.safetensors"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    if not checkpoint.is_file():
        checkpoint.write_bytes(b"PK4102-SIM-MODEL-STUB")
    return {
        "drive": drive,
        "runtime_prepared": runtime / "prepared_workflows",
        "drive_prepared": drive / "workflows" / "prepared",
        "comfy_input": comfy_input,
        "comfy_root": root / "ComfyUI",
        "runtime": runtime,
    }


def _make_temp_repo(real_repo: Path, drive_root: Path, comfy_root: Path, runtime_root: Path) -> Path:
    temp_repo = Path(tempfile.mkdtemp(prefix="ai-studio-pkg4102-"))
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


def _txt2img_api(*, seed: int, batch_size: int = 1) -> dict:
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
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ai_studio_base_txt2img", "images": ["8", 0]}},
    }


def _ui_from_prep(prep_workflow: dict, *, execution_seed: int) -> dict:
    data = json.loads(json.dumps(prep_workflow))
    for node in data.get("nodes") or []:
        if node.get("type") == "KSampler":
            widgets = list(node.get("widgets_values") or [])
            while len(widgets) < 2:
                widgets.append(None)
            widgets[0] = execution_seed
            widgets[1] = "fixed"
            node["widgets_values"] = widgets
    return data


def _create_generation(
    *,
    repo_root: Path,
    paths: dict[str, Path],
    preparation_id: str,
    prep_workflow: dict,
    execution_seed: int,
    generation_id: str,
    prompt_id: str,
    batch_size: int,
    fill: tuple[int, int, int],
    output_name: str,
    active_project=None,
) -> str:
    drive = paths["drive"]
    api = _txt2img_api(seed=execution_seed, batch_size=batch_size)
    ui = _ui_from_prep(prep_workflow, execution_seed=execution_seed)
    ui.setdefault("extra", {})
    if isinstance(ui["extra"], dict):
        ai = dict(ui["extra"].get("ai_studio") or {})
        ai["preparation_id"] = preparation_id
        ai["seed"] = execution_seed
        ai["seed_mode"] = "fixed"
        ai["control_after_generate"] = "fixed"
        ui["extra"]["ai_studio"] = ai

    out_path = drive / "outputs" / output_name
    _write_png(out_path, fill=fill)
    project_output = ""
    if active_project is not None:
        project_out = drive / "projects" / active_project.slug / "outputs" / output_name
        project_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_path, project_out)
        project_output = str(project_out)
    sha = file_sha256(out_path)
    record = EvidenceRecord(
        prompt_id=prompt_id,
        output_node_id="9",
        drive_path=str(out_path),
        drive_filename=output_name,
        drive_sha256=sha,
        local_sha256=sha,
        byte_size=out_path.stat().st_size,
        sync_status="verified",
        capability="txt2img",
        model_family="sd15",
        model_files=["sd15.safetensors"],
        positive_prompt="snowy alpine research station",
        negative_prompt="blurry, low quality",
        seed=execution_seed,
        steps=24,
        cfg=7.0,
        sampler_name="euler",
        scheduler="normal",
        width=512,
        height=768,
        workflow_identifier="base/txt2img",
        workflow_source="prepared",
        preparation_id=preparation_id,
        project_id=active_project.project_id if active_project else "",
        project_output_path=project_output,
        generation_id=generation_id,
    )
    provenance = ExecutionProvenance(
        workflow_identifier="base/txt2img",
        workflow_source="prepared",
        capability="txt2img",
        model_family="sd15",
        model_files=["sd15.safetensors"],
        positive_prompt="snowy alpine research station",
        negative_prompt="blurry, low quality",
        seed=execution_seed,
        steps=24,
        cfg=7.0,
        sampler_name="euler",
        scheduler="normal",
        width=512,
        height=768,
        preparation_id=preparation_id,
    )
    snap = create_generation_snapshot(
        drive_root=drive,
        record=record,
        dedupe_key=f"{prompt_id}:9:{output_name}",
        provenance=provenance,
        active_project=active_project,
        index_path=drive / "logs" / "generation_index.jsonl",
        ui_workflow=ui,
        api_prompt=api,
        repo_root=repo_root,
        existing_generation_id=generation_id,
    )
    _assert_true(f"snapshot created {generation_id}", snap.ok)
    _assert_equal("stored generation id", snap.generation_id, generation_id)
    return snap.generation_id


def _count_preps(paths: dict[str, Path]) -> int:
    root = paths["drive_prepared"]
    if not root.is_dir():
        return 0
    return sum(1 for path in root.rglob("*.metadata.json") if path.is_file())


def _notebook_source(real_repo: Path) -> str:
    nb = json.loads(
        (real_repo / "colab" / "notebooks" / "AI_Studio_Control_Panel_Colab.ipynb").read_text(
            encoding="utf-8"
        )
    )
    return "\n".join("".join(cell.get("source") or []) for cell in nb["cells"])


def main() -> int:
    real_repo = find_repo_root(script_file=Path(__file__))
    results: list[tuple[str, str]] = []
    temp_dirs: list[Path] = []
    print("Package 4.10.2 — Generation reproduction lookup hotfix")
    print("=" * 40)

    try:
        _assert_equal(
            "typo is not stored ID A",
            CASE_C_FAILED_INPUT,
            CASE_C_FAILED_INPUT,
        )
        _assert_false("failed input != A", CASE_C_FAILED_INPUT == CASE_C_GID_A)
        _assert_false("failed input != B", CASE_C_FAILED_INPUT == CASE_C_GID_B)
        _assert_equal(
            "typo still normalizes as UUID",
            normalize_generation_id(CASE_C_FAILED_INPUT),
            CASE_C_FAILED_INPUT,
        )
        _pass(results, "failed Case C input is a valid UUID that is not a stored ID")

        root = Path(tempfile.mkdtemp(prefix="pkg4102-root-"))
        temp_dirs.append(root)
        paths = _prep_paths(root)
        temp_repo = _make_temp_repo(real_repo, paths["drive"], paths["comfy_root"], paths["runtime"])
        temp_dirs.append(temp_repo)
        manifest = load_workflow_manifest(temp_repo, "base/txt2img")
        object_info = {str(node): {} for node in (manifest.get("required_nodes") or [])}

        ws = ProjectWorkspace(paths["drive"])
        project = ws.create_project(slug="mountain-demo", display_name="Mountain Demo")
        ws.set_active_project(project.slug)

        batch_prep = prepare_library_workflow(
            temp_repo,
            workflow_identifier="base/txt2img",
            parameters={
                "positive_prompt": "snowy alpine research station",
                "negative_prompt": "blurry, low quality",
                "seed": CASE_C_SEED,
                "seed_mode": "fixed",
                "batch_size": 2,
                "checkpoint": "sd15.safetensors",
            },
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            comfy_object_info=object_info,
            model_files_present=MODEL_FILES_PRESENT,
        )
        _assert_true("batch prep ok", batch_prep.ok)
        batch_wf = json.loads(Path(batch_prep.runtime_workflow_path).read_text(encoding="utf-8"))

        gid_a = _create_generation(
            repo_root=temp_repo,
            paths=paths,
            preparation_id=batch_prep.preparation_id,
            prep_workflow=batch_wf,
            execution_seed=CASE_C_SEED,
            generation_id=CASE_C_GID_A,
            prompt_id=CASE_C_PROMPT,
            batch_size=2,
            fill=(90, 91, 92),
            output_name="txt2img_20260814_000010.png",
            active_project=project,
        )
        gid_b = _create_generation(
            repo_root=temp_repo,
            paths=paths,
            preparation_id=batch_prep.preparation_id,
            prep_workflow=batch_wf,
            execution_seed=CASE_C_SEED,
            generation_id=CASE_C_GID_B,
            prompt_id=CASE_C_PROMPT,
            batch_size=2,
            fill=(93, 94, 95),
            output_name="txt2img_20260814_000011.png",
            active_project=project,
        )
        _assert_equal("stored A", gid_a, CASE_C_GID_A)
        _assert_equal("stored B", gid_b, CASE_C_GID_B)

        snap_a = load_snapshot_by_id(paths["drive"], CASE_C_GID_A)
        snap_b = load_snapshot_by_id(paths["drive"], CASE_C_GID_B)
        _assert_true("snapshot A present", snap_a is not None)
        _assert_true("snapshot B present", snap_b is not None)
        _assert_true(
            "typo snapshot absent",
            load_snapshot_by_id(paths["drive"], CASE_C_FAILED_INPUT) is None,
        )

        info_a = _run_cli(
            real_repo, temp_repo, "generation_info.py", "--generation-id", CASE_C_GID_A, "--summary"
        )
        _assert_equal("info A exit", info_a.returncode, 0)
        _assert_true("info A id", CASE_C_GID_A in (info_a.stdout or ""))
        _pass(results, "exact valid batch generation ID resolves")

        info_b = _run_cli(
            real_repo, temp_repo, "generation_info.py", "--generation-id", CASE_C_GID_B, "--summary"
        )
        _assert_equal("info B exit", info_b.returncode, 0)
        _assert_true("info B id", CASE_C_GID_B in (info_b.stdout or ""))
        _pass(results, "second valid sibling generation ID resolves")

        preps_before = _count_preps(paths)
        missing = _run_cli(
            real_repo,
            temp_repo,
            "generation_info.py",
            "--generation-id",
            CASE_C_FAILED_INPUT,
            "--summary",
        )
        missing_text = (missing.stdout or "") + (missing.stderr or "")
        _assert_equal("typo info exit", missing.returncode, 1)
        _assert_true("typo not found", "Generation not found" in missing_text)
        _assert_true("typo shows typed id", CASE_C_FAILED_INPUT in missing_text)
        _assert_false("typo does not leak stored A", CASE_C_GID_A in missing_text)
        _assert_true("typo no traceback", "Traceback" not in missing_text)
        _assert_true("typo hint", "Use Recent generations to copy an exact ID" in missing_text)

        malformed = _run_cli(
            real_repo, temp_repo, "generation_info.py", "--generation-id", "not-a-uuid", "--summary"
        )
        malformed_text = (malformed.stdout or "") + (malformed.stderr or "")
        _assert_equal("malformed exit", malformed.returncode, 1)
        _assert_true("malformed invalid", "Invalid generation ID" in malformed_text)
        _assert_true("malformed no traceback", "Traceback" not in malformed_text)
        _assert_equal("no prep after failed lookup", _count_preps(paths), preps_before)
        _pass(results, "malformed/nonexistent ID fails cleanly")
        _pass(results, "failed lookup does not create a prep")

        _assert_false(
            "failed lookup does not prompt",
            should_prompt_open_reproduction_preparation(lookup_ok=False, prepare_ok=False),
        )
        _pass(results, "failed lookup does not prompt to Open prepared")

        _assert_false(
            "failed prepare does not prompt",
            should_prompt_open_reproduction_preparation(
                lookup_ok=True, prepare_ok=False, preparation_id=""
            ),
        )
        _pass(results, "failed prepare does not prompt to Open prepared")

        _assert_true(
            "success prompts open",
            should_prompt_open_reproduction_preparation(
                lookup_ok=True,
                prepare_ok=True,
                preparation_id="prep_11111111-1111-1111-1111-111111111111",
            ),
        )
        _pass(results, "successful reproduction does prompt to Open prepared")

        bare = CASE_C_GID_A.removeprefix("gen_")
        info_bare = _run_cli(
            real_repo, temp_repo, "generation_info.py", "--generation-id", bare, "--summary"
        )
        _assert_equal("bare uuid info exit", info_bare.returncode, 0)
        _assert_equal("bare normalizes to A", normalize_generation_id(bare), CASE_C_GID_A)
        _pass(results, "UUID-only input normalization still works")

        lookup_src = (
            (real_repo / "core" / "runtime" / "generation_snapshot.py").read_text(encoding="utf-8")
            + (real_repo / "core" / "scripts" / "generation_info.py").read_text(encoding="utf-8")
            + (real_repo / "core" / "scripts" / "prepare_from_generation.py").read_text(encoding="utf-8")
            + (real_repo / "core" / "runtime" / "generation_identity.py").read_text(encoding="utf-8")
        )
        _assert_false("no difflib", "difflib" in lookup_src)
        _assert_false("no fuzzy", "fuzzy" in lookup_src.lower())
        _assert_false("no autocorrect", "autocorrect" in lookup_src.lower())
        expected_not_found = format_generation_not_found(CASE_C_FAILED_INPUT)
        _assert_true("not-found formatter names typed id", CASE_C_FAILED_INPUT in expected_not_found)
        _pass(results, "no fuzzy/autocorrect selection")

        prep_a = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            CASE_C_GID_A,
            "--json",
        )
        _assert_equal("prepare A exit", prep_a.returncode, 0)
        payload_a = json.loads(prep_a.stdout)
        _assert_true("prepare A ok", payload_a.get("ok") is True)
        _assert_equal("batch_size 2", payload_a.get("parameters", {}).get("batch_size"), 2)
        _assert_equal("scope batch", payload_a.get("reproduction_scope"), REPRODUCTION_SCOPE_SOURCE_BATCH)
        _assert_equal("seed preserved", payload_a.get("parameters", {}).get("seed"), CASE_C_SEED)
        _assert_equal("seed_mode fixed", payload_a.get("parameters", {}).get("seed_mode"), "fixed")
        _assert_equal(
            "lineage source A",
            payload_a.get("lineage", {}).get("reproduction_source_generation_id"),
            CASE_C_GID_A,
        )
        _assert_equal(
            "source_output_index null",
            payload_a.get("lineage", {}).get("source_output_index"),
            None,
        )
        _pass(results, "batch source produces batch_size=2")
        _pass(results, "batch source produces reproduction_scope=source_batch_execution")
        _pass(results, "executed seed 864209753 preserved")
        _pass(results, "source generation lineage preserved")
        _pass(results, "source_output_index remains null")

        prep_b = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            CASE_C_GID_B,
            "--json",
        )
        _assert_equal("prepare B exit", prep_b.returncode, 0)
        payload_b = json.loads(prep_b.stdout)
        _assert_true("sibling distinct prep", payload_b.get("preparation_id") != payload_a.get("preparation_id"))
        _assert_equal(
            "sibling lineage B",
            payload_b.get("lineage", {}).get("reproduction_source_generation_id"),
            CASE_C_GID_B,
        )
        _assert_equal("sibling batch_size", payload_b.get("parameters", {}).get("batch_size"), 2)

        failed_prep = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            CASE_C_FAILED_INPUT,
            "--json",
        )
        _assert_equal("typo prepare exit", failed_prep.returncode, 1)
        failed_payload = json.loads(failed_prep.stdout) if failed_prep.stdout.strip().startswith("{") else {}
        _assert_false("typo prepare not ok", bool(failed_payload.get("ok")))
        _assert_false("typo prepare no prep id", bool(failed_payload.get("preparation_id")))

        # Case A/B: batch_size=1 remains single_generation.
        single_prep = prepare_library_workflow(
            temp_repo,
            workflow_identifier="base/txt2img",
            parameters={
                "positive_prompt": "snowy alpine research station",
                "negative_prompt": "blurry, low quality",
                "seed": 135791357,
                "seed_mode": "fixed",
                "batch_size": 1,
                "checkpoint": "sd15.safetensors",
            },
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            comfy_object_info=object_info,
            model_files_present=MODEL_FILES_PRESENT,
        )
        _assert_true("single prep ok", single_prep.ok)
        single_wf = json.loads(Path(single_prep.runtime_workflow_path).read_text(encoding="utf-8"))
        single_gid = _create_generation(
            repo_root=temp_repo,
            paths=paths,
            preparation_id=single_prep.preparation_id,
            prep_workflow=single_wf,
            execution_seed=135791357,
            generation_id="gen_11111111-1111-1111-1111-111111111111",
            prompt_id="11111111-2222-3333-4444-555555555555",
            batch_size=1,
            fill=(10, 20, 30),
            output_name="txt2img_case_a.png",
            active_project=project,
        )
        single_result = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            single_gid,
            "--json",
        )
        _assert_equal("case A/B prepare exit", single_result.returncode, 0)
        single_payload = json.loads(single_result.stdout)
        _assert_equal("case A/B batch_size", single_payload.get("parameters", {}).get("batch_size"), 1)
        _assert_equal(
            "case A/B scope",
            single_payload.get("reproduction_scope"),
            REPRODUCTION_SCOPE_SINGLE,
        )
        _assert_equal("case A/B seed", single_payload.get("parameters", {}).get("seed"), 135791357)
        _pass(results, "Package 4.10 Case A/B behavior unchanged")

        retry_cmd = build_git_clone_command(
            "https://example.com/repo.git",
            "/tmp/target",
            force_http1=True,
        )
        _assert_true("4101 retry -c", "-c" in retry_cmd)
        _assert_true("4101 http.version", "http.version=HTTP/1.1" in retry_cmd)
        install_src = (real_repo / "core" / "comfyui" / "install_nodes.py").read_text(encoding="utf-8")
        _assert_false("4101 no GIT_HTTP_VERSION", "GIT_HTTP_VERSION" in install_src)
        _pass(results, "Package 4.10.1 bootstrap behavior unchanged")

        nb_path = real_repo / "colab" / "notebooks" / "AI_Studio_Control_Panel_Colab.ipynb"
        nb = json.loads(nb_path.read_text(encoding="utf-8"))
        _assert_true("notebook JSON valid", isinstance(nb.get("cells"), list))
        joined = _notebook_source(real_repo)
        _assert_true("echo normalized id", "Using generation ID:" in joined)
        _assert_true("info returncode gate", "info_result" in joined and "returncode" in joined)
        _assert_true("prep returncode gate", "prep_result" in joined)
        info_idx = joined.find("info_result")
        open_idx = joined.find("Open the new preparation in ComfyUI now?")
        prep_gate_idx = joined.find("prep_result")
        _assert_true("info gate before open", 0 <= info_idx < open_idx)
        _assert_true("prep gate before open", 0 <= prep_gate_idx < open_idx)
        _assert_true(
            "helper imported",
            "should_prompt_open_reproduction_preparation" in joined,
        )
        _pass(results, "notebook JSON valid")
        _pass(results, "notebook stops before Open prepared on failed lookup/prepare")

        help_info = _run_cli(real_repo, None, "generation_info.py", "--help")
        _assert_equal("generation_info --help", help_info.returncode, 0)
        help_prep = _run_cli(real_repo, None, "prepare_from_generation.py", "--help")
        _assert_equal("prepare_from_generation --help", help_prep.returncode, 0)
        _pass(results, "changed CLI --help succeeds")

        build_src = (real_repo / "core" / "scripts" / "build_review_package.py").read_text(encoding="utf-8")
        _assert_true(
            "review package lists 4102",
            "simulate_package4102_generation_reproduction_lookup.py" in build_src,
        )
        _pass(results, "review package includes Package 4.10.2 sim")

    except SimulationFailure as exc:
        results.append(("FAIL", str(exc)))
        print(f"  [FAIL] {exc}")
    except Exception as exc:  # noqa: BLE001
        results.append(("FAIL", f"unexpected: {exc}"))
        print(f"  [FAIL] unexpected: {exc}")
        raise
    finally:
        for path in temp_dirs:
            shutil.rmtree(path, ignore_errors=True)

    passed = sum(1 for status, _ in results if status == "PASS")
    failed = sum(1 for status, _ in results if status == "FAIL")
    print()
    print(f"Package 4.10.2 results: {passed} passed, {failed} failed, {len(results)} total")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
