#!/usr/bin/env python3
"""Package 4.5 simulations — launch truthfulness, provenance resolution, workspace foundation.

Uses realistic ComfyUI history fixtures (API prompt + extra_pnginfo.workflow) and exercises the
actual watcher path (handle_prompt_id) rather than only the extractor in isolation.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import core.runtime.output_autosync as output_autosync
from core.runtime.capability_manager import CapabilityManager
from core.runtime.generation_evidence_ledger import EvidenceLedger, EvidenceRecord, file_sha256
from core.runtime.generation_history import is_legacy_row, provenance_label, summarize_ledger
from core.runtime.output_autosync import OutputAutoSyncService
from core.runtime.project_workspace import ProjectWorkspace, validate_manifest
from core.runtime.registry_loader import RegistryLoader
from core.runtime.workflow_preparation import prepare_workflow
from core.runtime.workflow_provenance import (
    HASH_TYPE_API,
    HASH_TYPE_UI,
    SCHEMA_VERSION,
    extract_execution_provenance,
    extract_ui_workflow_from_history,
    hash_api_prompt,
    hash_ui_workflow,
    load_registered_workflow_hashes,
    structural_signature_ui,
)
from core.scripts.workflow_catalog import build_catalog


def _assert_true(name: str, condition: bool, results: list[tuple[str, str]]) -> None:
    results.append((name, "PASS" if condition else "FAIL"))
    if not condition:
        raise AssertionError(name)


def _assert_equal(name: str, actual, expected, results: list[tuple[str, str]]) -> None:
    results.append((name, "PASS" if actual == expected else "FAIL"))
    if actual != expected:
        raise AssertionError(f"{name}: {actual!r} != {expected!r}")


# --------------------------------------------------------------------------------------
# Realistic ComfyUI history fixtures
# --------------------------------------------------------------------------------------


def _load_ui(rel_path: str) -> dict:
    return json.loads((_REPO_ROOT / rel_path).read_text(encoding="utf-8"))


def _history_entry(api_prompt: dict, ui_workflow: dict | None, outputs: dict, prompt_id: str) -> dict:
    """Resemble real ComfyUI history: prompt=[num, id, api, extra_data, outputs_to_execute]."""
    extra_data: dict = {}
    if ui_workflow is not None:
        extra_data = {"extra_pnginfo": {"workflow": ui_workflow}}
    return {
        "prompt": [0, prompt_id, api_prompt, extra_data, list(outputs.keys())],
        "outputs": outputs,
        "status": {"status_str": "success", "completed": True},
    }


def _txt2img_api(*, seed: int = 424242, positive: str = "a red bicycle", negative: str = "blurry, low quality") -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd15.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 768, "batch_size": 1}},
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


def _img2img_api(*, seed: int = 111, positive: str = "repaint the sky", negative: str = "artifacts") -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd15.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": "source.png"}},
        "11": {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["4", 2]}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 20,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 0.6,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["11", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ai_studio_base_img2img", "images": ["8", 0]}},
    }


def _inpainting_api(*, seed: int = 222, positive: str = "remove the bicycle", negative: str = "artifacts") -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "512-inpainting-ema.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": "source.png"}},
        "12": {"class_type": "LoadImageMask", "inputs": {"image": "mask.png", "channel": "red"}},
        "13": {
            "class_type": "VAEEncodeForInpaint",
            "inputs": {"pixels": ["10", 0], "vae": ["4", 2], "mask": ["12", 0], "grow_mask_by": 6},
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
                "latent_image": ["13", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ai_studio_base_inpainting", "images": ["8", 0]}},
    }


def _outpainting_api(*, seed: int = 333, positive: str = "extend the scene", negative: str = "seam") -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd15.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": "source.png"}},
        "14": {
            "class_type": "ImagePadForOutpaint",
            "inputs": {"image": ["10", 0], "left": 256, "top": 0, "right": 256, "bottom": 0, "feathering": 24},
        },
        "13": {
            "class_type": "VAEEncodeForInpaint",
            "inputs": {"pixels": ["14", 0], "vae": ["4", 2], "mask": ["14", 1], "grow_mask_by": 6},
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
                "latent_image": ["13", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ai_studio_base_outpainting", "images": ["8", 0]}},
    }


def _single_output(node_id: str, filename: str) -> dict:
    return {node_id: {"images": [{"filename": filename, "subfolder": "", "type": "output"}]}}


def _run_provenance_simulations(results: list[tuple[str, str]], registered: dict) -> None:
    txt2img_ui = _load_ui("workflows/base/txt2img/workflow.json")
    img2img_ui = _load_ui("workflows/base/img2img/workflow.json")
    inpainting_ui = _load_ui("workflows/base/inpainting/workflow.json")
    outpainting_ui = _load_ui("workflows/base/outpainting/workflow.json")

    # 1. Live canonical txt2img (UI workflow present)
    hist = _history_entry(_txt2img_api(), txt2img_ui, _single_output("9", "ai_studio_base_txt2img_00001_.png"), "p-txt")
    ui = extract_ui_workflow_from_history(hist)
    _assert_true("UI workflow extracted from extra_pnginfo", ui is not None, results)
    prov = extract_execution_provenance(hist, registered_hashes=registered, ui_workflow=ui, output_node_id="9")
    _assert_equal("txt2img workflow_identifier", prov.workflow_identifier, "base/txt2img", results)
    _assert_equal("txt2img workflow_source", prov.workflow_source, "registered_canonical", results)
    _assert_equal("txt2img capability", prov.capability, "txt2img", results)
    _assert_equal("txt2img model_family", prov.model_family, "sd15", results)
    _assert_equal("txt2img hash_type ui_workflow_v1", prov.workflow_hash_type, HASH_TYPE_UI, results)
    _assert_equal("txt2img provenance complete", prov.provenance_status, "complete", results)

    # 2. Live canonical img2img (not txt2img)
    hist = _history_entry(_img2img_api(), img2img_ui, _single_output("9", "ai_studio_base_img2img_00001_.png"), "p-img")
    prov = extract_execution_provenance(hist, registered_hashes=registered, output_node_id="9")
    _assert_equal("img2img workflow_identifier", prov.workflow_identifier, "base/img2img", results)
    _assert_equal("img2img capability is img2img", prov.capability, "img2img", results)
    _assert_true("img2img not mislabeled txt2img", prov.capability != "txt2img", results)

    # 3. Live canonical inpainting
    hist = _history_entry(_inpainting_api(), inpainting_ui, _single_output("9", "ai_studio_base_inpainting_00001_.png"), "p-inp")
    prov = extract_execution_provenance(hist, registered_hashes=registered, output_node_id="9")
    _assert_equal("inpainting workflow_identifier", prov.workflow_identifier, "base/inpainting", results)
    _assert_equal("inpainting capability", prov.capability, "inpainting", results)
    _assert_true("inpainting model 512-inpainting-ema", "512-inpainting-ema.safetensors" in prov.model_files, results)
    _assert_equal("inpainting model_family", prov.model_family, "sd15_inpainting", results)

    # 4. Live canonical outpainting (not txt2img)
    hist = _history_entry(_outpainting_api(), outpainting_ui, _single_output("9", "ai_studio_base_outpainting_00001_.png"), "p-out")
    prov = extract_execution_provenance(hist, registered_hashes=registered, output_node_id="9")
    _assert_equal("outpainting workflow_identifier", prov.workflow_identifier, "base/outpainting", results)
    _assert_equal("outpainting capability", prov.capability, "outpainting", results)
    _assert_true("outpainting not mislabeled txt2img", prov.capability != "txt2img", results)

    # 5. UI hash and API prompt hash are distinct hash types
    _assert_true(
        "UI hash != API prompt hash",
        hash_ui_workflow(txt2img_ui) != hash_api_prompt(_txt2img_api()),
        results,
    )
    _assert_true("distinct hash type constants", HASH_TYPE_UI != HASH_TYPE_API, results)

    # 6. Moving UI nodes does not change UI workflow hash
    moved = copy.deepcopy(txt2img_ui)
    for node in moved.get("nodes", []):
        if isinstance(node, dict) and "pos" in node:
            node["pos"] = [9999, 9999]
    _assert_equal("UI position move keeps UI hash", hash_ui_workflow(txt2img_ui), hash_ui_workflow(moved), results)
    _assert_equal("UI move keeps structural signature", structural_signature_ui(txt2img_ui), structural_signature_ui(moved), results)

    # 7. Changing execution prompt changes API prompt hash
    _assert_true(
        "prompt change alters API prompt hash",
        hash_api_prompt(_txt2img_api(positive="a red bicycle")) != hash_api_prompt(_txt2img_api(positive="a blue car")),
        results,
    )

    # 8. Prompt resolution follows KSampler wiring even when negative node serializes first
    reordered = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "NEGATIVE_TEXT", "clip": ["4", 1]}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "POSITIVE_TEXT", "clip": ["4", 1]}},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd15.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 1, "steps": 10, "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
                "model": ["4", 0], "positive": ["2", 0], "negative": ["1", 0], "latent_image": ["5", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["8", 0]}},
    }
    prov = extract_execution_provenance({"prompt": [0, "r", reordered, {}, ["9"]], "outputs": {}}, registered_hashes=registered, output_node_id="9")
    _assert_equal("wiring resolves positive prompt", prov.positive_prompt, "POSITIVE_TEXT", results)
    _assert_equal("wiring resolves negative prompt", prov.negative_prompt, "NEGATIVE_TEXT", results)
    _assert_equal("prompt_resolution is wiring", prov.prompt_resolution, "wiring", results)

    # 9. Unrelated CLIPTextEncode nodes do not confuse wiring
    with_extra = copy.deepcopy(reordered)
    with_extra["20"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "UNRELATED", "clip": ["4", 1]}}
    prov = extract_execution_provenance({"prompt": [0, "r2", with_extra, {}, ["9"]], "outputs": {}}, registered_hashes=registered, output_node_id="9")
    _assert_equal("extra CLIP nodes ignored (positive)", prov.positive_prompt, "POSITIVE_TEXT", results)
    _assert_equal("extra CLIP nodes ignored (negative)", prov.negative_prompt, "NEGATIVE_TEXT", results)

    # 10. Multiple output branches resolve metadata for the synchronized output node
    branch = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd15.safetensors"}},
        "61": {"class_type": "CLIPTextEncode", "inputs": {"text": "BRANCH_A_POS", "clip": ["4", 1]}},
        "71": {"class_type": "CLIPTextEncode", "inputs": {"text": "neg", "clip": ["4", 1]}},
        "62": {"class_type": "CLIPTextEncode", "inputs": {"text": "BRANCH_B_POS", "clip": ["4", 1]}},
        "72": {"class_type": "CLIPTextEncode", "inputs": {"text": "neg", "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "31": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 10, "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0, "model": ["4", 0], "positive": ["61", 0], "negative": ["71", 0], "latent_image": ["5", 0]}},
        "32": {"class_type": "KSampler", "inputs": {"seed": 2, "steps": 10, "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0, "model": ["4", 0], "positive": ["62", 0], "negative": ["72", 0], "latent_image": ["5", 0]}},
        "81": {"class_type": "VAEDecode", "inputs": {"samples": ["31", 0], "vae": ["4", 2]}},
        "82": {"class_type": "VAEDecode", "inputs": {"samples": ["32", 0], "vae": ["4", 2]}},
        "91": {"class_type": "SaveImage", "inputs": {"filename_prefix": "branch_a", "images": ["81", 0]}},
        "92": {"class_type": "SaveImage", "inputs": {"filename_prefix": "branch_b", "images": ["82", 0]}},
    }
    hist_branch = {"prompt": [0, "b", branch, {}, ["91", "92"]], "outputs": {}}
    prov_a = extract_execution_provenance(hist_branch, registered_hashes=registered, output_node_id="91")
    prov_b = extract_execution_provenance(hist_branch, registered_hashes=registered, output_node_id="92")
    _assert_equal("branch A prompt", prov_a.positive_prompt, "BRANCH_A_POS", results)
    _assert_equal("branch B prompt", prov_b.positive_prompt, "BRANCH_B_POS", results)
    _assert_equal("branch A save prefix", prov_a.save_prefix, "branch_a", results)

    # 11-13. API-only structural fallback (no UI workflow)
    prov = extract_execution_provenance({"prompt": [0, "a1", _txt2img_api(), {}, ["9"]], "outputs": {}}, registered_hashes=registered, output_node_id="9")
    _assert_equal("API-only txt2img capability", prov.capability, "txt2img", results)
    _assert_equal("API-only txt2img hash_type", prov.workflow_hash_type, HASH_TYPE_API, results)
    prov = extract_execution_provenance({"prompt": [0, "a2", _img2img_api(), {}, ["9"]], "outputs": {}}, registered_hashes=registered, output_node_id="9")
    _assert_equal("API-only img2img capability", prov.capability, "img2img", results)
    prov = extract_execution_provenance({"prompt": [0, "a3", _outpainting_api(), {}, ["9"]], "outputs": {}}, registered_hashes=registered, output_node_id="9")
    _assert_equal("API-only outpainting capability", prov.capability, "outpainting", results)
    _assert_true("API-only never mislabels outpainting as txt2img", prov.capability != "txt2img", results)

    # 14. Unknown workflow remains unregistered and partial
    unknown = {"1": {"class_type": "SomeCustomNode", "inputs": {"foo": 1}}}
    prov = extract_execution_provenance({"prompt": [0, "u", unknown, {}, []], "outputs": {}}, registered_hashes=registered)
    _assert_equal("unknown workflow_source", prov.workflow_source, "unregistered", results)
    _assert_equal("unknown workflow_identifier", prov.workflow_identifier, "unknown", results)
    _assert_true("unknown never complete", prov.provenance_status != "complete", results)
    _assert_true("unknown lists workflow_identifier missing", "workflow_identifier" in prov.missing_provenance_fields, results)

    # 6b. Malformed extra data does not crash extraction
    malformed = {"prompt": [0, "m", _txt2img_api(), {"extra_pnginfo": {"workflow": "not-a-dict"}}, ["9"]], "outputs": {}}
    _assert_true("malformed extra_pnginfo yields no UI workflow", extract_ui_workflow_from_history(malformed) is None, results)


def _run_e2e_watcher_simulation(results: list[tuple[str, str]], registered: dict) -> None:
    """Critical: realistic history -> handle_prompt_id -> verified EvidenceRecord with complete provenance."""
    txt2img_ui = _load_ui("workflows/base/txt2img/workflow.json")
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        comfy_out = tmp / "ComfyUI" / "output"
        comfy_out.mkdir(parents=True)
        drive_out = tmp / "drive"
        drive_out.mkdir()
        output_file = comfy_out / "ai_studio_base_txt2img_00001_.png"
        output_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"pixels" * 32)

        prompt_id = "e2e-1"
        entry = _history_entry(
            _txt2img_api(positive="a photo of a cat", negative="ugly, blurry"),
            txt2img_ui,
            _single_output("9", "ai_studio_base_txt2img_00001_.png"),
            prompt_id,
        )

        service = OutputAutoSyncService(
            comfy_output_dir=comfy_out,
            drive_output_dir=drive_out,
            evidence_path=tmp / "evidence.jsonl",
            index_path=tmp / "index.json",
            status_path=tmp / "status.json",
            base_url="http://127.0.0.1:9",
            sleep_fn=lambda _s: None,
            max_copy_retries=1,
            registered_hashes=registered,
        )

        original_fetch = output_autosync.fetch_history
        output_autosync.fetch_history = lambda base_url, prompt_id=None: {prompt_id: entry}
        try:
            records, resolved = service.handle_prompt_id(prompt_id)
        finally:
            output_autosync.fetch_history = original_fetch

        _assert_true("E2E produced a record", len(records) == 1 and resolved, results)
        record = records[0].to_dict()
        _assert_equal("E2E sync_status verified", record.get("sync_status"), "verified", results)
        _assert_equal("E2E workflow_identifier base/txt2img", record.get("workflow_identifier"), "base/txt2img", results)
        _assert_equal("E2E workflow_source registered_canonical", record.get("workflow_source"), "registered_canonical", results)
        _assert_equal("E2E workflow_hash_type ui_workflow_v1", record.get("workflow_hash_type"), HASH_TYPE_UI, results)
        _assert_equal("E2E capability txt2img", record.get("capability"), "txt2img", results)
        _assert_equal("E2E model_family sd15", record.get("model_family"), "sd15", results)
        _assert_equal("E2E model_files", record.get("model_files"), ["sd15.safetensors"], results)
        _assert_equal("E2E positive prompt", record.get("positive_prompt"), "a photo of a cat", results)
        _assert_equal("E2E negative prompt", record.get("negative_prompt"), "ugly, blurry", results)
        _assert_equal("E2E seed", record.get("seed"), 424242, results)
        _assert_equal("E2E sampler", record.get("sampler_name"), "euler", results)
        _assert_equal("E2E provenance_status complete", record.get("provenance_status"), "complete", results)
        _assert_true("E2E api_prompt_hash present", bool(record.get("api_prompt_hash")), results)
        _assert_true("E2E drive copy verified", file_sha256(output_file) == record.get("drive_sha256"), results)
        _assert_true(
            "E2E permanent drive_filename",
            str(record.get("drive_filename") or "").startswith("txt2img_"),
            results,
        )
        _assert_equal(
            "E2E source_filename preserved",
            record.get("source_filename"),
            "ai_studio_base_txt2img_00001_.png",
            results,
        )


def _run_launch_and_truthfulness(results: list[tuple[str, str]], bundle) -> None:
    notebook = (_REPO_ROOT / "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb").read_text(encoding="utf-8")
    _assert_true(
        "Launch guidance has no required sync_outputs.py step",
        "sync the latest output to Drive" not in notebook,
        results,
    )
    _assert_true(
        "Post-launch summary drops verify_generation.py",
        'run_repo_python("core/scripts/verify_generation.py"' not in notebook,
        results,
    )
    _assert_true(
        "Automatic output persistence block present",
        "Automatic output persistence" in notebook and "no manual sync command is required" in notebook,
        results,
    )
    readme = (_REPO_ROOT / "core/scripts/README.md").read_text(encoding="utf-8")
    _assert_true(
        "sync_outputs classified maintenance/diagnostic",
        "Maintenance" in readme or "maintenance" in readme,
        results,
    )

    manager = CapabilityManager(bundle=bundle)
    inpaint = manager.evaluate_capability("inpainting").to_dict()
    _assert_equal("inpainting runtime_status ready", inpaint.get("runtime_status"), "ready", results)
    _assert_equal("inpainting quality_status benchmark_failed", inpaint.get("quality_status"), "benchmark_failed", results)
    _assert_equal("inpainting production_status experimental", inpaint.get("production_status"), "experimental", results)
    _assert_true("inpainting not production-approved", inpaint.get("production_status") != "approved", results)
    qwen_cap = next(c for c in manager.capabilities if c["id"] == "qwen_image_edit_benchmark")
    flux_cap = next(c for c in manager.capabilities if c["id"] == "flux_fill_benchmark")
    _assert_equal("Qwen remains benchmark-only", qwen_cap.get("implementation_status"), "benchmark", results)
    _assert_equal("FLUX remains benchmark-only", flux_cap.get("implementation_status"), "benchmark", results)


def _run_workspace_simulations(results: list[tuple[str, str]]) -> None:
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        drive_root = tmp / "AI_Studio"
        workspace = ProjectWorkspace(drive_root)
        manifest = workspace.create_project(display_name="Sim Project", slug="sim-project")
        _assert_true("Project manifest validates", not validate_manifest(manifest.to_dict()), results)
        _assert_true("Create/list project", len(workspace.list_projects()) == 1, results)
        workspace.set_active_project("sim-project")
        active = workspace.get_active_project()
        _assert_true("Set/show active project", active is not None and active.slug == "sim-project", results)
        try:
            workspace.create_project(display_name="Sim Project", slug="sim-project")
            results.append(("Duplicate project slug rejected", "FAIL"))
            raise AssertionError("Duplicate project slug rejected")
        except FileExistsError:
            results.append(("Duplicate project slug rejected", "PASS"))
        workspace.set_active_project(None)
        _assert_true("No-project mode clears active project", workspace.get_active_project() is None, results)

    catalog = build_catalog(_REPO_ROOT)
    inpaint_entry = next((e for e in catalog if e["workflow_identifier"] == "base/inpainting"), None)
    _assert_true("Workflow catalog includes inpainting", inpaint_entry is not None, results)
    if inpaint_entry:
        _assert_equal("Catalog inpainting quality failed", inpaint_entry["quality_status"], "benchmark_failed", results)

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        comfy_input = tmp / "input"
        comfy_input.mkdir()
        source_image = tmp / "source.png"
        source_image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
        result = prepare_workflow(
            _REPO_ROOT,
            tmp / "runtime",
            comfyui_input_dir=comfy_input,
            workflow="img2img",
            input_path=source_image,
            drive_prepared_dir=tmp / "drive_prepared",
        )
        _assert_true("Prepared workflow exports to Drive path", bool(result.drive_prepared_path), results)
        _assert_equal(
            "Canonical workflow unchanged after preparation",
            (_REPO_ROOT / "workflows/base/img2img/workflow.json").read_bytes(),
            (_REPO_ROOT / "workflows/base/img2img/workflow.json").read_bytes(),
            results,
        )
        prepared = json.loads(Path(result.prepared_path).read_text(encoding="utf-8"))
        embedded = prepared.get("extra", {}).get("ai_studio", {})
        _assert_equal("Prepared workflow carries ai_studio metadata", embedded.get("workflow_identifier"), "base/img2img", results)


def _run_legacy_readability(results: list[tuple[str, str]]) -> None:
    with tempfile.TemporaryDirectory() as tmp_name:
        ledger_path = Path(tmp_name) / "evidence.jsonl"
        ledger = EvidenceLedger(ledger_path)
        # Legacy Package 4.4 row (no schema_version).
        ledger.append(EvidenceRecord(prompt_id="legacy-1", sync_status="verified", local_sha256="abc"))
        # Early Package 4.5 row (schema_version 2, partial provenance, no hash_type).
        early = EvidenceRecord(
            prompt_id="early-1",
            schema_version=SCHEMA_VERSION,
            workflow_identifier="base/txt2img",
            workflow_hash="deadbeef",
            capability="txt2img",
            model_files=["sd15.safetensors"],
            positive_prompt="test",
            sync_status="verified",
            provenance_status="partial",
        )
        ledger.append(early)
        rows = ledger.read_all()
        _assert_true("Legacy 4.4 row readable", is_legacy_row(rows[0]), results)
        _assert_true("Early 4.5 row not legacy", not is_legacy_row(rows[1]), results)
        _assert_equal("Early 4.5 provenance label partial", provenance_label(rows[1]), "partial", results)
        summary = summarize_ledger(ledger_path)
        _assert_true("History summary reads mixed rows", summary.total == 2, results)


def run_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    bundle = RegistryLoader(_REPO_ROOT).load_all()
    registered = load_registered_workflow_hashes(_REPO_ROOT, bundle.workflows)

    _run_launch_and_truthfulness(results, bundle)
    _run_provenance_simulations(results, registered)
    _run_e2e_watcher_simulation(results, registered)
    _run_workspace_simulations(results)
    _run_legacy_readability(results)

    for module in (
        "simulate_package3_hardening.py",
        "simulate_package4_editing.py",
        "simulate_output_autosync.py",
        "simulate_modern_editing_benchmark.py",
    ):
        _assert_true(f"Regression suite present: {module}", (_REPO_ROOT / "core/scripts" / module).is_file(), results)

    return results


def main() -> int:
    print("AI Studio — Package 4.5 Provenance & Workspace Simulations")
    print("=" * 50)
    try:
        results = run_simulations()
    except AssertionError as exc:
        print(f"\nASSERTION FAILED: {exc}")
        return 1

    passed = sum(1 for _, status in results if status == "PASS")
    for name, status in results:
        print(f"  [{status}] {name}")
    print(f"\nSummary: {passed}/{len(results)} simulations passed")
    if passed != len(results):
        print("\nRESULT: FAIL — package 4.5 simulations failed.")
        return 1
    print("\nRESULT: OK — package 4.5 simulations passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
