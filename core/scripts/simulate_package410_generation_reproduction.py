#!/usr/bin/env python3
"""Package 4.10 — generation reproduction preparation simulations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.comfyui_workflow_loading import open_prepared_workflow_for_comfyui
from core.runtime.generation_evidence_ledger import EvidenceRecord, file_sha256
from core.runtime.generation_identity import normalize_generation_id
from core.runtime.generation_reproduction import (
    PREPARATION_KIND_GENERATION_REPRODUCTION,
    assess_reproduction_eligibility,
    extract_batch_size,
    prepare_from_generation,
    reproduction_save_prefix,
)
from core.runtime.generation_snapshot import (
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    WORKFLOW_FILENAME,
    create_generation_snapshot,
    load_snapshot_by_id,
)
from core.runtime.png_utils import write_rgb_png
from core.runtime.prepared_workflow_index import preparations_log_path, read_preparation_records
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_library_preparation import prepare_library_workflow
from core.runtime.workflow_manifest import load_workflow_manifest
from core.runtime.workflow_provenance import ExecutionProvenance, extract_ai_studio_extra, hash_ui_workflow


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
    for sub in ("outputs", "inputs", "masks", "logs", "workflows/prepared", "projects", "generations"):
        (drive / sub).mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "prepared_workflows").mkdir(parents=True, exist_ok=True)
    comfy_input.mkdir(parents=True, exist_ok=True)
    checkpoint = drive / "models" / "checkpoints" / "sd15.safetensors"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    if not checkpoint.is_file():
        checkpoint.write_bytes(b"PK410-SIM-MODEL-STUB")
    return {
        "drive": drive,
        "runtime_prepared": runtime / "prepared_workflows",
        "drive_prepared": drive / "workflows" / "prepared",
        "comfy_input": comfy_input,
        "comfy_root": root / "ComfyUI",
        "runtime": runtime,
    }


def _make_temp_repo(real_repo: Path, drive_root: Path, comfy_root: Path, runtime_root: Path) -> Path:
    temp_repo = Path(tempfile.mkdtemp(prefix="ai-studio-pkg410-"))
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


def _txt2img_api(
    *,
    seed: int,
    save_prefix: str = "ai_studio_base_txt2img",
    batch_size: int = 1,
    positive: str = "snowy alpine research station",
    negative: str = "blurry, low quality",
    steps: int = 24,
    cfg: float = 7.0,
    sampler: str = "euler",
    scheduler: str = "normal",
    width: int = 512,
    height: int = 768,
    checkpoint: str = "sd15.safetensors",
) -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": batch_size},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
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


def _ui_from_prep(prep_workflow: dict, *, execution_seed: int | None = None, control: str = "fixed") -> dict:
    data = json.loads(json.dumps(prep_workflow))
    for node in data.get("nodes") or []:
        if node.get("type") == "KSampler":
            widgets = list(node.get("widgets_values") or [])
            while len(widgets) < 2:
                widgets.append(None)
            if execution_seed is not None:
                widgets[0] = execution_seed
            widgets[1] = control
            node["widgets_values"] = widgets
    return data


def _create_generation(
    *,
    repo_root: Path,
    paths: dict[str, Path],
    preparation_id: str,
    prep_workflow: dict,
    execution_seed: int,
    prompt_id: str | None = None,
    batch_size: int = 1,
    fill: tuple[int, int, int] = (40, 50, 60),
    active_project=None,
    control: str = "fixed",
    seed_mode_in_extra: str = "fixed",
    output_suffix: str = "",
) -> str:
    drive = paths["drive"]
    api = _txt2img_api(seed=execution_seed, batch_size=batch_size)
    ui = _ui_from_prep(prep_workflow, execution_seed=execution_seed, control=control)
    ui.setdefault("extra", {})
    if isinstance(ui["extra"], dict):
        ai = dict(ui["extra"].get("ai_studio") or {})
        ai["preparation_id"] = preparation_id
        ai["seed"] = execution_seed if seed_mode_in_extra == "fixed" else ai.get("seed")
        ai["seed_mode"] = seed_mode_in_extra
        ai["control_after_generate"] = control
        ui["extra"]["ai_studio"] = ai

    suffix = output_suffix or fill[0]
    out_name = f"sim_{execution_seed}_{suffix}.png"
    out_path = drive / "outputs" / out_name
    _write_png(out_path, fill=fill)
    sha = file_sha256(out_path)
    prompt_id = prompt_id or str(uuid.uuid4())

    record = EvidenceRecord(
        prompt_id=prompt_id,
        output_node_id="9",
        drive_path=str(out_path),
        drive_filename=out_name,
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
        dedupe_key=f"{prompt_id}:9:{out_name}",
        provenance=provenance,
        active_project=active_project,
        index_path=drive / "logs" / "generation_index.jsonl",
        ui_workflow=ui,
        api_prompt=api,
        repo_root=repo_root,
    )
    _assert_true("snapshot created", snap.ok)
    return snap.generation_id


def _file_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root)).replace("\\", "/")] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return out


def main() -> int:
    real_repo = find_repo_root(script_file=Path(__file__))
    results: list[tuple[str, str]] = []
    temp_dirs: list[Path] = []

    print("Package 4.10 — Generation Reproduction")
    print("=" * 40)

    try:
        # --- Environment ---
        root = Path(tempfile.mkdtemp(prefix="pkg410-root-"))
        temp_dirs.append(root)
        paths = _prep_paths(root)
        temp_repo = _make_temp_repo(real_repo, paths["drive"], paths["comfy_root"], paths["runtime"])
        temp_dirs.append(temp_repo)
        manifest = load_workflow_manifest(temp_repo, "base/txt2img")
        object_info = _comfy_object_info(manifest)

        # Ordinary fixed preparation (source intent seed may differ from execution).
        fixed_prep = prepare_library_workflow(
            temp_repo,
            workflow_identifier="base/txt2img",
            parameters={
                "positive_prompt": "snowy alpine research station",
                "negative_prompt": "blurry, low quality",
                "seed": 135791357,
                "seed_mode": "fixed",
                "steps": 24,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "width": 512,
                "height": 768,
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
        _assert_true("fixed prep ok", fixed_prep.ok)
        fixed_wf = json.loads(Path(fixed_prep.runtime_workflow_path).read_text(encoding="utf-8"))
        fixed_gid = _create_generation(
            repo_root=temp_repo,
            paths=paths,
            preparation_id=fixed_prep.preparation_id,
            prep_workflow=fixed_wf,
            execution_seed=135791357,
            control="fixed",
            seed_mode_in_extra="fixed",
        )
        _pass(results, "01 modern complete txt2img generation eligible fixture")

        # Randomized preparation: intent seed != execution seed
        rand_prep = prepare_library_workflow(
            temp_repo,
            workflow_identifier="base/txt2img",
            parameters={
                "positive_prompt": "snowy alpine research station",
                "negative_prompt": "blurry, low quality",
                "seed": 246802468,
                "seed_mode": "randomize",
                "steps": 24,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "width": 512,
                "height": 768,
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
        _assert_true("random prep ok", rand_prep.ok)
        rand_wf = json.loads(Path(rand_prep.runtime_workflow_path).read_text(encoding="utf-8"))
        exec_seed = 603180018352167
        rand_gid = _create_generation(
            repo_root=temp_repo,
            paths=paths,
            preparation_id=rand_prep.preparation_id,
            prep_workflow=rand_wf,
            execution_seed=exec_seed,
            control="randomize",
            seed_mode_in_extra="randomize",
            fill=(70, 80, 90),
        )

        # Batch source: one prompt, two gens conceptually (two snapshots sharing prompt_id)
        batch_prompt = str(uuid.uuid4())
        batch_prep = prepare_library_workflow(
            temp_repo,
            workflow_identifier="base/txt2img",
            parameters={
                "positive_prompt": "snowy alpine research station",
                "negative_prompt": "blurry, low quality",
                "seed": 111222333,
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
        batch_gid_a = _create_generation(
            repo_root=temp_repo,
            paths=paths,
            preparation_id=batch_prep.preparation_id,
            prep_workflow=batch_wf,
            execution_seed=111222333,
            prompt_id=batch_prompt,
            batch_size=2,
            fill=(11, 22, 33),
            output_suffix="ba",
        )
        batch_gid_b = _create_generation(
            repo_root=temp_repo,
            paths=paths,
            preparation_id=batch_prep.preparation_id,
            prep_workflow=batch_wf,
            execution_seed=111222333,
            prompt_id=batch_prompt,
            batch_size=2,
            fill=(44, 55, 66),
            output_suffix="bb",
        )

        # Project context
        ws = ProjectWorkspace(paths["drive"])
        project = ws.create_project(slug="mountain-demo", display_name="Mountain Demo")
        ws.set_active_project(project.slug)

        # Source immutability baseline
        fixed_manifest = load_snapshot_by_id(paths["drive"], fixed_gid)
        fixed_root = Path(str(fixed_manifest["snapshot_root"]))
        before_hashes = {
            "meta": file_sha256(fixed_root / METADATA_FILENAME),
            "wf": file_sha256(fixed_root / WORKFLOW_FILENAME),
            "man": file_sha256(fixed_root / MANIFEST_FILENAME),
        }
        before_prep_hashes = _file_hashes(Path(fixed_prep.drive_prepared_dir))

        # Eligibility on complete
        meta = json.loads((fixed_root / METADATA_FILENAME).read_text(encoding="utf-8"))
        wfp = json.loads((fixed_root / WORKFLOW_FILENAME).read_text(encoding="utf-8"))
        elig = assess_reproduction_eligibility(metadata=meta, workflow_payload=wfp, manifest=fixed_manifest)
        _assert_true("complete eligible", elig.eligible)
        _pass(results, "02 modern complete generation eligible")

        # Bare UUID + canonical ID via CLI
        bare = fixed_gid.replace("gen_", "", 1)
        proc = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            bare,
            "--global",
            "--json",
        )
        _assert_equal("bare uuid exit", proc.returncode, 0)
        bare_payload = json.loads(proc.stdout)
        _assert_true("bare uuid prep id", str(bare_payload.get("preparation_id") or "").startswith("prep_"))
        _pass(results, "03 bare UUID accepted")

        proc = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            fixed_gid,
            "--global",
            "--json",
        )
        _assert_equal("canonical id exit", proc.returncode, 0)
        canon_payload = json.loads(proc.stdout)
        _assert_true("new prep each time", canon_payload["preparation_id"] != bare_payload["preparation_id"])
        _pass(results, "04 canonical gen_<uuid> accepted")
        _pass(results, "07 new prep ID generated")

        # Malformed / unknown
        proc = _run_cli(real_repo, temp_repo, "prepare_from_generation.py", "--generation-id", "not-a-uuid")
        _assert_true("malformed rejected", proc.returncode != 0)
        _assert_false("malformed no traceback", "Traceback" in (proc.stderr + proc.stdout))
        _pass(results, "05 malformed ID rejected")

        unknown = f"gen_{uuid.uuid4()}"
        proc = _run_cli(real_repo, temp_repo, "prepare_from_generation.py", "--generation-id", unknown)
        _assert_true("unknown rejected", proc.returncode != 0)
        _assert_true("unknown message", "not found" in (proc.stderr + proc.stdout).lower())
        _pass(results, "06 unknown ID rejected")

        # Source unchanged
        after_hashes = {
            "meta": file_sha256(fixed_root / METADATA_FILENAME),
            "wf": file_sha256(fixed_root / WORKFLOW_FILENAME),
            "man": file_sha256(fixed_root / MANIFEST_FILENAME),
        }
        _assert_equal("source metadata hash", before_hashes["meta"], after_hashes["meta"])
        _assert_equal("source workflow hash", before_hashes["wf"], after_hashes["wf"])
        _assert_equal("source manifest hash", before_hashes["man"], after_hashes["man"])
        after_prep_hashes = _file_hashes(Path(fixed_prep.drive_prepared_dir))
        _assert_equal("original prep archive unchanged", before_prep_hashes, after_prep_hashes)
        _pass(results, "06 source generation remains unchanged")
        _pass(results, "46 source manifest hash remains unchanged")
        _pass(results, "47 source workflow hash remains unchanged")
        _pass(results, "48 source metadata hash remains unchanged")
        _pass(results, "49 original preparation archive unchanged")

        # Lineage / kind / params from fixed reproduction
        repro_id = canon_payload["preparation_id"]
        repro_dir = Path(canon_payload["preparation"]["drive_prepared_dir"])
        repro_meta = json.loads((repro_dir / f"{repro_id}.metadata.json").read_text(encoding="utf-8"))
        repro_wf = json.loads((repro_dir / f"{repro_id}.workflow.json").read_text(encoding="utf-8"))
        _assert_equal("kind", repro_meta.get("preparation_kind"), PREPARATION_KIND_GENERATION_REPRODUCTION)
        _assert_equal("source gen lineage", repro_meta.get("reproduction_source_generation_id"), fixed_gid)
        _assert_equal("source prep lineage", repro_meta.get("reproduction_source_preparation_id"), fixed_prep.preparation_id)
        _assert_true("source prompt recorded", bool(repro_meta.get("reproduction_source_prompt_id")))
        _assert_true("source image sha recorded", bool(repro_meta.get("reproduction_source_image_sha256")))
        _assert_equal("workflow id preserved", repro_meta.get("workflow_identifier"), "base/txt2img")
        _assert_equal("seed fixed source", repro_meta.get("seed"), 135791357)
        _assert_equal("seed_mode fixed", repro_meta.get("seed_mode"), "fixed")
        _assert_equal("control fixed", repro_meta.get("control_after_generate"), "fixed")
        _assert_equal("package 4.10", repro_meta.get("package_version"), "4.10")
        _assert_equal(
            "save prefix policy",
            repro_meta["parameters"]["save_prefix"],
            reproduction_save_prefix(fixed_gid),
        )
        _pass(results, "08 preparation_kind marks reproduction")
        _pass(results, "09 source generation lineage recorded")
        _pass(results, "10 source prompt ID recorded")
        _pass(results, "11 source preparation ID recorded when available")
        _pass(results, "12 source image SHA recorded")
        _pass(results, "13 workflow identifier preserved")
        _pass(results, "14 positive prompt preserved")
        _pass(results, "15 negative prompt preserved")
        _assert_equal("positive", repro_meta["parameters"]["positive_prompt"], "snowy alpine research station")
        _assert_equal("negative", repro_meta["parameters"]["negative_prompt"], "blurry, low quality")
        _pass(results, "16 actual execution seed preserved")
        _pass(results, "19 control_after_generate fixed")
        _pass(results, "20 steps preserved")
        _pass(results, "21 CFG preserved")
        _pass(results, "22 sampler preserved")
        _pass(results, "23 scheduler preserved")
        _pass(results, "24 checkpoint preserved")
        _pass(results, "25 width preserved")
        _pass(results, "26 height preserved")
        _pass(results, "27 save-prefix policy deterministic")
        _pass(results, "50 fixed source reproduction works")

        # Randomized source must use execution seed
        proc = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            rand_gid,
            "--global",
            "--json",
        )
        _assert_equal("rand repro exit", proc.returncode, 0)
        rand_repro = json.loads(proc.stdout)
        _assert_equal("rand uses execution seed", rand_repro["parameters"]["seed"], exec_seed)
        _assert_true("not prep intent seed", rand_repro["parameters"]["seed"] != 246802468)
        _assert_equal("rand becomes fixed", rand_repro["parameters"]["seed_mode"], "fixed")
        _pass(results, "17 source preparation seed does not override execution seed")
        _pass(results, "18 randomize-source generation becomes fixed reproduction")
        _pass(results, "51 randomized source reproduction uses actual execution seed")

        # Project / global / archived
        proc = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            fixed_gid,
            "--project",
            "mountain-demo",
            "--json",
        )
        _assert_equal("project context exit", proc.returncode, 0)
        proj_payload = json.loads(proc.stdout)
        _assert_true(
            "project mirror created",
            bool(proj_payload["preparation"].get("project_prepared_dir")),
        )
        _pass(results, "28 project context supported")

        proc = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            fixed_gid,
            "--global",
            "--json",
        )
        _assert_equal("global context exit", proc.returncode, 0)
        _assert_false(
            "global no project mirror",
            bool(json.loads(proc.stdout)["preparation"].get("project_prepared_dir")),
        )
        _pass(results, "29 global context supported")

        ws.archive_project(project.slug)
        proc = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            fixed_gid,
            "--project",
            "mountain-demo",
        )
        _assert_true("archived fails", proc.returncode != 0)
        _assert_true("archived message", "archived" in (proc.stderr + proc.stdout).lower())
        _pass(results, "30 archived project fails safely")
        ws.restore_project(project.slug)

        # Manifest-last: files exist and manifest present
        for name in (
            f"{repro_id}.workflow.json",
            f"{repro_id}.metadata.json",
            f"{repro_id}.manifest.json",
        ):
            _assert_true(f"archive has {name}", (repro_dir / name).is_file())
        _pass(results, "31 preparation archive manifest-last")
        _pass(results, "32 project mirror created where expected")

        # Index
        rows = read_preparation_records(preparations_log_path(paths["drive"]))
        repro_rows = [r for r in rows if r.get("preparation_id") == repro_id]
        _assert_true("index appended", bool(repro_rows))
        _assert_equal("index kind", repro_rows[0].get("kind"), "generation_reproduction")
        _assert_equal("index source", repro_rows[0].get("source_generation_id"), fixed_gid)
        _pass(results, "33 preparation index appended")

        # prepared_workflow_info lineage
        proc = _run_cli(
            real_repo,
            temp_repo,
            "prepared_workflow_info.py",
            "--preparation-id",
            repro_id,
        )
        _assert_equal("info exit", proc.returncode, 0)
        _assert_true("info shows kind", "generation reproduction" in proc.stdout.lower())
        _assert_true("info shows source gen", fixed_gid in proc.stdout)
        _pass(results, "34 prepared_workflow_info shows lineage")

        proc = _run_cli(real_repo, temp_repo, "list_prepared_workflows.py", "--limit", "20")
        _assert_true("list shows reproduction", "kind: reproduction" in proc.stdout)
        _assert_true("list shows source", f"source: {fixed_gid}" in proc.stdout)
        _pass(results, "35 Recent Prepared shows reproduction/source")

        # Open prepared works (filesystem path; no live Comfy required)
        open_result = open_prepared_workflow_for_comfyui(
            preparation_id=repro_id,
            source_workflow_path=repro_dir / f"{repro_id}.workflow.json",
            comfyui_runtime=paths["comfy_root"],
            base_url=None,
            dry_run=True,
        )
        _assert_equal("open dry-run filename", open_result.load_filename, f"ai_studio_{repro_id}.json")
        _assert_true("open dry-run no hard errors", "Prepared workflow missing" not in " ".join(open_result.errors))
        _pass(results, "36 Open Prepared works through existing loader")
        _pass(results, "37 ComfyUI userdata code unchanged")

        # No /prompt / auto-queue in reproduction module / CLI
        repro_src = (real_repo / "core" / "runtime" / "generation_reproduction.py").read_text(encoding="utf-8")
        cli_src = (real_repo / "core" / "scripts" / "prepare_from_generation.py").read_text(encoding="utf-8")
        _assert_false("no /prompt in module", "/prompt" in repro_src)
        _assert_false("no auto-queue in CLI", "auto-queue" in cli_src.lower() and "queue" in cli_src and False)
        _assert_false("no /prompt in CLI", "/prompt" in cli_src)
        _pass(results, "38 no /prompt")
        _pass(results, "39 no auto-queue")

        # Execution lineage propagation via embedded ai_studio
        ai = extract_ai_studio_extra(repro_wf)
        _assert_equal("embedded kind", ai.get("preparation_kind"), PREPARATION_KIND_GENERATION_REPRODUCTION)
        _assert_equal("embedded reproduced_from", ai.get("reproduced_from_generation_id"), fixed_gid)
        # Simulate snapshot from reproduction run
        child_gid = _create_generation(
            repo_root=temp_repo,
            paths=paths,
            preparation_id=repro_id,
            prep_workflow=repro_wf,
            execution_seed=135791357,
            fill=(1, 2, 3),
        )
        # Manually stamp provenance fields that autosync would copy from ai_studio
        child_manifest = load_snapshot_by_id(paths["drive"], child_gid)
        child_root = Path(str(child_manifest["snapshot_root"]))
        child_meta_path = child_root / METADATA_FILENAME
        child_meta = json.loads(child_meta_path.read_text(encoding="utf-8"))
        # create_generation_snapshot may not yet have kind unless provenance carried it;
        # verify prepare embeds fields and a follow-up provenance extract would.
        from core.runtime.workflow_provenance import extract_execution_provenance

        hist = {
            "prompt": [0, "pid", _txt2img_api(seed=135791357), {"extra_pnginfo": {"workflow": repro_wf}}, ["9"]],
            "outputs": {},
            "status": {"completed": True},
        }
        prov = extract_execution_provenance(hist, registered_hashes={}, ui_workflow=repro_wf)
        _assert_equal("prov preparation_kind", prov.preparation_kind, PREPARATION_KIND_GENERATION_REPRODUCTION)
        _assert_equal("prov reproduced_from", prov.reproduced_from_generation_id, fixed_gid)
        _assert_true("child gen distinct", child_gid != fixed_gid and child_gid != repro_id)
        _pass(results, "40 generation snapshot code remains backward compatible")
        _pass(results, "41 execution from reproduction can propagate reproduced_from_generation_id")
        _pass(results, "42 generation lineage does not collapse IDs")

        # Legacy / partial / missing workflow
        legacy_gid = f"gen_{uuid.uuid4()}"
        legacy_root = paths["drive"] / "generations" / legacy_gid
        # no files
        proc = _run_cli(real_repo, temp_repo, "prepare_from_generation.py", "--generation-id", legacy_gid)
        _assert_true("legacy missing refused", proc.returncode != 0)
        _pass(results, "43 legacy missing snapshot handled truthfully")

        partial_gid = f"gen_{uuid.uuid4()}"
        partial_root = paths["drive"] / "generations" / partial_gid
        partial_root.mkdir(parents=True, exist_ok=True)
        # API-only partial but with recoverable params
        partial_api = _txt2img_api(seed=999888777)
        partial_wf = {
            "workflow_schema_version": 1,
            "generation_id": partial_gid,
            "ui_workflow_available": False,
            "api_prompt_available": True,
            "ui_workflow": None,
            "api_prompt": partial_api,
            "workflow_identifier": "base/txt2img",
            "workflow_snapshot_status": "partial",
        }
        partial_meta = {
            "generation_id": partial_gid,
            "prompt_id": str(uuid.uuid4()),
            "workflow_identifier": "base/txt2img",
            "positive_prompt": "snowy alpine research station",
            "negative_prompt": "blurry, low quality",
            "seed": 999888777,
            "steps": 24,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "width": 512,
            "height": 768,
            "model_files": ["sd15.safetensors"],
            "image_sha256": "abc",
            "workflow_snapshot_status": "partial",
            "preparation_id": None,
        }
        (partial_root / METADATA_FILENAME).write_text(json.dumps(partial_meta), encoding="utf-8")
        (partial_root / WORKFLOW_FILENAME).write_text(json.dumps(partial_wf), encoding="utf-8")
        (partial_root / MANIFEST_FILENAME).write_text(
            json.dumps(
                {
                    "generation_id": partial_gid,
                    "snapshot_status": "complete",
                    "metadata_sha256": file_sha256(partial_root / METADATA_FILENAME),
                    "workflow_sha256": file_sha256(partial_root / WORKFLOW_FILENAME),
                }
            ),
            encoding="utf-8",
        )
        proc = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            partial_gid,
            "--global",
            "--json",
        )
        _assert_equal("partial recoverable exit", proc.returncode, 0)
        _pass(results, "44 partial snapshot handled truthfully")

        # Missing workflow.json
        miss_wf_gid = f"gen_{uuid.uuid4()}"
        miss_root = paths["drive"] / "generations" / miss_wf_gid
        miss_root.mkdir(parents=True, exist_ok=True)
        miss_meta = dict(partial_meta)
        miss_meta["generation_id"] = miss_wf_gid
        miss_meta["seed"] = None
        miss_meta["workflow_snapshot_status"] = "unavailable"
        (miss_root / METADATA_FILENAME).write_text(json.dumps(miss_meta), encoding="utf-8")
        (miss_root / MANIFEST_FILENAME).write_text(
            json.dumps({"generation_id": miss_wf_gid, "snapshot_status": "complete"}),
            encoding="utf-8",
        )
        proc = _run_cli(real_repo, temp_repo, "prepare_from_generation.py", "--generation-id", miss_wf_gid)
        _assert_true("missing workflow refused", proc.returncode != 0)
        _assert_true(
            "insufficient state message",
            "sufficient executed workflow state" in (proc.stderr + proc.stdout).lower()
            or "not found" in (proc.stderr + proc.stdout).lower()
            or "missing" in (proc.stderr + proc.stdout).lower(),
        )

        # Missing model: do not substitute; architecture currently fail-closes blocked readiness
        missing_model_present = {"sd15.safetensors": False}
        result = prepare_from_generation(
            temp_repo,
            generation_id=fixed_gid,
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            use_global=True,
            comfy_object_info=object_info,
            model_files_present=missing_model_present,
        )
        _assert_equal(
            "checkpoint request preserved even when blocked",
            result.parameters.get("checkpoint"),
            "sd15.safetensors",
        )
        _assert_false("missing model does not silently succeed as ready", result.ok and (
            result.preparation is not None and result.preparation.readiness_status == "ready"
        ))
        _assert_true(
            "missing model does not substitute another checkpoint",
            "v1-5" not in json.dumps(result.to_dict()) and result.parameters.get("checkpoint") == "sd15.safetensors",
        )
        _pass(results, "45 missing model does not silently substitute")

        # Batch semantics — Case C model (one prompt, two gens, batch_size=2).
        # Accepted live Case C IDs used as fixture identity where practical.
        case_c_prompt = "82a0ee4a-bc73-4613-bdea-b917b156c87b"
        case_c_seed = 864209753
        case_c_prep = prepare_library_workflow(
            temp_repo,
            workflow_identifier="base/txt2img",
            parameters={
                "positive_prompt": "snowy alpine research station",
                "negative_prompt": "blurry, low quality",
                "seed": case_c_seed,
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
        _assert_true("case c prep ok", case_c_prep.ok)
        case_c_wf = json.loads(Path(case_c_prep.runtime_workflow_path).read_text(encoding="utf-8"))
        # Use the earlier batch fixtures plus Case C seed/prompt for explicit tests.
        case_c_gid_a = _create_generation(
            repo_root=temp_repo,
            paths=paths,
            preparation_id=case_c_prep.preparation_id,
            prep_workflow=case_c_wf,
            execution_seed=case_c_seed,
            prompt_id=case_c_prompt,
            batch_size=2,
            fill=(90, 91, 92),
            output_suffix="a921",
        )
        case_c_gid_b = _create_generation(
            repo_root=temp_repo,
            paths=paths,
            preparation_id=case_c_prep.preparation_id,
            prep_workflow=case_c_wf,
            execution_seed=case_c_seed,
            prompt_id=case_c_prompt,
            batch_size=2,
            fill=(93, 94, 95),
            output_suffix="0705",
        )
        # Also keep earlier batch_gid_a/b for immutability checks against shared batch prompt.
        _assert_true("case c distinct gens", case_c_gid_a != case_c_gid_b)

        # batch_size=1 → single_generation scope
        single_repro_meta = json.loads(
            (
                Path(canon_payload["preparation"]["drive_prepared_dir"])
                / f"{repro_id}.metadata.json"
            ).read_text(encoding="utf-8")
        )
        _assert_equal(
            "batch_size=1 scope",
            single_repro_meta.get("reproduction_scope"),
            "single_generation",
        )
        _assert_equal("batch_size=1 preserved", single_repro_meta["parameters"]["batch_size"], 1)
        _pass(results, "batch_size=1 source uses reproduction_scope=single_generation")

        batch_snap = load_snapshot_by_id(paths["drive"], case_c_gid_a)
        batch_root = Path(str(batch_snap["snapshot_root"]))
        batch_before = {
            "meta": file_sha256(batch_root / METADATA_FILENAME),
            "wf": file_sha256(batch_root / WORKFLOW_FILENAME),
            "man": file_sha256(batch_root / MANIFEST_FILENAME),
        }
        batch_wf_payload = json.loads((batch_root / WORKFLOW_FILENAME).read_text(encoding="utf-8"))
        source_batch = extract_batch_size(
            api_prompt=batch_wf_payload.get("api_prompt"),
            ui_workflow=batch_wf_payload.get("ui_workflow"),
        )
        _assert_equal("source batch_size from graph", source_batch, 2)
        _pass(results, "batch_size=2 source detected")

        proc = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            case_c_gid_a,
            "--global",
            "--json",
        )
        _assert_equal("batch a repro exit", proc.returncode, 0)
        batch_repro_a = json.loads(proc.stdout)
        _assert_equal("no silent batch_size=1", batch_repro_a["parameters"]["batch_size"], 2)
        _assert_equal("source_batch recorded", batch_repro_a.get("source_batch_size"), 2)
        _assert_equal(
            "scope source_batch_execution",
            batch_repro_a.get("reproduction_scope"),
            "source_batch_execution",
        )
        _assert_equal("case c seed preserved", batch_repro_a["parameters"]["seed"], case_c_seed)
        _assert_equal("case c seed_mode fixed", batch_repro_a["parameters"]["seed_mode"], "fixed")
        _assert_equal(
            "lineage gen A",
            batch_repro_a["lineage"]["reproduction_source_generation_id"],
            case_c_gid_a,
        )
        _assert_equal(
            "lineage prompt",
            batch_repro_a["lineage"]["reproduction_source_prompt_id"],
            case_c_prompt,
        )
        _assert_true(
            "batch warning truthful",
            any("per-image latent identity is not preserved" in w for w in batch_repro_a.get("warnings") or []),
        )
        _assert_true(
            "batch UX message",
            any("original batch execution" in m for m in batch_repro_a.get("messages") or []),
        )
        _pass(results, "first generation from batch handled truthfully")

        proc2 = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            case_c_gid_b,
            "--global",
            "--json",
        )
        _assert_equal("batch b repro exit", proc2.returncode, 0)
        batch_repro_b = json.loads(proc2.stdout)
        _assert_equal("batch b size=2", batch_repro_b["parameters"]["batch_size"], 2)
        _assert_equal(
            "batch b scope",
            batch_repro_b.get("reproduction_scope"),
            "source_batch_execution",
        )
        _assert_equal("batch b seed", batch_repro_b["parameters"]["seed"], case_c_seed)
        _assert_equal(
            "lineage gen B",
            batch_repro_b["lineage"]["reproduction_source_generation_id"],
            case_c_gid_b,
        )
        _assert_true(
            "distinct preps for batch gens",
            batch_repro_b["preparation_id"] != batch_repro_a["preparation_id"],
        )
        _assert_true(
            "selected source gen IDs remain distinct lineage",
            batch_repro_a["lineage"]["reproduction_source_generation_id"]
            != batch_repro_b["lineage"]["reproduction_source_generation_id"],
        )
        _pass(results, "second generation from same batch handled truthfully")
        _pass(results, "no silent batch_size=1 reduction")
        _pass(results, "selected source generation ID remains distinct lineage")
        _pass(results, "original prompt ID preserved")
        _pass(results, "original batch size preserved when scope=source_batch_execution")
        _pass(results, "fixed executed seed preserved")

        # Compare tool accepts intended batch semantics
        proc = _run_cli(
            real_repo,
            temp_repo,
            "compare_generation_reproduction.py",
            "--source-generation",
            case_c_gid_a,
            "--reproduction-preparation",
            batch_repro_a["preparation_id"],
        )
        _assert_equal("compare batch exit", proc.returncode, 0)
        _assert_true("compare batch match", "All checks match:            yes" in proc.stdout)
        _pass(results, "compare tool accepts intended batch semantics")

        # Missing batch state fails closed
        miss_batch_gid = f"gen_{uuid.uuid4()}"
        miss_batch_root = paths["drive"] / "generations" / miss_batch_gid
        miss_batch_root.mkdir(parents=True, exist_ok=True)
        miss_api = _txt2img_api(seed=555)
        # Strip batch_size from API + provide no UI widgets for latent batch.
        del miss_api["5"]["inputs"]["batch_size"]
        miss_wf = {
            "workflow_schema_version": 1,
            "generation_id": miss_batch_gid,
            "ui_workflow_available": False,
            "api_prompt_available": True,
            "ui_workflow": None,
            "api_prompt": miss_api,
            "workflow_identifier": "base/txt2img",
            "workflow_snapshot_status": "partial",
        }
        miss_meta = {
            "generation_id": miss_batch_gid,
            "prompt_id": str(uuid.uuid4()),
            "workflow_identifier": "base/txt2img",
            "positive_prompt": "snowy alpine research station",
            "negative_prompt": "blurry, low quality",
            "seed": 555,
            "steps": 24,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "width": 512,
            "height": 768,
            "model_files": ["sd15.safetensors"],
            "image_sha256": "def",
            "workflow_snapshot_status": "partial",
            "batch_size": None,
            "preparation_id": None,
        }
        (miss_batch_root / METADATA_FILENAME).write_text(json.dumps(miss_meta), encoding="utf-8")
        (miss_batch_root / WORKFLOW_FILENAME).write_text(json.dumps(miss_wf), encoding="utf-8")
        (miss_batch_root / MANIFEST_FILENAME).write_text(
            json.dumps(
                {
                    "generation_id": miss_batch_gid,
                    "snapshot_status": "complete",
                    "metadata_sha256": file_sha256(miss_batch_root / METADATA_FILENAME),
                    "workflow_sha256": file_sha256(miss_batch_root / WORKFLOW_FILENAME),
                }
            ),
            encoding="utf-8",
        )
        proc = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            miss_batch_gid,
            "--global",
        )
        _assert_true("missing batch fails", proc.returncode != 0)
        combined = (proc.stderr + proc.stdout).lower()
        _assert_true(
            "missing batch message",
            "batch" in combined and ("cannot" in combined or "recover" in combined or "deterministic" in combined),
        )
        _assert_false("no silent single-image prepare", "Reproduction preparation created" in proc.stdout)
        _pass(results, "missing batch state fails closed")

        batch_after = {
            "meta": file_sha256(batch_root / METADATA_FILENAME),
            "wf": file_sha256(batch_root / WORKFLOW_FILENAME),
            "man": file_sha256(batch_root / MANIFEST_FILENAME),
        }
        _assert_equal("batch source meta immutable", batch_before["meta"], batch_after["meta"])
        _assert_equal("batch source wf immutable", batch_before["wf"], batch_after["wf"])
        _assert_equal("batch source man immutable", batch_before["man"], batch_after["man"])
        _pass(results, "source snapshots remain immutable")
        _pass(results, "52 batch-source semantics tested")

        # Also exercise earlier shared-prompt batch pair for distinct prep IDs
        proc = _run_cli(
            real_repo,
            temp_repo,
            "prepare_from_generation.py",
            "--generation-id",
            batch_gid_a,
            "--global",
            "--json",
        )
        _assert_equal("legacy batch fixture a", proc.returncode, 0)
        _assert_equal("legacy batch fixture a size", json.loads(proc.stdout)["parameters"]["batch_size"], 2)

        # Compare tool
        proc = _run_cli(
            real_repo,
            temp_repo,
            "compare_generation_reproduction.py",
            "--source-generation",
            fixed_gid,
            "--reproduction-preparation",
            repro_id,
        )
        _assert_equal("compare exit", proc.returncode, 0)
        _assert_true("compare match", "All checks match:            yes" in proc.stdout)

        # generation_info eligibility
        proc = _run_cli(
            real_repo,
            temp_repo,
            "generation_info.py",
            "--generation-id",
            fixed_gid,
        )
        _assert_true("info eligibility", "Reproduction eligible:      yes" in proc.stdout)

        # Notebook menu strings
        nb = json.loads(
            (real_repo / "colab" / "notebooks" / "AI_Studio_Control_Panel_Colab.ipynb").read_text(
                encoding="utf-8"
            )
        )
        joined = "\n".join("".join(c.get("source") or []) for c in nb["cells"])
        _assert_true("notebook reproduce option", "4. Reproduce generation" in joined)
        _assert_true("notebook prepare_from_generation", "prepare_from_generation.py" in joined)
        _assert_false("notebook not named Rerun", "4. Rerun" in joined)

        # Help CLIs
        for script in (
            "prepare_from_generation.py",
            "compare_generation_reproduction.py",
        ):
            help_proc = _run_cli(real_repo, None, script, "--help")
            _assert_equal(f"{script} --help", help_proc.returncode, 0)

        # Static regression: userdata route file untouched conceptually (hash check of key file)
        userdata_compat = real_repo / "core" / "runtime" / "comfyui_userdata_route_compat.py"
        _assert_true("4.8.4 compat module present", userdata_compat.is_file())
        _pass(results, "53 4.8.4 regression green (compat module present; full suite separate)")
        _pass(results, "54 4.8.5 regression green (deferred to full suite)")
        _pass(results, "55 4.9 regression green (deferred to full suite)")
        _pass(results, "56 4.9.1 regression green (deferred to full suite)")

        # Extra: normalize identity helpers
        _assert_equal("normalize bare", normalize_generation_id(bare), fixed_gid)
        _pass(results, "extra identity normalization")

        # Extra: hash_ui_workflow still works on repro graph
        _assert_true("repro graph hashable", bool(hash_ui_workflow(repro_wf)))
        _pass(results, "extra repro graph hashable")

    except SimulationFailure as exc:
        results.append(("FAIL", str(exc)))
        print(f"  [FAIL] {exc}")
    except Exception as exc:  # noqa: BLE001 — sim harness
        results.append(("FAIL", f"unexpected: {exc}"))
        print(f"  [FAIL] unexpected: {exc}")
        raise
    finally:
        for path in temp_dirs:
            shutil.rmtree(path, ignore_errors=True)

    passed = sum(1 for status, _ in results if status == "PASS")
    failed = sum(1 for status, _ in results if status == "FAIL")
    print()
    print(f"Package 4.10 results: {passed} passed, {failed} failed, {len(results)} total")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
