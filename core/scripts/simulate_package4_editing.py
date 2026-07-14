#!/usr/bin/env python3
"""Focused simulations for Production Package 4 image editing foundation."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from unittest.mock import patch
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.capability_manager import CapabilityManager
from core.runtime import input_utils
from core.runtime import workflow_preparation
from core.runtime.diagnostic_fixtures import RED_SQUARE, create_fixture_bundle
from core.runtime.inpainting_reference_preparation import (
    CONTROLLED_GROW_MASK_BY,
    prepare_inpainting_reference,
    prompt_texts,
    resolve_reference_runtime_paths,
    sampler_widgets,
)
from core.runtime.inpainting_workflow_compare import (
    MASK_SOURCE_EMBEDDED_ALPHA,
    MASK_SOURCE_SEPARATE_LOAD_IMAGE_MASK,
    REFERENCE_INPAINTING_PATH,
    REFERENCE_PROVENANCE_PATH,
    compare_inpainting_workflows,
    load_reference_provenance,
)
from core.runtime.mask_diagnostics import analyze_mask
from core.runtime.registry_loader import RegistryBundle, RegistryLoader, find_repo_root
from core.runtime.workflow_preparation import prepare_workflow
from core.runtime.workflow_validation import (
    DIAG_INPAINTING_MASK_PREVIEW_WORKFLOW_ID,
    INPAINTING_CANONICAL_CHECKPOINT,
    INPAINTING_CANONICAL_DENOISE,
    INPAINTING_CANONICAL_MASK_CHANNEL,
    OUTPAINTING_CANONICAL_DENOISE,
    validate_base_img2img_workflow,
    validate_base_inpainting_workflow,
    validate_base_outpainting_workflow,
    validate_base_txt2img_workflow,
    validate_diag_inpainting_mask_preview_workflow,
    validate_workflow_from_data,
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


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _minimal_valid_png_bytes(width: int = 8, height: int = 8, rgb: tuple[int, int, int] = (0, 0, 0)) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(rgb) * width
    compressed = zlib.compress(row * height, 9)
    return signature + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", compressed) + _png_chunk(b"IEND", b"")


def _write_valid_png(
    path: Path,
    *,
    width: int = 8,
    height: int = 8,
    rgb: tuple[int, int, int] = (0, 0, 0),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image

        Image.new("RGB", (width, height), rgb).save(path, format="PNG")
    except ImportError:
        path.write_bytes(_minimal_valid_png_bytes(width, height, rgb))


def _write_png(path: Path, size: int = 128, fill: int = 0) -> None:
    side = max(1, int(size**0.5))
    rgb = (fill, fill, fill)
    _write_valid_png(path, width=side, height=side, rgb=rgb)


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


def _loadimagemask_channel(data: dict) -> str:
    for node in data.get("nodes", []):
        if node.get("type") == "LoadImageMask":
            widgets = node.get("widgets_values", [])
            if len(widgets) > 1:
                return widgets[1]
    return ""


def _checkpoint_filename(data: dict) -> str:
    for node in data.get("nodes", []):
        if node.get("type") == "CheckpointLoaderSimple":
            widgets = node.get("widgets_values", [])
            if widgets:
                return widgets[0]
    return ""


def _ksampler_denoise(data: dict) -> float | None:
    for node in data.get("nodes", []):
        if node.get("type") == "KSampler":
            widgets = node.get("widgets_values", [])
            if len(widgets) > 6:
                return widgets[6]
    return None


def _create_dogfood_bundle(
    tmp: Path,
    *,
    include_sd15: bool = True,
    include_inpainting_checkpoint: bool = True,
) -> RegistryBundle:
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
        if asset.get("id") == "sd15_inpainting_checkpoint" and include_inpainting_checkpoint:
            inpaint = tmp / "models" / "512-inpainting-ema.safetensors"
            inpaint.parent.mkdir(parents=True, exist_ok=True)
            inpaint.write_bytes(b"fake-inpainting-checkpoint")
            asset["runtime_path"] = str(inpaint)
        elif asset.get("id") == "sd15_inpainting_checkpoint" and not include_inpainting_checkpoint:
            asset["runtime_path"] = str(tmp / "models" / "missing-512-inpainting-ema.safetensors")
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

        inpaint_standard_ckpt = root / "inpaint_standard_ckpt.json"
        data = _load_workflow("workflows/base/inpainting/workflow.json")
        for node in data["nodes"]:
            if node.get("type") == "CheckpointLoaderSimple":
                node["widgets_values"][0] = "sd15.safetensors"
        inpaint_standard_ckpt.write_text(json.dumps(data), encoding="utf-8")
        validation = validate_base_inpainting_workflow(inpaint_standard_ckpt)
        _assert_equal("inpainting with sd15 checkpoint", validation.valid, False)
        results.append(("inpainting workflow uses sd15.safetensors", "PASS"))

        inpaint_dedicated_ckpt = root / "inpaint_dedicated_ckpt.json"
        data = _load_workflow("workflows/base/inpainting/workflow.json")
        for node in data["nodes"]:
            if node.get("type") == "CheckpointLoaderSimple":
                node["widgets_values"][0] = INPAINTING_CANONICAL_CHECKPOINT
        inpaint_dedicated_ckpt.write_text(json.dumps(data), encoding="utf-8")
        validation = validate_base_inpainting_workflow(inpaint_dedicated_ckpt)
        _assert_equal("inpainting with dedicated checkpoint", validation.valid, True)
        results.append(("inpainting workflow uses 512-inpainting-ema.safetensors", "PASS"))

        inpaint_alpha_channel = root / "inpaint_alpha_channel.json"
        data = _load_workflow("workflows/base/inpainting/workflow.json")
        for node in data["nodes"]:
            if node.get("type") == "LoadImageMask":
                node["widgets_values"][1] = "alpha"
        inpaint_alpha_channel.write_text(json.dumps(data), encoding="utf-8")
        validation = validate_base_inpainting_workflow(inpaint_alpha_channel)
        _assert_equal("inpainting with alpha mask channel", validation.valid, False)
        results.append(("inpainting workflow with alpha mask channel rejected", "PASS"))

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
        inpaint_ready = manager.evaluate_capability("inpainting")
        _assert_equal("inpainting ready with dedicated checkpoint", inpaint_ready.computed_status, "ready")
        results.append(("dedicated inpainting checkpoint present", "PASS"))

        txt2img = manager.evaluate_capability("txt2img")
        _assert_equal("txt2img ready with standard sd15", txt2img.computed_status, "ready")
        results.append(("txt2img remains READY with standard SD1.5", "PASS"))

        img2img = manager.evaluate_capability("img2img")
        _assert_equal("img2img ready with standard sd15", img2img.computed_status, "ready")
        results.append(("img2img remains READY with standard SD1.5", "PASS"))

        outpainting = manager.evaluate_capability("outpainting")
        _assert_equal("outpainting ready unchanged", outpainting.computed_status, "ready")
        results.append(("outpainting behavior does not regress", "PASS"))

    with tempfile.TemporaryDirectory() as tmp_name:
        bundle = _create_dogfood_bundle(
            Path(tmp_name),
            include_sd15=True,
            include_inpainting_checkpoint=False,
        )
        manager = CapabilityManager(bundle=bundle)
        inpaint = manager.evaluate_capability("inpainting")
        _assert_equal("inpainting partial without dedicated checkpoint", inpaint.computed_status, "partial")
        _assert_true(
            "inpainting missing dedicated reason",
            any("Dedicated SD1.5 inpainting checkpoint not found" in reason for reason in inpaint.reasons),
        )
        results.append(("dedicated checkpoint missing but standard SD1.5 present", "PASS"))

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
        _assert_equal(
            "inpaint prepared mask channel",
            _loadimagemask_channel(prepared_inpaint),
            INPAINTING_CANONICAL_MASK_CHANNEL,
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

        mask_payload = _minimal_valid_png_bytes(8, 8, (2, 2, 2))
        mask_other_payload = _minimal_valid_png_bytes(8, 8, (3, 3, 3))
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
        _write_valid_png(source_file, width=16, height=16, rgb=(0x11, 0x11, 0x11))
        _write_valid_png(mask_file, width=16, height=16, rgb=(0x22, 0x22, 0x22))
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
        identical_payload = _minimal_valid_png_bytes(8, 8, (0x33, 0x33, 0x33))
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


def run_mask_channel_regression_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    canonical = _load_workflow("workflows/base/inpainting/workflow.json")
    for node in canonical.get("nodes", []):
        if node.get("type") == "LoadImageMask":
            _assert_equal(
                "canonical inpainting mask channel",
                node.get("widgets_values", [None, None])[1],
                INPAINTING_CANONICAL_MASK_CHANNEL,
            )
    validation = validate_base_inpainting_workflow(_REPO_ROOT / "workflows/base/inpainting/workflow.json")
    _assert_equal("canonical inpainting workflow valid", validation.valid, True)
    results.append(("canonical inpainting workflow uses red mask channel", "PASS"))

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        bundle = _create_dogfood_bundle(tmp)
        repo = tmp / "repo"
        runtime_dir = bundle.path("runtime_workflows")
        comfy_input_dir = bundle.path("comfyui_runtime") / "input"
        source = tmp / "source.png"
        mask = tmp / "mask.png"
        _write_valid_png(source, width=16, height=16, rgb=(10, 20, 30))
        _write_valid_png(mask, width=16, height=16, rgb=(255, 255, 255))

        prepared = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="inpainting",
            input_path=source,
            mask_path=mask,
        )
        _assert_true("matching-dimension inpainting preparation ok", prepared.ok)
        prepared_data = json.loads(Path(prepared.prepared_path).read_text(encoding="utf-8"))
        mask_widgets = next(
            node.get("widgets_values", [])
            for node in prepared_data.get("nodes", [])
            if node.get("type") == "LoadImageMask"
        )
        _assert_equal(
            "prepared inpainting mask widgets",
            mask_widgets,
            [prepared.staged_mask_filename, INPAINTING_CANONICAL_MASK_CHANNEL, "white"],
        )
        _assert_equal(
            "prepared inpainting checkpoint",
            _checkpoint_filename(prepared_data),
            INPAINTING_CANONICAL_CHECKPOINT,
        )
        _assert_equal(
            "prepared inpainting denoise",
            _ksampler_denoise(prepared_data),
            INPAINTING_CANONICAL_DENOISE,
        )
        _assert_true(
            "prepared inpainting avoids alpha channel",
            "alpha" not in _loadimagemask_channel(prepared_data),
        )
        results.append(("prepared inpainting workflow preserves red mask channel", "PASS"))
        results.append(("prepared workflow must not contain alpha unless canonical used alpha", "PASS"))
        results.append(
            (
                "prepared inpainting workflow uses dedicated checkpoint, red channel, denoise 1.0, valid mask path",
                "PASS",
            )
        )
        results.append(("valid source and mask PNGs with matching dimensions", "PASS"))

        mismatched_mask = tmp / "mask_mismatch.png"
        _write_valid_png(mismatched_mask, width=32, height=16, rgb=(255, 255, 255))

        def _forced_dimension_mismatch(source_path: Path, mask_path: Path):
            return (
                False,
                "Source and mask dimensions differ: source=(16, 16), mask=(32, 16).",
                None,
            )

        with patch.object(workflow_preparation, "validate_matching_dimensions", _forced_dimension_mismatch):
            mismatch_result = prepare_workflow(
                repo,
                runtime_dir,
                comfyui_input_dir=comfy_input_dir,
                workflow="inpainting",
                input_path=source,
                mask_path=mismatched_mask,
            )
        _assert_equal("mismatched-dimension inpainting preparation ok flag", mismatch_result.ok, False)
        _assert_true(
            "mismatched-dimension error message",
            any("dimensions differ" in error for error in mismatch_result.errors),
        )
        results.append(("valid source and mask PNGs with different dimensions", "PASS"))

        forced_alpha = json.loads(Path(prepared.prepared_path).read_text(encoding="utf-8"))
        for node in forced_alpha.get("nodes", []):
            if node.get("type") == "LoadImageMask":
                node["widgets_values"][1] = "alpha"
        alpha_validation = validate_workflow_from_data("base_inpainting", forced_alpha)
        _assert_equal("forced alpha prepared workflow valid flag", alpha_validation.valid, False)
        results.append(("prepared workflow with forced alpha channel", "PASS"))

        def _deferred_dimension_check(source_path: Path, mask_path: Path):
            return True, None, "Pillow not available; source/mask dimension check deferred."

        with patch.object(workflow_preparation, "validate_matching_dimensions", _deferred_dimension_check):
            deferred_result = prepare_workflow(
                repo,
                runtime_dir,
                comfyui_input_dir=comfy_input_dir,
                workflow="inpainting",
                input_path=source,
                mask_path=mask,
            )
        _assert_true("inpainting preparation without pillow dimension check", deferred_result.ok)
        deferred_data = json.loads(Path(deferred_result.prepared_path).read_text(encoding="utf-8"))
        _assert_equal(
            "deferred-dimension prepared mask channel",
            _loadimagemask_channel(deferred_data),
            INPAINTING_CANONICAL_MASK_CHANNEL,
        )
        results.append(("simulations pass without Pillow available", "PASS"))

        try:
            from PIL import Image  # noqa: F401

            dims_ok, dims_error, _ = input_utils.validate_matching_dimensions(source, mismatched_mask)
            _assert_equal("pillow mismatch dimension check ok flag", dims_ok, False)
            _assert_true("pillow mismatch dimension error", bool(dims_error))
            results.append(("simulations pass with Pillow installed", "PASS"))
        except ImportError:
            results.append(("simulations pass with Pillow installed", "PASS (dimension check deferred locally)"))

    return results


def _write_mask_fixture(path: Path, *, fill: tuple[int, int, int], box: tuple[int, int, int, int] | None) -> None:
    from core.runtime.png_utils import write_rgb_png

    width = height = 64
    rows: list[list[tuple[int, int, int]]] = []
    for y in range(height):
        row: list[tuple[int, int, int]] = []
        for x in range(width):
            if box is not None and box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                row.append((255, 255, 255))
            else:
                row.append(fill)
        rows.append(row)
    write_rgb_png(path, width, height, rows)


def run_mask_diagnostics_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        partial = tmp / "partial.png"
        all_black = tmp / "all_black.png"
        all_white = tmp / "all_white.png"
        inverted = tmp / "inverted.png"
        red_channel = tmp / "red_channel.png"
        alpha_channel = tmp / "alpha_channel.png"
        tiny_brick = tmp / "tiny_brick.png"

        _write_mask_fixture(partial, fill=(0, 0, 0), box=(24, 24, 39, 39))
        _write_mask_fixture(all_black, fill=(0, 0, 0), box=None)
        _write_mask_fixture(all_white, fill=(255, 255, 255), box=None)
        inverted_rows = []
        for y in range(64):
            row = []
            for x in range(64):
                if 24 <= x <= 39 and 24 <= y <= 39:
                    row.append((0, 0, 0))
                else:
                    row.append((255, 255, 255))
            inverted_rows.append(row)
        from core.runtime.png_utils import write_rgb_png

        write_rgb_png(inverted, 64, 64, inverted_rows)

        red_rows = [[(0, 0, 0) for _ in range(64)] for _ in range(64)]
        for y in range(20, 30):
            for x in range(20, 30):
                red_rows[y][x] = (255, 0, 0)
        write_rgb_png(red_channel, 64, 64, red_rows)

        from core.runtime.png_utils import encode_rgba_png

        alpha_rows = [[(0, 0, 0, 255) for _ in range(64)] for _ in range(64)]
        for y in range(18, 28):
            for x in range(18, 28):
                # Transparent = ComfyUI inpaint region under LoadImage MASK semantics.
                alpha_rows[y][x] = (0, 0, 0, 0)
        alpha_channel.write_bytes(encode_rgba_png(64, 64, alpha_rows))

        tiny_rows = [[(0, 0, 0) for _ in range(128)] for _ in range(128)]
        for y in range(60, 68):
            for x in range(60, 68):
                tiny_rows[y][x] = (255, 255, 255)
        write_rgb_png(tiny_brick, 128, 128, tiny_rows)

        partial_report = analyze_mask(partial, channel="red")
        _assert_equal("partial mask classification", partial_report.classification, "partially_masked")
        _assert_true("partial mask has nonzero pixels", partial_report.nonzero_pixel_count > 0)
        results.append(("partial mask statistics", "PASS"))

        black_report = analyze_mask(all_black, channel="red")
        _assert_equal("all-black mask classification", black_report.classification, "all_black")
        results.append(("all-black mask", "PASS"))

        white_report = analyze_mask(all_white, channel="red")
        _assert_equal("all-white mask classification", white_report.classification, "all_white")
        results.append(("all-white mask", "PASS"))

        inverted_report = analyze_mask(inverted, channel="red", comparison_path=partial)
        _assert_equal("inverted mask detection", inverted_report.inverted_relative_to, "inverted")
        results.append(("inverted mask detection", "PASS"))

        _assert_equal("partial mask bounding box", partial_report.bounding_box, (24, 24, 39, 39))
        results.append(("bounding box accuracy", "PASS"))

        red_report = analyze_mask(red_channel, channel="red")
        _assert_true("red-channel extraction", red_report.nonzero_pixel_count == 100)
        results.append(("red-channel extraction", "PASS"))

        alpha_report = analyze_mask(alpha_channel, channel="alpha")
        _assert_true("alpha-channel extraction", alpha_report.nonzero_pixel_count == 100)
        _assert_equal("alpha channel bounding box", alpha_report.bounding_box, (18, 18, 27, 27))
        results.append(("alpha-channel extraction", "PASS"))

        tiny_report = analyze_mask(tiny_brick, channel="red")
        _assert_true("tiny brick partially masked", tiny_report.classification == "partially_masked")
        _assert_true("tiny brick percent small", tiny_report.masked_percent < 1.0)
        results.append(("tiny brick mask statistics", "PASS"))

        reference_data = _load_workflow("workflows/reference/inpainting_official/workflow.json")
        reference_types = [node.get("type") for node in reference_data.get("nodes", [])]
        _assert_equal("official reference LoadImage count", reference_types.count("LoadImage"), 1)
        load_image = next(node for node in reference_data["nodes"] if node.get("type") == "LoadImage")
        mask_links = None
        for output in load_image.get("outputs", []):
            if output.get("name") == "MASK":
                mask_links = output.get("links")
        _assert_true("official reference LoadImage MASK connected", bool(mask_links))
        results.append(("official reference has one LoadImage providing IMAGE and MASK", "PASS"))

        _assert_equal("official reference has no LoadImageMask", reference_types.count("LoadImageMask"), 0)
        results.append(("official reference has no LoadImageMask node", "PASS"))

        canonical_data = _load_workflow("workflows/base/inpainting/workflow.json")
        canonical_mask = next(
            node for node in canonical_data["nodes"] if node.get("type") == "LoadImageMask"
        )
        _assert_equal("canonical uses LoadImageMask red", canonical_mask.get("widgets_values", [None, None])[1], "red")
        results.append(("canonical workflow uses separate LoadImageMask red channel", "PASS"))

        comparison = compare_inpainting_workflows(
            _REPO_ROOT / "workflows/base/inpainting/workflow.json",
            _REPO_ROOT / "workflows/reference/inpainting_official/workflow.json",
        )
        _assert_equal("canonical/reference overall", comparison.overall, "materially_different")
        _assert_equal(
            "canonical mask source type",
            comparison.canonical_mask_architecture.get("mask_source_type"),
            MASK_SOURCE_SEPARATE_LOAD_IMAGE_MASK,
        )
        _assert_equal(
            "reference mask source type",
            comparison.reference_mask_architecture.get("mask_source_type"),
            MASK_SOURCE_EMBEDDED_ALPHA,
        )
        arch_diff = next(
            (item for item in comparison.differences if item.field == "mask_architecture"),
            None,
        )
        _assert_true("mask architecture difference reported", arch_diff is not None)
        results.append(("comparison reports mask architecture as materially different", "PASS"))

        material_data = json.loads(json.dumps(reference_data))
        for node in material_data["nodes"]:
            if node.get("type") == "CheckpointLoaderSimple":
                node["widgets_values"][0] = "sd15.safetensors"
        material_path = tmp / "material_reference.json"
        material_path.write_text(json.dumps(material_data), encoding="utf-8")
        material_comparison = compare_inpainting_workflows(
            _REPO_ROOT / "workflows/base/inpainting/workflow.json",
            material_path,
        )
        _assert_equal("material workflow difference overall", material_comparison.overall, "materially_different")
        results.append(("material workflow difference detection", "PASS"))

        preview_validation = validate_diag_inpainting_mask_preview_workflow(
            _REPO_ROOT / "workflows/diagnostics/inpainting_mask_preview/workflow.json"
        )
        _assert_equal("diagnostic mask preview workflow valid", preview_validation.valid, True)
        results.append(("diagnostic mask preview workflow validation", "PASS"))

        bundle = _create_dogfood_bundle(tmp)
        repo = tmp / "repo"
        runtime_dir = bundle.path("runtime_workflows")
        comfy_input_dir = bundle.path("comfyui_runtime") / "input"
        source = tmp / "inspect_source.png"
        mask = tmp / "inspect_mask.png"
        _write_valid_png(source, width=16, height=16, rgb=(10, 20, 30))
        _write_valid_png(mask, width=16, height=16, rgb=(255, 255, 255))
        inspect_result = prepare_workflow(
            repo,
            runtime_dir,
            comfyui_input_dir=comfy_input_dir,
            workflow="inpainting",
            input_path=source,
            mask_path=mask,
            diagnostics=True,
        )
        _assert_true("prepared workflow inspection ok", inspect_result.ok)
        _assert_true("prepared workflow inspection details", bool(inspect_result.diagnostic_details))
        _assert_equal(
            "prepared workflow inspection checkpoint",
            inspect_result.diagnostic_details.get("checkpoint"),
            INPAINTING_CANONICAL_CHECKPOINT,
        )
        results.append(("prepared workflow inspection", "PASS"))

        fixture_dir = tmp / "fixture_runtime"
        fixture_paths = create_fixture_bundle(fixture_dir)
        _assert_true("fixture source exists", Path(fixture_paths["source"]).is_file())
        _assert_true("fixture mask exists", Path(fixture_paths["mask"]).is_file())
        _assert_true("fixture rgba exists", Path(fixture_paths["source_rgba"]).is_file())
        fixture_mask = analyze_mask(Path(fixture_paths["mask"]), channel="red")
        _assert_equal("fixture mask dimensions", fixture_mask.dimensions, (512, 512))
        results.append(("diagnostic fixture generation", "PASS"))
        results.append(("diagnostic fixture mask dimensions", "PASS"))

        rgba_report = analyze_mask(Path(fixture_paths["source_rgba"]), channel="alpha")
        _assert_equal("RGBA fixture classification", rgba_report.classification, "partially_masked")
        _assert_equal("RGBA fixture alpha bounding box", rgba_report.bounding_box, RED_SQUARE["box"])
        results.append(("RGBA fixture contains a valid alpha mask", "PASS"))
        results.append(("alpha diagnostics identify the correct bounding box", "PASS"))

        ref_prep = prepare_inpainting_reference(
            _REPO_ROOT,
            runtime_dir,
            input_path=Path(fixture_paths["source_rgba"]),
            comfyui_input_dir=comfy_input_dir,
            match_canonical_sampler=True,
            positive_prompt="a bright yellow square",
            negative_prompt="blurry, low quality, distorted, seams, artifacts",
        )
        _assert_true("prepared official reference ok", ref_prep.ok)
        prepared_ref = json.loads(Path(ref_prep.prepared_path).read_text(encoding="utf-8"))
        staged_rgba = Path(ref_prep.staged_input_path)
        _assert_true("prepared official reference stages rgba", staged_rgba.is_file())
        _assert_equal(
            "prepared official reference preserves alpha bytes",
            staged_rgba.read_bytes(),
            Path(fixture_paths["source_rgba"]).read_bytes(),
        )
        _assert_equal("prepared reference grow_mask_by", ref_prep.grow_mask_by, CONTROLLED_GROW_MASK_BY)
        results.append(("prepared official reference preserves the embedded alpha mask", "PASS"))

        canonical_prepared = json.loads(Path(inspect_result.prepared_path).read_text(encoding="utf-8"))
        _assert_equal(
            "canonical and reference prepared samplers match",
            sampler_widgets(canonical_prepared),
            sampler_widgets(prepared_ref),
        )
        results.append(("canonical and reference prepared workflows use identical sampler parameters", "PASS"))

        provenance = load_reference_provenance(_REPO_ROOT)
        _assert_true("reference provenance present", bool(provenance))
        _assert_equal(
            "reference provenance extracted status",
            provenance.get("status"),
            "extracted_from_official_workflow_png",
        )
        _assert_true("reference provenance has source image sha", bool(provenance.get("source_image_sha256")))
        results.append(("reference provenance metadata is present", "PASS"))

        repo_canonical = _REPO_ROOT / "workflows/base/inpainting/workflow.json"
        repo_mtime_before = repo_canonical.stat().st_mtime
        _assert_true("fixture path outside repo", not str(fixture_dir).startswith(str(_REPO_ROOT)))
        _assert_equal("repo canonical unchanged mtime", repo_canonical.stat().st_mtime, repo_mtime_before)
        results.append(("no repo writes from fixture generation", "PASS"))

    return results


def run_reference_preparation_hardening_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    resolved = resolve_reference_runtime_paths(_REPO_ROOT)
    _assert_equal("colab default comfyui input", resolved.comfyui_input_dir, Path("/content/ComfyUI/input"))
    results.append(("Colab default ComfyUI input path resolves to /content/ComfyUI/input", "PASS"))
    _assert_equal(
        "colab default prepared workflows",
        resolved.runtime_dir,
        Path("/content/ai-studio-runtime/workflows"),
    )
    results.append(
        ("Colab default prepared workflow path resolves beneath /content/ai-studio-runtime/workflows", "PASS")
    )

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        override_runtime = tmp / "custom_runtime_workflows"
        override_input = tmp / "custom_comfy" / "input"
        overridden = resolve_reference_runtime_paths(
            _REPO_ROOT,
            runtime_dir=override_runtime,
            comfyui_input_dir=override_input,
        )
        _assert_equal("explicit runtime override", overridden.runtime_dir, override_runtime.resolve())
        _assert_equal("explicit input override", overridden.comfyui_input_dir, override_input.resolve())
        results.append(("explicit directory overrides still work", "PASS"))

        fixture_paths = create_fixture_bundle(tmp / "fixture")
        rgba = Path(fixture_paths["source_rgba"])
        extracted_prompts = prompt_texts(_load_workflow(REFERENCE_INPAINTING_PATH))
        _assert_true("extracted prompts readable", extracted_prompts is not None)

        prompt_prep = prepare_inpainting_reference(
            _REPO_ROOT,
            override_runtime,
            input_path=rgba,
            comfyui_input_dir=override_input,
            positive_prompt="a bright yellow square",
            negative_prompt="blurry, low quality, distorted, seams, artifacts",
            match_canonical_sampler=True,
            resolved_paths=overridden,
        )
        _assert_true("prompt override prep ok", prompt_prep.ok)
        _assert_equal("positive prompt override", prompt_prep.positive_prompt, "a bright yellow square")
        _assert_equal(
            "negative prompt override",
            prompt_prep.negative_prompt,
            "blurry, low quality, distorted, seams, artifacts",
        )
        results.append(("positive prompt override is applied", "PASS"))
        results.append(("negative prompt override is applied", "PASS"))

        preserve_prep = prepare_inpainting_reference(
            _REPO_ROOT,
            override_runtime,
            input_path=rgba,
            comfyui_input_dir=override_input,
        )
        _assert_true("omitted prompt flags ok", preserve_prep.ok)
        _assert_equal("preserved positive prompt", preserve_prep.positive_prompt, extracted_prompts[0])
        _assert_equal("preserved negative prompt", preserve_prep.negative_prompt, extracted_prompts[1])
        results.append(("omitted prompt flags preserve extracted prompts", "PASS"))

        broken = _load_workflow(REFERENCE_INPAINTING_PATH)
        clip_nodes = [node for node in broken["nodes"] if node.get("type") == "CLIPTextEncode"]
        non_clip = [node for node in broken["nodes"] if node.get("type") != "CLIPTextEncode"]
        broken["nodes"] = non_clip + clip_nodes[:1]
        broken_path = tmp / "broken_reference.json"
        broken_path.write_text(json.dumps(broken), encoding="utf-8")
        malformed = prepare_inpainting_reference(
            _REPO_ROOT,
            override_runtime,
            input_path=rgba,
            comfyui_input_dir=override_input,
            reference_workflow_path=broken_path,
        )
        _assert_true("malformed CLIP count rejected", not malformed.ok)
        results.append(("malformed CLIP node count is rejected", "PASS"))

        aligned = prepare_inpainting_reference(
            _REPO_ROOT,
            override_runtime,
            input_path=rgba,
            comfyui_input_dir=override_input,
            match_canonical_sampler=True,
        )
        _assert_true("match-canonical-sampler ok", aligned.ok)
        canonical = _load_workflow("workflows/base/inpainting/workflow.json")
        _assert_equal(
            "match-canonical-sampler widgets",
            sampler_widgets(json.loads(Path(aligned.prepared_path).read_text(encoding="utf-8"))),
            sampler_widgets(canonical),
        )
        results.append(("--match-canonical-sampler aligns seed and sampler parameters", "PASS"))

        prepared = json.loads(Path(aligned.prepared_path).read_text(encoding="utf-8"))
        _assert_true(
            "prepared retains embedded-alpha topology",
            any(
                node.get("type") == "LoadImage"
                and any(out.get("name") == "MASK" and out.get("links") for out in node.get("outputs", []))
                for node in prepared["nodes"]
            ),
        )
        _assert_equal(
            "prepared has no LoadImageMask",
            sum(1 for node in prepared["nodes"] if node.get("type") == "LoadImageMask"),
            0,
        )
        results.append(("prepared reference retains embedded-alpha mask topology", "PASS"))

        import hashlib

        workflow_path = _REPO_ROOT / REFERENCE_INPAINTING_PATH
        provenance = load_reference_provenance(_REPO_ROOT)
        current_sha = hashlib.sha256(workflow_path.read_bytes()).hexdigest()
        _assert_equal(
            "extracted reference workflow hash unchanged",
            current_sha,
            provenance.get("extracted_workflow_json_sha256"),
        )
        _assert_equal(
            "provenance source image hash present",
            bool(provenance.get("source_image_sha256")),
            True,
        )
        results.append(("extracted reference workflow and provenance hashes remain unchanged", "PASS"))

        _assert_true(
            "default prepared path under configured runtime",
            str(Path("/content/ai-studio-runtime/workflows")) in str(resolved.runtime_dir)
            or resolved.runtime_dir == Path("/content/ai-studio-runtime/workflows"),
        )

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
        ("Mask Channel Regression", run_mask_channel_regression_simulations),
        ("Mask Diagnostics", run_mask_diagnostics_simulations),
        ("Reference Preparation Hardening", run_reference_preparation_hardening_simulations),
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
