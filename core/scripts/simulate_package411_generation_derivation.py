#!/usr/bin/env python3
"""Package 4.11 — generation derivation / image variation simulations."""

from __future__ import annotations

import hashlib
import json
import os
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

from core.runtime.generation_derivation import (
    DERIVATION_SOURCE_FILENAME,
    DERIVATION_SOURCE_RELATIVE_PATH,
    DERIVATION_SOURCE_SUBDIR,
    DERIVATION_TYPE_IMAGE_VARIATION,
    PREPARATION_KIND_GENERATION_DERIVATION,
    assess_derivation_eligibility,
    compare_generation_to_derivation,
    prepare_variation_from_generation,
    resolve_derivation_archived_source,
    restage_derivation_inputs_for_open,
    should_prompt_open_derivation_preparation,
)
from core.runtime.generation_evidence_ledger import EvidenceRecord, file_sha256
from core.runtime.generation_identity import format_generation_not_found, normalize_generation_id
from core.runtime.generation_reproduction import prepare_from_generation
from core.runtime.generation_snapshot import (
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    WORKFLOW_FILENAME,
    create_generation_snapshot,
    load_snapshot_by_id,
)
from core.runtime.png_utils import write_rgb_png
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.seed_mode import SEED_MODE_FIXED, SEED_MODE_RANDOMIZE
from core.runtime.workflow_library_preparation import prepare_library_workflow
from core.runtime.workflow_manifest import load_workflow_manifest
from core.runtime.workflow_provenance import ExecutionProvenance, extract_ai_studio_extra, extract_execution_provenance
from core.runtime.registry_loader import find_repo_root


MODEL_FILES_PRESENT = {"sd15.safetensors": True}


class SimulationFailure(Exception):
    pass


def _pass(results: list[tuple[str, str]], name: str) -> None:
    results.append(("PASS", name))
    print(f"  [PASS] {name}")


def _assert_true(label: str, condition: bool) -> None:
    if not condition:
        raise SimulationFailure(label)


def _assert_false(label: str, condition: bool) -> None:
    if condition:
        raise SimulationFailure(label)


def _assert_equal(label: str, left, right) -> None:
    if left != right:
        raise SimulationFailure(f"{label}: {left!r} != {right!r}")


def _write_png(path: Path, fill: tuple[int, int, int] = (10, 20, 30)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [[fill for _ in range(8)] for _ in range(8)]
    write_rgb_png(path, 8, 8, rows)


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


def _comfy_object_info(manifest: dict) -> dict[str, dict]:
    return {str(node): {} for node in (manifest.get("required_nodes") or [])}


def _notebook_source(repo_root: Path) -> str:
    nb = json.loads(
        (repo_root / "colab" / "notebooks" / "AI_Studio_Control_Panel_Colab.ipynb").read_text(
            encoding="utf-8"
        )
    )
    chunks: list[str] = []
    for cell in nb.get("cells") or []:
        src = cell.get("source") or []
        if isinstance(src, list):
            chunks.append("".join(src))
        else:
            chunks.append(str(src))
    return "\n".join(chunks)


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
        checkpoint.write_bytes(b"PK411-SIM-MODEL-STUB")
    return {
        "drive": drive,
        "runtime_prepared": runtime / "prepared_workflows",
        "drive_prepared": drive / "workflows" / "prepared",
        "comfy_input": comfy_input,
        "comfy_root": root / "ComfyUI",
        "runtime": runtime,
    }


def _make_temp_repo(real_repo: Path, drive_root: Path, comfy_root: Path, runtime_root: Path) -> Path:
    temp_repo = Path(tempfile.mkdtemp(prefix="ai-studio-pkg411-"))
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


def _txt2img_api(*, seed: int, batch_size: int = 1, positive: str = "mountain cabin") -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd15.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 768, "batch_size": batch_size}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 30,
                "cfg": 8.0,
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
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "sim411", "images": ["8", 0]}},
    }


def _create_source_generation(
    *,
    repo_root: Path,
    paths: dict[str, Path],
    seed: int,
    fill: tuple[int, int, int],
    batch_size: int = 1,
    suffix: str = "",
    prompt_id: str | None = None,
    active_project=None,
    capability: str = "txt2img",
    workflow_identifier: str = "base/txt2img",
    positive: str = "mountain cabin",
    steps: int = 30,
    cfg: float = 8.0,
) -> dict[str, str]:
    prep = prepare_library_workflow(
        repo_root,
        workflow_identifier="base/txt2img",
        parameters={
            "positive_prompt": positive,
            "negative_prompt": "blurry",
            "seed": seed,
            "seed_mode": "fixed",
            "steps": steps,
            "cfg": cfg,
            "sampler_name": "euler",
            "scheduler": "normal",
            "width": 512,
            "height": 768,
            "batch_size": batch_size,
            "checkpoint": "sd15.safetensors",
        },
        runtime_prepared_root=paths["runtime_prepared"],
        drive_prepared_root=paths["drive_prepared"],
        comfyui_input_dir=paths["comfy_input"],
        drive_root=paths["drive"],
        dry_run=False,
        allowed_input_roots=[paths["drive"] / "inputs"],
        comfy_object_info=_comfy_object_info(load_workflow_manifest(repo_root, "base/txt2img")),
        model_files_present=MODEL_FILES_PRESENT,
        active_project=active_project,
    )
    _assert_true("source prep ok", prep.ok)
    prep_workflow = json.loads(Path(prep.runtime_workflow_path).read_text(encoding="utf-8"))
    out_name = f"sim411_{seed}{suffix}.png"
    out_path = paths["drive"] / "outputs" / out_name
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
        capability=capability,
        model_family="sd15",
        model_files=["sd15.safetensors"],
        positive_prompt=positive,
        negative_prompt="blurry",
        seed=seed,
        steps=steps,
        cfg=cfg,
        sampler_name="euler",
        scheduler="normal",
        width=512,
        height=768,
        workflow_identifier=workflow_identifier,
        preparation_id=prep.preparation_id,
        project_id=active_project.project_id if active_project else "",
    )
    provenance = ExecutionProvenance(
        workflow_identifier=workflow_identifier,
        capability=capability,
        model_family="sd15",
        model_files=["sd15.safetensors"],
        positive_prompt=positive,
        negative_prompt="blurry",
        seed=seed,
        steps=steps,
        cfg=cfg,
        sampler_name="euler",
        scheduler="normal",
        width=512,
        height=768,
        preparation_id=prep.preparation_id,
        provenance_status="complete",
    )
    snap = create_generation_snapshot(
        drive_root=paths["drive"],
        record=record,
        dedupe_key=f"{prompt_id}:9:{out_name}",
        provenance=provenance,
        active_project=active_project,
        index_path=paths["drive"] / "logs" / "generation_index.jsonl",
        ui_workflow=prep_workflow,
        api_prompt=_txt2img_api(seed=seed, batch_size=batch_size, positive=positive),
        repo_root=repo_root,
    )
    _assert_true("snapshot ok", snap.ok)
    return {
        "generation_id": snap.generation_id,
        "preparation_id": prep.preparation_id,
        "snapshot_root": str(snap.snapshot_root),
        "png": str(out_path),
        "sha": sha,
        "prompt_id": prompt_id,
    }


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _rewrite_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _prepare_kwargs(temp_repo: Path, paths: dict[str, Path], object_info: dict) -> dict:
    return {
        "runtime_prepared_root": paths["runtime_prepared"],
        "drive_prepared_root": paths["drive_prepared"],
        "comfyui_input_dir": paths["comfy_input"],
        "drive_root": paths["drive"],
        "comfy_object_info": object_info,
        "model_files_present": MODEL_FILES_PRESENT,
    }


def main() -> int:
    real_repo = find_repo_root(script_file=Path(__file__))
    results: list[tuple[str, str]] = []
    temp_dirs: list[Path] = []

    print("Package 4.11 — Generation Derivation / Image Variation")
    print("=" * 40)

    try:
        root = Path(tempfile.mkdtemp(prefix="pkg411-root-"))
        temp_dirs.append(root)
        paths = _prep_paths(root)
        temp_repo = _make_temp_repo(real_repo, paths["drive"], paths["comfy_root"], paths["runtime"])
        temp_dirs.append(temp_repo)
        img2img_manifest = load_workflow_manifest(temp_repo, "base/img2img")
        object_info = _comfy_object_info(img2img_manifest)
        kw = _prepare_kwargs(temp_repo, paths, object_info)

        # --- Case A: modern complete source ---
        src_a = _create_source_generation(
            repo_root=temp_repo,
            paths=paths,
            seed=135791357,
            fill=(30, 40, 50),
            suffix="_a",
        )
        gid_a = src_a["generation_id"]
        snap_root_a = Path(src_a["snapshot_root"])
        source_prep_dir = paths["drive_prepared"] / src_a["preparation_id"]
        hashes_before = {
            "metadata": file_sha256(snap_root_a / METADATA_FILENAME),
            "workflow": file_sha256(snap_root_a / WORKFLOW_FILENAME),
            "manifest": file_sha256(snap_root_a / MANIFEST_FILENAME),
            "png": file_sha256(Path(src_a["png"])),
            "source_prep": _file_hashes(source_prep_dir),
        }

        var_a = prepare_variation_from_generation(
            temp_repo, generation_id=gid_a, **kw
        )
        _assert_true("case A prep ok", var_a.ok)
        _assert_equal("case A workflow", var_a.workflow_identifier, "base/img2img")
        _assert_equal("case A kind", var_a.preparation_kind, PREPARATION_KIND_GENERATION_DERIVATION)
        _assert_equal("case A type", var_a.derivation_type, DERIVATION_TYPE_IMAGE_VARIATION)
        _assert_equal("case A seed_mode", var_a.parameters.get("seed_mode"), SEED_MODE_RANDOMIZE)
        _assert_equal(
            "case A control_after_generate",
            var_a.parameters.get("control_after_generate"),
            "randomize",
        )
        _assert_equal("case A inherited prompt", var_a.parameters.get("positive_prompt"), "mountain cabin")
        _assert_equal("case A inherited negative", var_a.parameters.get("negative_prompt"), "blurry")
        _assert_equal("case A inherited steps", var_a.parameters.get("steps"), 30)
        _assert_equal("case A inherited cfg", float(var_a.parameters.get("cfg")), 8.0)
        _assert_equal("case A inherited sampler", var_a.parameters.get("sampler_name"), "euler")
        _assert_equal("case A inherited scheduler", var_a.parameters.get("scheduler"), "normal")
        _assert_equal("case A inherited checkpoint", var_a.parameters.get("checkpoint"), "sd15.safetensors")
        _assert_equal("case A denoise default", float(var_a.parameters.get("denoise")), 0.55)
        _assert_true("case A new seed", var_a.parameters.get("seed") != 135791357)
        _assert_true(
            "case A save prefix",
            str(var_a.parameters.get("save_prefix") or "").startswith("ai_studio_var_"),
        )
        drive_prep = Path(var_a.preparation.drive_prepared_dir if var_a.preparation else "")
        meta_a = _load_json(drive_prep / f"{var_a.preparation_id}.metadata.json")
        _assert_equal(
            "durable archive relative",
            meta_a.get("derivation_source_archived_path"),
            DERIVATION_SOURCE_RELATIVE_PATH,
        )
        _assert_false(
            "archive path not absolute runtime",
            Path(str(meta_a.get("derivation_source_archived_path") or "")).is_absolute(),
        )
        archive_a = resolve_derivation_archived_source(drive_prep, meta_a)
        _assert_true("case A archive exists", archive_a is not None and archive_a.is_file())
        _assert_equal("case A archive sha", file_sha256(archive_a), src_a["sha"])
        _assert_equal("case A parent lineage", meta_a.get("derived_from_generation_id"), gid_a)
        _pass(results, "Case A — complete source variation with inherited vs new defaults")

        compare_a = _run_cli(
            real_repo,
            temp_repo,
            "compare_generation_derivation.py",
            "--source-generation",
            gid_a,
            "--derivation-preparation",
            var_a.preparation_id,
        )
        _assert_equal("case A compare exit", compare_a.returncode, 0)
        _pass(results, "Case A — compare_generation_derivation matches correct source")

        # --- Case B: randomized historical source is not reproduction intent ---
        src_b = _create_source_generation(
            repo_root=temp_repo,
            paths=paths,
            seed=603180018352167,
            fill=(50, 60, 70),
            suffix="_rand",
        )
        var_b = prepare_variation_from_generation(
            temp_repo, generation_id=src_b["generation_id"], **kw
        )
        _assert_true("case B ok", var_b.ok)
        _assert_equal("case B seed_mode", var_b.parameters.get("seed_mode"), SEED_MODE_RANDOMIZE)
        _assert_true("case B seed not frozen as reproduction", var_b.parameters.get("seed_mode") != "fixed")
        _pass(results, "Case B — randomized source uses variation seed intent")

        # --- Case C: two batch siblings, select A only ---
        shared_prompt = str(uuid.uuid4())
        sib_a = _create_source_generation(
            repo_root=temp_repo,
            paths=paths,
            seed=864209753,
            fill=(80, 90, 100),
            batch_size=2,
            suffix="_sibA",
            prompt_id=shared_prompt,
        )
        sib_b = _create_source_generation(
            repo_root=temp_repo,
            paths=paths,
            seed=864209753,
            fill=(10, 200, 30),
            batch_size=2,
            suffix="_sibB",
            prompt_id=shared_prompt,
        )
        _assert_true("siblings different SHA", sib_a["sha"] != sib_b["sha"])
        _assert_equal("siblings share prompt", sib_a["prompt_id"], sib_b["prompt_id"])
        var_c = prepare_variation_from_generation(
            temp_repo, generation_id=sib_a["generation_id"], **kw
        )
        _assert_true("case C ok", var_c.ok)
        _assert_true("case C no batch_size", "batch_size" not in (var_c.parameters or {}))
        meta_c = _load_json(
            Path(var_c.preparation.drive_prepared_dir) / f"{var_c.preparation_id}.metadata.json"
        )
        arch_c = resolve_derivation_archived_source(
            Path(var_c.preparation.drive_prepared_dir), meta_c
        )
        _assert_equal("case C archive is sibling A", file_sha256(arch_c), sib_a["sha"])
        _assert_true("case C archive is not sibling B", file_sha256(arch_c) != sib_b["sha"])
        _assert_equal("case C no invented output index", meta_c.get("source_output_index"), None)
        _pass(results, "Case C — selected batch sibling only; no batch reconstruction")

        # --- Case D: realistic restart from Drive prep ---
        staged_name = str((meta_a.get("staged_inputs") or {}).get("input_image", {}).get("staged_filename") or "")
        _assert_true("case D staged filename recorded", bool(staged_name))
        runtime_copy = paths["runtime_prepared"] / var_a.preparation_id
        _assert_true("runtime copy existed", runtime_copy.is_dir())
        shutil.rmtree(runtime_copy, ignore_errors=True)
        _assert_false("runtime copy removed", runtime_copy.exists())
        for item in paths["comfy_input"].glob("*"):
            if item.is_file():
                item.unlink()
        msgs, errs = restage_derivation_inputs_for_open(
            prepared_dir=drive_prep,
            metadata=meta_a,
            comfyui_input_dir=paths["comfy_input"],
        )
        _assert_true("case D restage no errors", not errs)
        restaged = paths["comfy_input"] / staged_name
        _assert_true("case D restaged expected filename", restaged.is_file())
        _assert_equal("case D restage SHA", file_sha256(restaged), src_a["sha"])
        _assert_false("case D not using missing runtime copy", runtime_copy.exists())
        _pass(results, "Case D — Drive-only restart restage with relative archive")

        # --- Case E: source immutability after prep/archive/stage ---
        _assert_equal("E metadata", file_sha256(snap_root_a / METADATA_FILENAME), hashes_before["metadata"])
        _assert_equal("E workflow", file_sha256(snap_root_a / WORKFLOW_FILENAME), hashes_before["workflow"])
        _assert_equal("E manifest", file_sha256(snap_root_a / MANIFEST_FILENAME), hashes_before["manifest"])
        _assert_equal("E png", file_sha256(Path(src_a["png"])), hashes_before["png"])
        _assert_equal("E source prep", _file_hashes(source_prep_dir), hashes_before["source_prep"])
        _pass(results, "Case E — source snapshot, PNG, and original prep immutable")

        # --- Case F: fail closed unknown ID ---
        bad = prepare_variation_from_generation(
            temp_repo, generation_id="gen_00000000-0000-0000-0000-000000000099", **kw
        )
        _assert_false("F unknown fails", bad.ok)
        _assert_equal("F no prep id", bad.preparation_id, "")
        _assert_true("F not found", any("Generation not found" in e for e in bad.errors))
        _pass(results, "Case F — unknown generation fails closed")

        # --- Eligibility table ---
        elig_complete = assess_derivation_eligibility(
            metadata=_load_json(snap_root_a / METADATA_FILENAME),
            manifest=_load_json(snap_root_a / MANIFEST_FILENAME),
            workflow_payload=_load_json(snap_root_a / WORKFLOW_FILENAME),
        )
        _assert_true("complete eligible", elig_complete.eligible)
        _pass(results, "Eligibility A — modern complete generation accepted")

        src_partial = _create_source_generation(
            repo_root=temp_repo, paths=paths, seed=111, fill=(1, 2, 3), suffix="_partial_ok"
        )
        partial_root = Path(src_partial["snapshot_root"])
        wf_partial = _load_json(partial_root / WORKFLOW_FILENAME)
        wf_partial["workflow_snapshot_status"] = "partial"
        _rewrite_json(partial_root / WORKFLOW_FILENAME, wf_partial)
        meta_partial = _load_json(partial_root / METADATA_FILENAME)
        meta_partial["workflow_snapshot_status"] = "partial"
        _rewrite_json(partial_root / METADATA_FILENAME, meta_partial)
        elig_partial_ok = assess_derivation_eligibility(
            metadata=meta_partial,
            manifest=_load_json(partial_root / MANIFEST_FILENAME),
            workflow_payload=wf_partial,
        )
        _assert_true("partial recoverable eligible", elig_partial_ok.eligible)
        _pass(results, "Eligibility B — partial snapshot with recoverable state accepted")

        src_partial_bad = _create_source_generation(
            repo_root=temp_repo, paths=paths, seed=112, fill=(2, 3, 4), suffix="_partial_bad"
        )
        bad_root = Path(src_partial_bad["snapshot_root"])
        (bad_root / WORKFLOW_FILENAME).unlink()
        meta_bad = _load_json(bad_root / METADATA_FILENAME)
        for key in ("positive_prompt", "steps", "cfg", "sampler_name", "scheduler", "model_files"):
            meta_bad.pop(key, None)
        meta_bad["workflow_snapshot_status"] = "partial"
        _rewrite_json(bad_root / METADATA_FILENAME, meta_bad)
        refused_partial = prepare_variation_from_generation(
            temp_repo, generation_id=src_partial_bad["generation_id"], **kw
        )
        _assert_false("partial missing refused", refused_partial.ok)
        _assert_equal("partial missing no prep", refused_partial.preparation_id, "")
        _pass(results, "Eligibility C — partial missing inherited state refused")

        src_legacy = _create_source_generation(
            repo_root=temp_repo, paths=paths, seed=113, fill=(3, 4, 5), suffix="_legacy"
        )
        legacy_root = Path(src_legacy["snapshot_root"])
        (legacy_root / WORKFLOW_FILENAME).unlink(missing_ok=True)
        legacy_meta = {
            "generation_id": src_legacy["generation_id"],
            "canonical_output_path": src_legacy["png"],
            "image_sha256": src_legacy["sha"],
        }
        _rewrite_json(legacy_root / METADATA_FILENAME, legacy_meta)
        refused_legacy = prepare_variation_from_generation(
            temp_repo, generation_id=src_legacy["generation_id"], **kw
        )
        _assert_false("legacy refused", refused_legacy.ok)
        _pass(results, "Eligibility D — legacy PNG without creative state refused")

        src_nowf = _create_source_generation(
            repo_root=temp_repo, paths=paths, seed=114, fill=(4, 5, 6), suffix="_nowf"
        )
        nowf_root = Path(src_nowf["snapshot_root"])
        (nowf_root / WORKFLOW_FILENAME).unlink()
        meta_nowf = _load_json(nowf_root / METADATA_FILENAME)
        meta_nowf["workflow_snapshot_status"] = "unavailable"
        _rewrite_json(nowf_root / METADATA_FILENAME, meta_nowf)
        var_nowf = prepare_variation_from_generation(
            temp_repo, generation_id=src_nowf["generation_id"], **kw
        )
        _assert_true("missing workflow still eligible via metadata", var_nowf.ok)
        _pass(results, "Eligibility E — missing workflow snapshot allowed if metadata complete")

        src_nometa = _create_source_generation(
            repo_root=temp_repo, paths=paths, seed=115, fill=(5, 6, 7), suffix="_nometa"
        )
        (Path(src_nometa["snapshot_root"]) / METADATA_FILENAME).unlink()
        refused_nometa = prepare_variation_from_generation(
            temp_repo, generation_id=src_nometa["generation_id"], **kw
        )
        _assert_false("missing metadata refused", refused_nometa.ok)
        _pass(results, "Eligibility F — missing generation metadata refused")

        src_nopng = _create_source_generation(
            repo_root=temp_repo, paths=paths, seed=116, fill=(6, 7, 8), suffix="_nopng"
        )
        Path(src_nopng["png"]).unlink()
        refused_nopng = prepare_variation_from_generation(
            temp_repo, generation_id=src_nopng["generation_id"], **kw
        )
        _assert_false("missing png refused", refused_nopng.ok)
        _pass(results, "Eligibility G — missing source image refused")

        src_nosha = _create_source_generation(
            repo_root=temp_repo, paths=paths, seed=117, fill=(7, 8, 9), suffix="_nosha"
        )
        nosha_meta = _load_json(Path(src_nosha["snapshot_root"]) / METADATA_FILENAME)
        nosha_meta["image_sha256"] = None
        _rewrite_json(Path(src_nosha["snapshot_root"]) / METADATA_FILENAME, nosha_meta)
        nosha_manifest = _load_json(Path(src_nosha["snapshot_root"]) / MANIFEST_FILENAME)
        nosha_manifest["image_sha256"] = None
        _rewrite_json(Path(src_nosha["snapshot_root"]) / MANIFEST_FILENAME, nosha_manifest)
        refused_nosha = prepare_variation_from_generation(
            temp_repo, generation_id=src_nosha["generation_id"], **kw
        )
        _assert_false("missing sha refused", refused_nosha.ok)
        _pass(results, "Eligibility H — missing image SHA refused")

        src_badsha = _create_source_generation(
            repo_root=temp_repo, paths=paths, seed=118, fill=(8, 9, 10), suffix="_badsha"
        )
        badsha_meta = _load_json(Path(src_badsha["snapshot_root"]) / METADATA_FILENAME)
        badsha_meta["image_sha256"] = "0" * 64
        _rewrite_json(Path(src_badsha["snapshot_root"]) / METADATA_FILENAME, badsha_meta)
        refused_badsha = prepare_variation_from_generation(
            temp_repo, generation_id=src_badsha["generation_id"], **kw
        )
        _assert_false("sha mismatch refused", refused_badsha.ok)
        _pass(results, "Eligibility I — image SHA mismatch refused")

        src_img2img = _create_source_generation(
            repo_root=temp_repo,
            paths=paths,
            seed=119,
            fill=(9, 10, 11),
            suffix="_img2img",
            capability="img2img",
            workflow_identifier="base/img2img",
        )
        var_img = prepare_variation_from_generation(
            temp_repo, generation_id=src_img2img["generation_id"], **kw
        )
        _assert_true("img2img source eligible", var_img.ok)
        _pass(results, "Source capability — any verified image-producing generation eligible")

        # --- Checkpoint / node readiness ---
        missing_ckpt = prepare_variation_from_generation(
            temp_repo,
            generation_id=gid_a,
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            comfy_object_info=object_info,
            model_files_present={"sd15.safetensors": False},
        )
        _assert_false("missing checkpoint fails", missing_ckpt.ok)
        _assert_equal("missing checkpoint no prep", missing_ckpt.preparation_id, "")
        _pass(results, "Readiness — missing inherited checkpoint fails closed")

        missing_node = prepare_variation_from_generation(
            temp_repo,
            generation_id=gid_a,
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            comfy_object_info={},
            model_files_present=MODEL_FILES_PRESENT,
        )
        _assert_false("missing node fails", missing_node.ok)
        _assert_equal("missing node no prep", missing_node.preparation_id, "")
        _pass(results, "Readiness — missing required img2img node fails closed")

        # --- Parameter contract ---
        fixed_var = prepare_variation_from_generation(
            temp_repo,
            generation_id=gid_a,
            parameter_overrides={"seed_mode": "fixed", "seed": 4242},
            **kw,
        )
        _assert_true("fixed override ok", fixed_var.ok)
        _assert_equal("fixed seed_mode", fixed_var.parameters.get("seed_mode"), SEED_MODE_FIXED)
        _assert_equal("fixed control", fixed_var.parameters.get("control_after_generate"), "fixed")
        _assert_equal("fixed seed", int(fixed_var.parameters.get("seed")), 4242)
        _pass(results, "Parameters — fixed seed_mode override maps to native control_after_generate")

        locked = prepare_variation_from_generation(
            temp_repo,
            generation_id=gid_a,
            parameter_overrides={
                "save_prefix": "user_should_not_win",
                "input_image": str(Path(src_b["png"])),
            },
            **kw,
        )
        _assert_true("locked overrides ignored", locked.ok)
        _assert_true(
            "save_prefix locked",
            str(locked.parameters.get("save_prefix") or "").startswith("ai_studio_var_"),
        )
        locked_meta = _load_json(
            Path(locked.preparation.drive_prepared_dir) / f"{locked.preparation_id}.metadata.json"
        )
        locked_arch = resolve_derivation_archived_source(
            Path(locked.preparation.drive_prepared_dir), locked_meta
        )
        _assert_equal("input_image locked to A", file_sha256(locked_arch), src_a["sha"])
        _pass(results, "Parameters — save_prefix and input_image locked against override")

        def _reject(**overrides):
            result = prepare_variation_from_generation(
                temp_repo, generation_id=gid_a, parameter_overrides=overrides, **kw
            )
            _assert_false(f"reject {overrides}", result.ok)
            _assert_equal(f"reject {overrides} no prep", result.preparation_id, "")

        _reject(denoise=1.5)
        _reject(denoise=-0.1)
        _reject(steps=0)
        _reject(cfg=0.5)
        _reject(sampler_name="not_a_sampler")
        _reject(scheduler="not_a_scheduler")
        _reject(checkpoint="not-allowed.safetensors")
        _pass(results, "Parameters — denoise/steps/CFG/sampler/scheduler/checkpoint bounds enforced")

        # --- Project / global ---
        workspace = ProjectWorkspace(paths["drive"])
        project = workspace.create_project(display_name="Variation Demo", slug="variation-demo")
        src_proj = _create_source_generation(
            repo_root=temp_repo,
            paths=paths,
            seed=221,
            fill=(11, 12, 13),
            suffix="_proj",
            active_project=project,
        )
        var_proj = prepare_variation_from_generation(
            temp_repo, generation_id=src_proj["generation_id"], **kw
        )
        _assert_true("project default ok", var_proj.ok)
        _assert_true(
            "project mirror path",
            "variation-demo" in str(var_proj.preparation.project_prepared_dir or ""),
        )
        proj_archive = Path(var_proj.preparation.project_prepared_dir) / DERIVATION_SOURCE_SUBDIR / DERIVATION_SOURCE_FILENAME
        _assert_true("project mirror has archive", proj_archive.is_file())
        _assert_equal("project archive sha", file_sha256(proj_archive), src_proj["sha"])
        _pass(results, "Project A — source project inherited; mirror contains archived source")

        var_global_src = prepare_variation_from_generation(temp_repo, generation_id=gid_a, **kw)
        _assert_true("global source ok", var_global_src.ok)
        _assert_true(
            "global source stays global",
            not (var_global_src.preparation.project_prepared_dir or ""),
        )
        _pass(results, "Project B — global source yields global derivative")

        archived = workspace.create_project(display_name="Archived Demo", slug="archived-demo")
        src_arch = _create_source_generation(
            repo_root=temp_repo,
            paths=paths,
            seed=222,
            fill=(14, 15, 16),
            suffix="_arch",
            active_project=archived,
        )
        workspace.archive_project("archived-demo")
        var_arch = prepare_variation_from_generation(
            temp_repo, generation_id=src_arch["generation_id"], **kw
        )
        _assert_false("archived project refused", var_arch.ok)
        _pass(results, "Project C — archived source project fails closed")

        other = workspace.create_project(display_name="Other Demo", slug="other-demo")
        var_override = prepare_variation_from_generation(
            temp_repo,
            generation_id=gid_a,
            project_ref="other-demo",
            **kw,
        )
        _assert_true("explicit override ok", var_override.ok)
        _assert_true(
            "explicit override project",
            "other-demo" in str(var_override.preparation.project_prepared_dir or ""),
        )
        _pass(results, "Project D — explicit safe project override")
        del other

        # --- Notebook gating ---
        _assert_false(
            "lookup fail no open",
            should_prompt_open_derivation_preparation(lookup_ok=False, prepare_ok=False),
        )
        _assert_false(
            "prepare fail no open",
            should_prompt_open_derivation_preparation(lookup_ok=True, prepare_ok=False, preparation_id=""),
        )
        _assert_true(
            "success open allowed",
            should_prompt_open_derivation_preparation(
                lookup_ok=True,
                prepare_ok=True,
                preparation_id="prep_11111111-1111-1111-1111-111111111111",
            ),
        )
        joined = _notebook_source(real_repo)
        _assert_true("menu item 5", "Create variation from generation" in joined)
        _assert_true("derivation helper", "should_prompt_open_derivation_preparation" in joined)
        info_idx = joined.find("core/scripts/prepare_variation_from_generation.py")
        open_idx = joined.find("Open the new variation preparation in ComfyUI now?")
        _assert_true("open prompt after prepare", 0 <= info_idx < open_idx)
        lookup_src = (
            (real_repo / "core" / "runtime" / "generation_derivation.py").read_text(encoding="utf-8")
            + (real_repo / "core" / "scripts" / "prepare_variation_from_generation.py").read_text(
                encoding="utf-8"
            )
        )
        _assert_false("no fuzzy", "fuzzy" in lookup_src.lower())
        _assert_false("no difflib", "difflib" in lookup_src)
        malformed = _run_cli(
            real_repo, temp_repo, "prepare_variation_from_generation.py", "--generation-id", "not-a-uuid"
        )
        _assert_equal("malformed exit", malformed.returncode, 1)
        _assert_true("malformed no traceback", "Traceback" not in ((malformed.stdout or "") + (malformed.stderr or "")))
        _pass(results, "Notebook gating — fail-closed lookup/prepare; no fuzzy correction")

        # --- Child lineage synthetic path ---
        ui_child = _load_json(drive_prep / f"{var_a.preparation_id}.workflow.json")
        prov = extract_execution_provenance(
            {"outputs": {}, "prompt": {}},
            registered_hashes={},
            ui_workflow=ui_child,
            output_node_id="8",
        )
        _assert_equal("prov derived_from", prov.derived_from_generation_id, gid_a)
        _assert_equal("prov kind", prov.preparation_kind, PREPARATION_KIND_GENERATION_DERIVATION)
        _assert_equal("prov not reproduction", prov.reproduced_from_generation_id, "")
        child_png = paths["drive"] / "outputs" / "sim411_child.png"
        _write_png(child_png, fill=(90, 91, 92))
        child_sha = file_sha256(child_png)
        child_prompt = str(uuid.uuid4())
        child_record = EvidenceRecord(
            prompt_id=child_prompt,
            output_node_id="8",
            drive_path=str(child_png),
            drive_filename=child_png.name,
            drive_sha256=child_sha,
            local_sha256=child_sha,
            byte_size=child_png.stat().st_size,
            sync_status="verified",
            capability="img2img",
            workflow_identifier="base/img2img",
            preparation_id=var_a.preparation_id,
            preparation_kind=prov.preparation_kind,
            derived_from_generation_id=prov.derived_from_generation_id,
            reproduced_from_generation_id=prov.reproduced_from_generation_id,
        )
        child_snap = create_generation_snapshot(
            drive_root=paths["drive"],
            record=child_record,
            dedupe_key=f"{child_prompt}:8:{child_png.name}",
            provenance=prov,
            active_project=None,
            index_path=paths["drive"] / "logs" / "generation_index.jsonl",
            ui_workflow=ui_child,
            repo_root=temp_repo,
        )
        _assert_true("child snapshot ok", child_snap.ok)
        child_meta = _load_json(child_snap.snapshot_root / METADATA_FILENAME)
        _assert_equal("child derived_from", child_meta.get("derived_from_generation_id"), gid_a)
        _assert_equal("child kind", child_meta.get("preparation_kind"), PREPARATION_KIND_GENERATION_DERIVATION)
        _assert_true("child not reproduced_from", not child_meta.get("reproduced_from_generation_id"))
        _pass(results, "Child lineage — synthetic execution carries parent derivation only")

        compare_child = compare_generation_to_derivation(
            generation_metadata=_load_json(snap_root_a / METADATA_FILENAME),
            generation_manifest=_load_json(snap_root_a / MANIFEST_FILENAME),
            preparation_metadata=meta_a,
            child_generation_metadata=child_meta,
            prepared_dir=drive_prep,
            generation_workflow=_load_json(snap_root_a / WORKFLOW_FILENAME),
        )
        _assert_true("compare child lineage", compare_child.get("child_lineage_ok") is True)
        _pass(results, "Compare — child lineage when supplied")

        # --- Compare tool hardening ---
        wrong = compare_generation_to_derivation(
            generation_metadata=_load_json(Path(src_b["snapshot_root"]) / METADATA_FILENAME),
            generation_manifest=_load_json(Path(src_b["snapshot_root"]) / MANIFEST_FILENAME),
            preparation_metadata=meta_a,
            prepared_dir=drive_prep,
        )
        _assert_false("wrong source lineage", wrong.get("lineage_ok"))
        _pass(results, "Compare — wrong source generation fails lineage")

        corrupted = drive_prep / DERIVATION_SOURCE_SUBDIR / DERIVATION_SOURCE_FILENAME
        corrupted.write_bytes(b"not-the-source-png")
        corrupt_report = compare_generation_to_derivation(
            generation_metadata=_load_json(snap_root_a / METADATA_FILENAME),
            generation_manifest=_load_json(snap_root_a / MANIFEST_FILENAME),
            preparation_metadata=meta_a,
            prepared_dir=drive_prep,
        )
        _assert_false("corrupt archive fails", corrupt_report.get("all_match"))
        shutil.copy2(Path(src_a["png"]), corrupted)
        missing_arch_dir = Path(tempfile.mkdtemp(prefix="pkg411-empty-prep-"))
        temp_dirs.append(missing_arch_dir)
        missing_report = compare_generation_to_derivation(
            generation_metadata=_load_json(snap_root_a / METADATA_FILENAME),
            generation_manifest=_load_json(snap_root_a / MANIFEST_FILENAME),
            preparation_metadata=meta_a,
            prepared_dir=missing_arch_dir,
        )
        _assert_false("missing archive fails", missing_report.get("all_match"))
        _pass(results, "Compare — corrupted/missing archived source fails read-only")

        # --- Reproduction regression ---
        repro = prepare_from_generation(
            temp_repo,
            generation_id=gid_a,
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            allowed_input_roots=[paths["drive"] / "inputs"],
            comfy_object_info=_comfy_object_info(load_workflow_manifest(temp_repo, "base/txt2img")),
            model_files_present=MODEL_FILES_PRESENT,
        )
        _assert_true("reproduction still works", repro.ok)
        _assert_equal("reproduction seed_mode fixed", repro.parameters.get("seed_mode"), "fixed")
        _assert_equal("reproduction seed from source", repro.parameters.get("seed"), 135791357)
        _pass(results, "Regression — Package 4.10 reproduction semantics unchanged")

        for script in (
            "prepare_variation_from_generation.py",
            "compare_generation_derivation.py",
        ):
            help_result = _run_cli(real_repo, temp_repo, script, "--help")
            _assert_equal(f"{script} --help", help_result.returncode, 0)
        _pass(results, "CLI --help for new Package 4.11 tools")

        _assert_true("img2img seed_mode param", "seed_mode" in (img2img_manifest.get("parameter_schema") or {}))
        wf_a = _load_json(drive_prep / f"{var_a.preparation_id}.workflow.json")
        ai = extract_ai_studio_extra(wf_a) or {}
        _assert_equal("workflow derived_from", ai.get("derived_from_generation_id"), gid_a)
        _assert_equal(
            "workflow archive relative",
            str(ai.get("derivation_source_archived_path") or "").replace("\\", "/"),
            DERIVATION_SOURCE_RELATIVE_PATH,
        )
        _pass(results, "Prepared workflow embeds derivation lineage with relative archive")

        expected_not_found = format_generation_not_found("gen_00000000-0000-0000-0000-000000000099")
        _assert_true("not-found formatter", "Generation not found" in expected_not_found)
        _assert_true("normalize still works", normalize_generation_id(gid_a.removeprefix("gen_")) == gid_a)
        _pass(results, "Identity — exact fail-closed lookup; UUID normalize still works")

    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        results.append(("FAIL", str(exc)))
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] unexpected: {exc}")
        results.append(("FAIL", f"unexpected: {exc}"))
        raise
    finally:
        for temp in temp_dirs:
            shutil.rmtree(temp, ignore_errors=True)

    passed = sum(1 for status, _ in results if status == "PASS")
    failed = sum(1 for status, _ in results if status == "FAIL")
    print()
    print(f"Package 4.11 results: {passed} passed, {failed} failed, {len(results)} total")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
