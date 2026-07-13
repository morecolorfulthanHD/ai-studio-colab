#!/usr/bin/env python3
"""Focused simulations for Production Package 4 image editing foundation."""

from __future__ import annotations

import json
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

from core.runtime.capability_manager import CapabilityManager
from core.runtime.registry_loader import RegistryBundle, RegistryLoader, find_repo_root
from core.runtime.workflow_preparation import prepare_workflow
from core.runtime.workflow_validation import (
    INPAINTING_CANONICAL_DENOISE,
    OUTPAINTING_CANONICAL_DENOISE,
    validate_base_img2img_workflow,
    validate_base_inpainting_workflow,
    validate_base_outpainting_workflow,
    validate_base_txt2img_workflow,
)

_REPO_ROOT = find_repo_root(script_file=Path(__file__))


class SimulationFailure(Exception):
    pass


def _assert_equal(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise SimulationFailure(f"{label}: expected {expected!r}, got {actual!r}")


def _assert_true(label: str, value: bool) -> None:
    if not value:
        raise SimulationFailure(f"{label}: expected True, got False")


def _write_png(path: Path, size: int = 128, fill: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + (bytes([fill]) * max(size - 8, 0)))


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _load_workflow(rel_path: str) -> dict:
    workflow_path = _REPO_ROOT / rel_path
    with workflow_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_workflow(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _loadimage_filename(data: dict) -> str:
    for node in data.get("nodes", []):
        if node.get("type") == "LoadImage":
            return node.get("widgets_values", [""])[0]
    return ""


def _loadimagemask_filename(data: dict) -> str:
    for node in data.get("nodes", []):
        if node.get("type") == "LoadImageMask":
            return node.get("widgets_values", [""])[0]
    return ""


def _create_dogfood_bundle(tmp: Path, *, include_sd15: bool = True) -> RegistryBundle:
    repo = tmp / "repo"
    shutil.copytree(_REPO_ROOT / "configs", repo / "configs")
    shutil.copytree(_REPO_ROOT / "workflows", repo / "workflows")

    comfy = tmp / "ComfyUI"
    comfy.mkdir(parents=True)
    (comfy / ".git").mkdir()
    (comfy / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (comfy / "output").mkdir()
    (comfy / "input").mkdir()

    drive_outputs = tmp / "drive_outputs"
    drive_outputs.mkdir(parents=True)
    drive_inputs = tmp / "drive_inputs"
    (drive_inputs / "images").mkdir(parents=True)
    (drive_inputs / "masks").mkdir(parents=True)
    runtime_workflows = tmp / "runtime_workflows"
    runtime_workflows.mkdir(parents=True)

    paths_file = repo / "configs/paths/colab_paths.json"
    paths_data = json.loads(paths_file.read_text(encoding="utf-8"))
    paths_data["paths"]["comfyui_runtime"] = str(comfy)
    paths_data["paths"]["comfyui_output"] = str(comfy / "output")
    paths_data["paths"]["drive_outputs"] = str(drive_outputs)
    paths_data["paths"]["drive_inputs"] = str(drive_inputs)
    paths_data["paths"]["runtime_workflows"] = str(runtime_workflows)
    paths_file.write_text(json.dumps(paths_data, indent=2), encoding="utf-8")

    assets_file = repo / "configs/assets/asset_registry.json"
    assets_data = json.loads(assets_file.read_text(encoding="utf-8"))
    for asset in assets_data.get("assets", []):
        if asset.get("id") == "sd15_checkpoint" and include_sd15:
            sd15 = tmp / "models" / "sd15.safetensors"
            sd15.parent.mkdir(parents=True, exist_ok=True)
            sd15.write_bytes(b"fake-checkpoint")
            asset["runtime_path"] = str(sd15)
        elif asset.get("id") == "sd15_checkpoint" and not include_sd15:
            asset["runtime_path"] = str(tmp / "models" / "missing_sd15.safetensors")
    assets_file.write_text(json.dumps(assets_data, indent=2), encoding="utf-8")

    return RegistryLoader(repo).load_all()


def run_workflow_validation_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        valid_img2img = root / "img2img_valid.json"
        valid_img2img.write_text(json.dumps(_load_workflow("workflows/base/img2img/workflow.json")), encoding="utf-8")
        validation = validate_base_img2img_workflow(valid_img2img)
        _assert_equal("valid img2img workflow", validation.valid, True)
        results.append(("valid img2img workflow", "PASS"))

        missing_vae = root / "img2img_missing_vae.json"
        data = _load_workflow("workflows/base/img2img/workflow.json")
        data["nodes"] = [node for node in data["nodes"] if node.get("type") != "VAEEncode"]
        missing_vae.write_text(json.dumps(data), encoding="utf-8")
        validation = validate_base_img2img_workflow(missing_vae)
        _assert_equal("img2img missing VAEEncode", validation.valid, False)
        results.append(("img2img workflow missing VAEEncode", "PASS"))

        valid_inpaint = root / "inpaint_valid.json"
        valid_inpaint.write_text(json.dumps(_load_workflow("workflows/base/inpainting/workflow.json")), encoding="utf-8")
        validation = validate_base_inpainting_workflow(valid_inpaint)
        _assert_equal("valid inpainting workflow", validation.valid, True)
        results.append(("valid inpainting workflow", "PASS"))

        missing_mask = root / "inpaint_missing_mask.json"
        data = _load_workflow("workflows/base/inpainting/workflow.json")
        data["nodes"] = [node for node in data["nodes"] if node.get("type") != "LoadImageMask"]
        missing_mask.write_text(json.dumps(data), encoding="utf-8")
        validation = validate_base_inpainting_workflow(missing_mask)
        _assert_equal("inpainting missing mask path", validation.valid, False)
        results.append(("inpainting workflow missing mask path", "PASS"))

        valid_outpaint = root / "outpaint_valid.json"
        valid_outpaint.write_text(json.dumps(_load_workflow("workflows/base/outpainting/workflow.json")), encoding="utf-8")
        validation = validate_base_outpainting_workflow(valid_outpaint)
        _assert_equal("valid outpainting workflow", validation.valid, True)
        results.append(("valid outpainting workflow", "PASS"))

        missing_pad = root / "outpaint_missing_pad.json"
        data = _load_workflow("workflows/base/outpainting/workflow.json")
        data["nodes"] = [node for node in data["nodes"] if node.get("type") != "ImagePadForOutpaint"]
        missing_pad.write_text(json.dumps(data), encoding="utf-8")
        validation = validate_base_outpainting_workflow(missing_pad)
        _assert_equal("outpainting missing canvas expansion", validation.valid, False)
        results.append(("outpainting workflow missing canvas expansion node/path", "PASS"))

    return results


def run_connectivity_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        disconnected_load = root / "img2img_disconnected_load.json"
        data = _load_workflow("workflows/base/img2img/workflow.json")
        data["links"] = [link for link in data["links"] if link[0] != 1]
        for node in data["nodes"]:
            if node.get("type") == "LoadImage":
                node["outputs"][0]["links"] = None
        _write_workflow(disconnected_load, data)
        validation = validate_base_img2img_workflow(disconnected_load)
        _assert_equal("disconnected LoadImage", validation.valid, False)
        results.append(("img2img graph with all nodes but disconnected LoadImage", "PASS"))

        missing_vae_link = root / "img2img_missing_vae_link.json"
        data = _load_workflow("workflows/base/img2img/workflow.json")
        data["links"] = [link for link in data["links"] if link[0] != 5]
        _write_workflow(missing_vae_link, data)
        validation = validate_base_img2img_workflow(missing_vae_link)
        _assert_equal("missing VAE-to-encode link", validation.valid, False)
        results.append(("img2img missing VAE-to-encode link", "PASS"))

        missing_decode_link = root / "img2img_missing_decode_link.json"
        data = _load_workflow("workflows/base/img2img/workflow.json")
        data["links"] = [link for link in data["links"] if link[0] != 10]
        _write_workflow(missing_decode_link, data)
        validation = validate_base_img2img_workflow(missing_decode_link)
        _assert_equal("missing sampler-to-decode link", validation.valid, False)
        results.append(("img2img missing sampler-to-decode link", "PASS"))

        mask_disconnected = root / "inpaint_mask_disconnected.json"
        data = _load_workflow("workflows/base/inpainting/workflow.json")
        data["links"] = [link for link in data["links"] if link[0] != 2]
        _write_workflow(mask_disconnected, data)
        validation = validate_base_inpainting_workflow(mask_disconnected)
        _assert_equal("inpainting mask disconnected", validation.valid, False)
        results.append(("inpainting mask node present but disconnected", "PASS"))

        mask_wrong_socket = root / "inpaint_mask_wrong_socket.json"
        data = _load_workflow("workflows/base/inpainting/workflow.json")
        data["links"] = [
            [2, 2, 0, 6, 0, "MASK"] if link[0] == 2 else link
            for link in data["links"]
        ]
        _write_workflow(mask_wrong_socket, data)
        validation = validate_base_inpainting_workflow(mask_wrong_socket)
        _assert_equal("inpainting mask wrong socket", validation.valid, False)
        results.append(("inpainting mask connected to wrong destination socket", "PASS"))

        pad_disconnected = root / "outpaint_pad_disconnected.json"
        data = _load_workflow("workflows/base/outpainting/workflow.json")
        data["links"] = [link for link in data["links"] if link[0] != 1]
        _write_workflow(pad_disconnected, data)
        validation = validate_base_outpainting_workflow(pad_disconnected)
        _assert_equal("outpainting pad disconnected", validation.valid, False)
        results.append(("outpainting pad node present but disconnected", "PASS"))

        mask_path_missing = root / "outpaint_mask_path_missing.json"
        data = _load_workflow("workflows/base/outpainting/workflow.json")
        data["links"] = [link for link in data["links"] if link[0] != 3]
        _write_workflow(mask_path_missing, data)
        validation = validate_base_outpainting_workflow(mask_path_missing)
        _assert_equal("outpainting mask path missing", validation.valid, False)
        results.append(("outpainting image path connected but mask path missing", "PASS"))

        malformed_link = root / "malformed_link.json"
        data = _load_workflow("workflows/base/img2img/workflow.json")
        data["links"].append([99, 1, 0, 999, 0, "IMAGE"])
        _write_workflow(malformed_link, data)
        validation = validate_base_img2img_workflow(malformed_link)
        _assert_equal("malformed link unknown node", validation.valid, False)
        results.append(("malformed link references unknown node", "PASS"))

        duplicate_ids = root / "duplicate_ids.json"
        data = _load_workflow("workflows/base/img2img/workflow.json")
        data["nodes"][-1]["id"] = data["nodes"][0]["id"]
        _write_workflow(duplicate_ids, data)
        validation = validate_base_img2img_workflow(duplicate_ids)
        _assert_equal("duplicate node ids", validation.valid, False)
        results.append(("duplicate node IDs", "PASS"))

        canonical_inpaint = _load_workflow("workflows/base/inpainting/workflow.json")
        sampler = next(node for node in canonical_inpaint["nodes"] if node.get("type") == "KSampler")
        _assert_equal("inpainting canonical denoise", sampler["widgets_values"][6], INPAINTING_CANONICAL_DENOISE)
        results.append(("inpainting canonical denoise = 1.0", "PASS"))

        canonical_outpaint = _load_workflow("workflows/base/outpainting/workflow.json")
        outpaint_sampler = next(
            node for node in canonical_outpaint["nodes"] if node.get("type") == "KSampler"
        )
        _assert_equal(
            "outpainting canonical denoise",
            outpaint_sampler["widgets_values"][6],
            OUTPAINTING_CANONICAL_DENOISE,
        )
        results.append(("canonical outpainting denoise = 1.0", "PASS"))

        wrong_outpaint_denoise = root / "outpaint_wrong_denoise.json"
        data = _load_workflow("workflows/base/outpainting/workflow.json")
        for node in data["nodes"]:
            if node.get("type") == "KSampler":
                node["widgets_values"][6] = 0.55
        _write_workflow(wrong_outpaint_denoise, data)
        validation = validate_base_outpainting_workflow(wrong_outpaint_denoise)
        _assert_equal("outpainting wrong denoise", validation.valid, False)
        results.append(("outpainting workflow changed to denoise 0.55", "PASS"))

        canonical_img2img = _load_workflow("workflows/base/img2img/workflow.json")
        _assert_equal("canonical img2img last_link_id", canonical_img2img.get("last_link_id"), 11)
        validation = validate_base_img2img_workflow(_REPO_ROOT / "workflows/base/img2img/workflow.json")
        _assert_equal("canonical img2img valid", validation.valid, True)
        results.append(("correct canonical img2img workflow last_link_id = 11", "PASS"))

        low_last_link = root / "img2img_low_last_link.json"
        data = _load_workflow("workflows/base/img2img/workflow.json")
        data["last_link_id"] = 10
        _write_workflow(low_last_link, data)
        validation = validate_base_img2img_workflow(low_last_link)
        _assert_equal("img2img last_link_id below max", validation.valid, False)
        results.append(("img2img last_link_id below maximum link ID", "PASS"))

        duplicate_link_ids = root / "duplicate_link_ids.json"
        data = _load_workflow("workflows/base/img2img/workflow.json")
        data["links"].append(list(data["links"][0]))
        _write_workflow(duplicate_link_ids, data)
        validation = validate_base_img2img_workflow(duplicate_link_ids)
        _assert_equal("duplicate global link ids", validation.valid, False)
        results.append(("duplicate global link IDs", "PASS"))

        input_wrong_socket = root / "input_wrong_socket.json"
        data = _load_workflow("workflows/base/img2img/workflow.json")
        for link in data["links"]:
            if link[0] == 1:
                link[4] = 1
        _write_workflow(input_wrong_socket, data)
        validation = validate_base_img2img_workflow(input_wrong_socket)
        _assert_equal("input wrong socket", validation.valid, False)
        results.append(("node input references a link that targets another socket", "PASS"))

        output_wrong_source = root / "output_wrong_source.json"
        data = _load_workflow("workflows/base/img2img/workflow.json")
        for link in data["links"]:
            if link[0] == 11:
                link[1] = 99
        _write_workflow(output_wrong_source, data)
        validation = validate_base_img2img_workflow(output_wrong_source)
        _assert_equal("output wrong source", validation.valid, False)
        results.append(("node output references a link sourced from another node or socket", "PASS"))

    return results


def run_capability_readiness_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp_name:
        bundle = _create_dogfood_bundle(Path(tmp_name))
        manager = CapabilityManager(bundle=bundle)

        for cap_id in ("img2img", "inpainting", "outpainting"):
            evaluation = manager.evaluate_capability(cap_id)
            _assert_equal(f"{cap_id} implemented with runtime deps", evaluation.computed_status, "ready")
            results.append((f"{cap_id} implemented with runtime dependencies present", "PASS"))

    with tempfile.TemporaryDirectory() as tmp_name:
        bundle = _create_dogfood_bundle(Path(tmp_name), include_sd15=False)
        manager = CapabilityManager(bundle=bundle)
        for cap_id in ("img2img", "inpainting", "outpainting"):
            evaluation = manager.evaluate_capability(cap_id)
            _assert_true(f"{cap_id} not ready without sd15", evaluation.computed_status != "ready")
        results.append(("missing SD1.5 makes all three editing capabilities not READY", "PASS"))

    with tempfile.TemporaryDirectory() as tmp_name:
        bundle = _create_dogfood_bundle(Path(tmp_name))
        manager = CapabilityManager(bundle=bundle)
        img2img = manager.evaluate_capability("img2img")
        _assert_equal("installed img2img readiness without input", img2img.computed_status, "ready")
        _assert_equal("execution input not selected", img2img.execution_input_status, "not_selected")
        results.append(("no input image selected keeps capability READY with input not selected", "PASS"))

    return results


def run_preparation_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        bundle = _create_dogfood_bundle(tmp)
        repo = tmp / "repo"
        runtime_dir = bundle.path("runtime_workflows")
        comfy_input_dir = bundle.path("comfyui_runtime") / "input"
        input_image = tmp / "source.png"
        _write_png(input_image, 80)

        invalid_input = tmp / "source.txt"
        invalid_input.write_text("not an image", encoding="utf-8")
        invalid_result = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="img2img",
            input_path=invalid_input,
        )
        _assert_equal("invalid extension preparation ok flag", invalid_result.ok, False)
        results.append(("invalid input extension", "PASS"))

        mask_image = tmp / "mask.png"
        _write_png(mask_image, 80)
        missing_mask = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="inpainting",
            input_path=input_image,
            mask_path=None,
        )
        _assert_equal("missing mask preparation ok flag", missing_mask.ok, False)
        results.append(("missing mask for inpainting", "PASS"))

        outpaint_result = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="outpainting",
            input_path=input_image,
            expansion={"left": 256, "right": 256, "top": 0, "bottom": 0},
        )
        _assert_equal("valid outpainting expansion ok flag", outpaint_result.ok, True)
        _assert_true("valid outpainting prepared path set", bool(outpaint_result.prepared_path))
        results.append(("valid outpainting expansion values", "PASS"))

        negative_result = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="outpainting",
            input_path=input_image,
            expansion={"left": -10, "right": 0, "top": 0, "bottom": 0},
        )
        _assert_equal("negative expansion ok flag", negative_result.ok, False)
        results.append(("negative expansion values", "PASS"))

        zero_expansion = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="outpainting",
            input_path=input_image,
            expansion={"left": 0, "right": 0, "top": 0, "bottom": 0},
        )
        _assert_equal("all-zero expansion ok flag", zero_expansion.ok, False)
        results.append(("outpainting all-zero expansion", "PASS"))

        canonical = repo / "workflows/base/img2img/workflow.json"
        canonical_bytes = canonical.read_bytes()
        prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="img2img",
            input_path=input_image,
        )
        _assert_equal("canonical workflow unchanged", canonical.read_bytes(), canonical_bytes)
        results.append(("canonical workflow remains unchanged after preparation", "PASS"))

        staged_result = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="img2img",
            input_path=input_image,
        )
        _assert_true("staged input path set", bool(staged_result.staged_input_path))
        staged_file = Path(staged_result.staged_input_path)
        _assert_true("staged input copied", staged_file.is_file())
        prepared_data = json.loads(Path(staged_result.prepared_path).read_text(encoding="utf-8"))
        _assert_equal(
            "prepared workflow references staged filename",
            _loadimage_filename(prepared_data),
            staged_result.staged_input_filename,
        )
        results.append(("selected image staged into ComfyUI/input", "PASS"))

        inpaint_result = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="inpainting",
            input_path=input_image,
            mask_path=mask_image,
        )
        prepared_inpaint = json.loads(Path(inpaint_result.prepared_path).read_text(encoding="utf-8"))
        _assert_equal(
            "inpaint prepared source filename",
            _loadimage_filename(prepared_inpaint),
            inpaint_result.staged_input_filename,
        )
        _assert_equal(
            "inpaint prepared mask filename",
            _loadimagemask_filename(prepared_inpaint),
            inpaint_result.staged_mask_filename,
        )
        results.append(("source and mask both staged", "PASS"))

        collision_source = tmp / "collision.png"
        _write_png(collision_source, 96)
        _write_png(comfy_input_dir / "collision.png", 64)
        collision_result = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="img2img",
            input_path=collision_source,
        )
        _assert_true("collision staged filename differs", "__" in collision_result.staged_input_filename)
        _assert_true("collision staged file exists", Path(collision_result.staged_input_path).is_file())
        results.append(("existing staged file with same name but different size", "PASS"))

        identical_payload = b"\x89PNG\r\n\x1a\n" + (b"\x00" * 104)
        reuse_source = tmp / "reuse.png"
        _write_bytes(reuse_source, identical_payload)
        _write_bytes(comfy_input_dir / "reuse.png", identical_payload)
        reuse_result = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="img2img",
            input_path=reuse_source,
        )
        _assert_equal("reuse staged filename", reuse_result.staged_input_filename, "reuse.png")
        _assert_equal("reuse staged path", reuse_result.staged_input_path, str(comfy_input_dir / "reuse.png"))
        _assert_true("reuse message present", any("identical" in message.lower() for message in reuse_result.messages))
        results.append(("existing staged file with same name, same size, same content", "PASS"))

        hash_source = tmp / "hash_collision.png"
        _write_bytes(hash_source, identical_payload)
        _write_bytes(comfy_input_dir / "hash_collision.png", b"\x89PNG\r\n\x1a\n" + (b"\x01" * 104))
        hash_result = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="img2img",
            input_path=hash_source,
        )
        _assert_true("hash collision staged filename differs", "__" in hash_result.staged_input_filename)
        _assert_true(
            "hash collision message present",
            any("different content" in message.lower() for message in hash_result.messages),
        )
        results.append(("existing staged file with same name and same size but different content", "PASS"))

        mask_payload = b"\x89PNG\r\n\x1a\n" + (b"\x02" * 80)
        mask_other_payload = b"\x89PNG\r\n\x1a\n" + (b"\x03" * 80)
        mask_source = tmp / "mask_reuse.png"
        _write_bytes(mask_source, mask_payload)
        _write_bytes(comfy_input_dir / "mask_reuse.png", mask_other_payload)
        mask_collision_result = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="inpainting",
            input_path=input_image,
            mask_path=mask_source,
        )
        _assert_true(
            "mask collision-safe filename",
            "__" in mask_collision_result.staged_mask_filename,
        )
        _assert_true(
            "source still staged for inpainting",
            Path(mask_collision_result.staged_input_path).is_file(),
        )
        results.append(("source image and mask both use content-based reuse rules", "PASS"))

        dry_input = tmp / "dry.png"
        _write_png(dry_input, 72)
        missing_input_dir = tmp / "missing_comfy" / "input"
        missing_runtime_dir = tmp / "missing_runtime"
        _assert_true("missing input dir absent", not missing_input_dir.exists())
        _assert_true("missing runtime dir absent", not missing_runtime_dir.exists())
        dry_result = prepare_workflow(
            repo,
            missing_runtime_dir,
            comfyui_input_dir=missing_input_dir,
            workflow="img2img",
            input_path=dry_input,
            dry_run=True,
        )
        _assert_equal("dry-run ok flag", dry_result.ok, True)
        _assert_true("dry-run staged path planned", bool(dry_result.staged_input_path))
        _assert_true("dry-run input dir still absent", not missing_input_dir.exists())
        _assert_true("dry-run runtime dir still absent", not missing_runtime_dir.exists())
        _assert_true("dry-run parent comfy dir still absent", not missing_input_dir.parent.exists())
        results.append(("dry-run with nonexistent ComfyUI input and runtime workflow directories", "PASS"))

        before_inputs = set(comfy_input_dir.iterdir())
        before_prepared = set(runtime_dir.glob("*.json"))
        dry_existing_result = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="img2img",
            input_path=dry_input,
            dry_run=True,
        )
        _assert_equal("dry-run existing dirs ok flag", dry_existing_result.ok, True)
        after_inputs = set(comfy_input_dir.iterdir())
        after_prepared = set(runtime_dir.glob("*.json"))
        _assert_equal("dry-run no input copies", after_inputs, before_inputs)
        _assert_equal("dry-run no prepared workflow", after_prepared, before_prepared)
        results.append(("--dry-run", "PASS"))

        fixed_ts = "20260712T120000Z"
        batch_root = tmp / "batch_staging"
        batch_root.mkdir()
        source_dir = batch_root / "sources"
        mask_dir = batch_root / "masks"
        source_dir.mkdir()
        mask_dir.mkdir()
        shared_name = "shared.png"
        source_file = source_dir / shared_name
        mask_file = mask_dir / shared_name
        _write_bytes(source_file, b"\x89PNG\r\n\x1a\n" + (b"\x11" * 80))
        _write_bytes(mask_file, b"\x89PNG\r\n\x1a\n" + (b"\x22" * 80))
        absent_input_dir = batch_root / "absent_comfy" / "input"
        absent_runtime_dir = batch_root / "absent_runtime"
        _assert_true("batch absent input dir missing", not absent_input_dir.exists())
        dry_batch = prepare_workflow(
            repo,
            absent_runtime_dir,
            comfyui_input_dir=absent_input_dir,
            workflow="inpainting",
            input_path=source_file,
            mask_path=mask_file,
            dry_run=True,
            operation_timestamp=fixed_ts,
        )
        _assert_equal("dry batch ok", dry_batch.ok, True)
        _assert_true(
            "dry batch distinct staged filenames",
            dry_batch.staged_input_filename != dry_batch.staged_mask_filename,
        )
        _assert_true("dry batch input dir still absent", not absent_input_dir.exists())
        _assert_true("dry batch runtime dir still absent", not absent_runtime_dir.exists())

        exec_input_dir = batch_root / "exec_comfy" / "input"
        exec_runtime_dir = batch_root / "exec_runtime"
        exec_batch = prepare_workflow(
            repo,
            exec_runtime_dir,
            comfyui_input_dir=exec_input_dir,
            workflow="inpainting",
            input_path=source_file,
            mask_path=mask_file,
            dry_run=False,
            operation_timestamp=fixed_ts,
        )
        _assert_equal("exec batch ok", exec_batch.ok, True)
        _assert_equal("exec matches dry source filename", exec_batch.staged_input_filename, dry_batch.staged_input_filename)
        _assert_equal("exec matches dry mask filename", exec_batch.staged_mask_filename, dry_batch.staged_mask_filename)
        staged_source = Path(exec_batch.staged_input_path)
        staged_mask = Path(exec_batch.staged_mask_path)
        _assert_equal("staged source bytes", staged_source.read_bytes(), source_file.read_bytes())
        _assert_equal("staged mask bytes", staged_mask.read_bytes(), mask_file.read_bytes())
        results.append(("dry-run and execute share identical staged filenames", "PASS"))
        results.append(("dry-run inpainting same basename different content absent destination", "PASS"))

        identical_root = tmp / "identical_batch"
        identical_root.mkdir()
        identical_source = identical_root / "same.png"
        identical_mask = identical_root / "masks" / "same.png"
        identical_mask.parent.mkdir()
        identical_payload = b"\x89PNG\r\n\x1a\n" + (b"\x33" * 72)
        _write_bytes(identical_source, identical_payload)
        _write_bytes(identical_mask, identical_payload)
        identical_input_dir = identical_root / "comfy" / "input"
        identical_result = prepare_workflow(
            repo,
            identical_root / "runtime",
            comfyui_input_dir=identical_input_dir,
            workflow="inpainting",
            input_path=identical_source,
            mask_path=identical_mask,
            operation_timestamp=fixed_ts,
        )
        _assert_equal("identical basename shared filename", identical_result.staged_input_filename, "same.png")
        _assert_equal(
            "identical basename shared staged path",
            identical_result.staged_mask_path,
            identical_result.staged_input_path,
        )
        prepared_identical = json.loads(Path(identical_result.prepared_path).read_text(encoding="utf-8"))
        _assert_equal(
            "identical basename workflow references",
            _loadimage_filename(prepared_identical),
            _loadimagemask_filename(prepared_identical),
        )
        results.append(("same source/mask basename with identical content", "PASS"))

    return results


def run_txt2img_regression_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    validation = validate_base_txt2img_workflow(_REPO_ROOT / "workflows/base/txt2img/workflow.json")
    _assert_equal("txt2img workflow still valid", validation.valid, True)
    results.append(("existing txt2img workflow validation", "PASS"))

    script = _REPO_ROOT / "core/scripts/simulate_package3_hardening.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SimulationFailure(
            "package 3 hardening simulations failed during package 4 regression check\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    results.append(("existing Package 3 and txt2img simulations continue to pass", "PASS"))

    return results


def main() -> int:
    sections = [
        ("Workflow Validation", run_workflow_validation_simulations),
        ("Graph Connectivity", run_connectivity_simulations),
        ("Capability Readiness", run_capability_readiness_simulations),
        ("Workflow Preparation", run_preparation_simulations),
        ("txt2img Regression", run_txt2img_regression_simulations),
    ]

    print("AI Studio — Package 4 Image Editing Simulations")
    print("=" * 50)

    total = 0
    failed = 0
    for section_name, runner in sections:
        print(f"\n{section_name}")
        try:
            section_results = runner()
            for name, status in section_results:
                total += 1
                print(f"  [{status}] {name}")
        except SimulationFailure as exc:
            failed += 1
            total += 1
            print(f"  [FAIL] {exc}")

    print()
    print(f"Summary: {total - failed}/{total} simulations passed")
    if failed:
        print("\nRESULT: FAIL — package 4 editing simulations failed.")
        return 1

    print("\nRESULT: OK — package 4 editing simulations passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
