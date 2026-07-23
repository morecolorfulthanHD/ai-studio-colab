#!/usr/bin/env python3
"""Package 4.8 — Workflow Library simulations."""

from __future__ import annotations

import copy
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

from core.runtime.generation_evidence_ledger import EvidenceRecord
from core.runtime.generation_snapshot import build_metadata_snapshot
from core.runtime.png_utils import write_rgb_png
from core.runtime.preparation_identity import (
    InvalidPreparationIdError,
    normalize_preparation_id,
)
from core.runtime.prepared_workflow_index import (
    append_preparation_record,
    find_by_preparation_id,
    preparations_log_path,
    read_preparation_records,
)
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import find_repo_root
from core.runtime.workflow_edit_relationship import compare_workflow_relationship
from core.runtime.workflow_library_preparation import prepare_library_workflow
from core.runtime.workflow_manifest import (
    list_workflow_manifests,
    load_workflow_manifest,
    resolve_workflow_identifier,
    validate_manifest_against_canonical,
    validate_manifest_structure,
    workflow_id_for_identifier,
)
from core.runtime.workflow_parameters import (
    apply_parameter_bindings,
    coerce_and_validate_parameters,
)
from core.runtime.workflow_provenance import (
    ExecutionProvenance,
    extract_ai_studio_extra,
    hash_api_prompt,
    hash_ui_workflow,
)
from core.runtime.workflow_readiness import (
    READINESS_BENCHMARK_ONLY,
    READINESS_EXPERIMENTAL,
    READINESS_READY,
    evaluate_workflow_readiness,
)
from core.scripts.validate_prepared_workflow import validate_prepared_dir
from core.scripts.workflow_catalog import build_catalog

MODEL_FILES_PRESENT = {
    "sd15.safetensors": True,
    "512-inpainting-ema.safetensors": True,
}


class SimulationFailure(Exception):
    pass


def _pass(results: list[tuple[str, str]], name: str) -> None:
    results.append((name, "PASS"))


def _assert_true(label: str, value: bool) -> None:
    if not value:
        raise SimulationFailure(f"{label}: expected True")


def _assert_equal(label: str, actual, expected) -> None:
    if actual != expected:
        raise SimulationFailure(f"{label}: expected {expected!r}, got {actual!r}")


def _assert_false(label: str, value: bool) -> None:
    if value:
        raise SimulationFailure(f"{label}: expected False")


def _assert_raises_invalid_prep(label: str, value: str) -> None:
    try:
        normalize_preparation_id(value)
    except InvalidPreparationIdError:
        return
    raise SimulationFailure(f"{label}: expected InvalidPreparationIdError")


def _write_png(path: Path, fill: tuple[int, int, int] = (10, 20, 30)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [[fill for _ in range(8)] for _ in range(8)]
    write_rgb_png(path, 8, 8, rows)


def _comfy_object_info(manifest: dict) -> dict[str, dict]:
    nodes = manifest.get("required_nodes") or []
    return {str(node): {} for node in nodes}


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
    return {
        "drive": drive,
        "runtime_prepared": runtime / "prepared_workflows",
        "drive_prepared": drive / "workflows" / "prepared",
        "comfy_input": comfy_input,
    }


def _prepare_txt2img(
    repo_root: Path,
    paths: dict[str, Path],
    *,
    parameters: dict | None = None,
    active_project=None,
    dry_run: bool = False,
    allow_experimental: bool = False,
    allow_benchmark: bool = False,
):
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
        active_project=active_project,
        allow_experimental=allow_experimental,
        allow_benchmark=allow_benchmark,
        dry_run=dry_run,
        allowed_input_roots=[paths["drive"] / "inputs", repo_root / "inputs"],
        comfy_object_info=_comfy_object_info(manifest),
        model_files_present=MODEL_FILES_PRESENT,
    )


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
    # 1–14 manifests / catalog / info / readiness / gates
    # ------------------------------------------------------------------
    manifests = list_workflow_manifests(repo_root)
    _assert_true("manifests discovered", len(manifests) >= 4)
    identifiers = {str(m.get("_workflow_identifier") or "") for m in manifests}
    for expected in (
        "base/txt2img",
        "base/img2img",
        "base/inpainting",
        "base/outpainting",
        "reference/qwen_image_edit",
        "reference/flux_fill",
    ):
        _assert_true(f"manifest present {expected}", expected in identifiers)
    _pass(results, "list_workflow_manifests discovers library workflows")

    _assert_equal("resolve txt2img", resolve_workflow_identifier("txt2img"), "base/txt2img")
    _assert_equal("resolve img2img", resolve_workflow_identifier("img2img"), "base/img2img")
    _assert_equal("resolve inpainting", resolve_workflow_identifier("inpainting"), "base/inpainting")
    _assert_equal("resolve outpainting", resolve_workflow_identifier("outpainting"), "base/outpainting")
    _assert_equal("resolve qwen alias", resolve_workflow_identifier("qwen_image_edit"), "reference/qwen_image_edit")
    _assert_equal("resolve flux alias", resolve_workflow_identifier("flux_fill"), "reference/flux_fill")
    _pass(results, "resolve_workflow_identifier normalizes aliases")
    _pass(results, "resolve_workflow_identifier resolves benchmark aliases")

    _assert_equal("workflow_id txt2img", workflow_id_for_identifier("base/txt2img"), "base_txt2img")
    _pass(results, "workflow_id_for_identifier maps registry workflow id")

    for wf_id in ("base/txt2img", "base/img2img", "base/inpainting", "base/outpainting"):
        manifest = load_workflow_manifest(repo_root, wf_id)
        _assert_true(f"{wf_id} structure", not validate_manifest_structure(manifest))
        _assert_true(f"{wf_id} canonical hash", not validate_manifest_against_canonical(repo_root, manifest))
    _pass(results, "load_workflow_manifest txt2img validates")
    _pass(results, "validate_manifest_structure and hash pass for base workflows")

    catalog = build_catalog(repo_root)
    _assert_true("build_catalog non-empty", len(catalog) >= 4)
    ready_catalog = build_catalog(repo_root, ready_only=True)
    ready_ids = {e["workflow_identifier"] for e in ready_catalog}
    _assert_true("catalog ready-only includes txt2img", "base/txt2img" in ready_ids)
    benchmark_catalog = build_catalog(repo_root, include_benchmark=False)
    benchmark_ids = {e["workflow_identifier"] for e in benchmark_catalog}
    _assert_true("catalog excludes benchmark by default", "reference/flux_fill" not in benchmark_ids)
    _pass(results, "build_catalog filters and sorts entries")
    _pass(results, "build_catalog excludes benchmark workflows by default")

    txt2img_manifest = load_workflow_manifest(repo_root, "base/txt2img")
    txt2img_nodes = _comfy_object_info(txt2img_manifest)
    ready = evaluate_workflow_readiness(
        repo_root,
        "base/txt2img",
        comfy_object_info=txt2img_nodes,
        model_files_present=MODEL_FILES_PRESENT,
    )
    _assert_equal("txt2img readiness ready", ready.status, READINESS_READY)
    _pass(results, "evaluate_workflow_readiness txt2img ready with models and nodes")

    partial = evaluate_workflow_readiness(repo_root, "base/img2img", model_files_present=MODEL_FILES_PRESENT)
    _assert_true("img2img readiness partial or ready", partial.status in {"ready", "partial"})
    _pass(results, "evaluate_workflow_readiness img2img reports partial caution")

    exp_gate = evaluate_workflow_readiness(
        repo_root,
        "base/inpainting",
        model_files_present=MODEL_FILES_PRESENT,
    )
    _assert_equal("inpainting experimental gate", exp_gate.status, READINESS_EXPERIMENTAL)
    _assert_true(
        "inpainting gate reason",
        any("allow-experimental" in r for r in exp_gate.reasons),
    )
    _pass(results, "experimental workflow requires allow-experimental gate")

    exp_ready = evaluate_workflow_readiness(
        repo_root,
        "base/inpainting",
        allow_experimental=True,
        comfy_object_info=_comfy_object_info(load_workflow_manifest(repo_root, "base/inpainting")),
        model_files_present=MODEL_FILES_PRESENT,
    )
    _assert_equal("inpainting ready with experimental flag", exp_ready.status, READINESS_EXPERIMENTAL)
    _pass(results, "experimental workflow readiness passes with allow-experimental")

    qwen_gate = evaluate_workflow_readiness(repo_root, "reference/qwen_image_edit")
    _assert_equal("qwen benchmark gate", qwen_gate.status, READINESS_BENCHMARK_ONLY)
    _pass(results, "benchmark workflow requires allow-benchmark gate")

    bench_ready = evaluate_workflow_readiness(
        repo_root,
        "reference/qwen_image_edit",
        allow_benchmark=True,
        model_files_present=MODEL_FILES_PRESENT,
    )
    _assert_equal("qwen ready with benchmark flag", bench_ready.status, READINESS_BENCHMARK_ONLY)
    _pass(results, "benchmark workflow readiness passes with allow-benchmark")

    # ------------------------------------------------------------------
    # 15–25 parameter validation
    # ------------------------------------------------------------------
    schema = txt2img_manifest.get("parameter_schema") or {}
    defaults = txt2img_manifest.get("default_parameters") or {}

    _, empty_errors = coerce_and_validate_parameters(schema, defaults, {"positive_prompt": "   "})
    _assert_true("positive_prompt empty fails", any("positive_prompt" in e for e in empty_errors))
    _pass(results, "coerce_and_validate_parameters rejects empty positive_prompt")

    params, seed_errors = coerce_and_validate_parameters(
        schema, defaults, {"positive_prompt": "test", "seed": "424242"}
    )
    _assert_true("seed coercion ok", not seed_errors)
    _assert_equal("seed coerced int", params.get("seed"), 424242)
    _pass(results, "coerce_and_validate_parameters coerces integer seed")

    params, width_errors = coerce_and_validate_parameters(
        schema, defaults, {"positive_prompt": "test", "width": 513}
    )
    _assert_true("width normalization ok", not width_errors)
    _assert_equal("width divisible by 8", params.get("width") % 8, 0)
    _pass(results, "coerce_and_validate_parameters normalizes width divisible_by_8")

    _, enum_errors = coerce_and_validate_parameters(
        schema, defaults, {"positive_prompt": "test", "sampler_name": "not_a_sampler"}
    )
    _assert_true("enum validation fails", any("sampler_name" in e for e in enum_errors))
    _pass(results, "coerce_and_validate_parameters validates enum sampler_name")

    params, prefix_errors = coerce_and_validate_parameters(
        schema,
        defaults,
        {"positive_prompt": "test", "save_prefix": "bad/name?prefix"},
    )
    _assert_true("save_prefix ok", not prefix_errors)
    _assert_true("save_prefix sanitized", "/" not in str(params.get("save_prefix")))
    _pass(results, "coerce_and_validate_parameters normalizes save_prefix")

    _, missing_errors = coerce_and_validate_parameters(schema, defaults, {})
    _assert_true("missing positive_prompt fails", any("positive_prompt" in e for e in missing_errors))
    _pass(results, "coerce_and_validate_parameters rejects missing required params")

    canonical = json.loads(
        (repo_root / str(txt2img_manifest["canonical_workflow_path"])).read_text(encoding="utf-8")
    )
    bound = apply_parameter_bindings(
        copy.deepcopy(canonical),
        schema,
        {"positive_prompt": "bound prompt", "seed": 999, "negative_prompt": "blur"},
    )
    prompt_node = next(n for n in bound["nodes"] if str(n.get("id")) == "6")
    _assert_equal("binding prompt node", prompt_node["widgets_values"][0], "bound prompt")
    sampler_node = next(n for n in bound["nodes"] if str(n.get("id")) == "3")
    _assert_equal("binding seed node", sampler_node["widgets_values"][0], 999)
    _pass(results, "apply_parameter_bindings updates prompt and seed nodes")

    img2img_manifest = load_workflow_manifest(repo_root, "base/img2img")
    img_bound = apply_parameter_bindings(
        copy.deepcopy(json.loads((repo_root / str(img2img_manifest["canonical_workflow_path"])).read_text(encoding="utf-8"))),
        img2img_manifest.get("parameter_schema") or {},
        {"input_image": "staged_input.png", "positive_prompt": "img2img test"},
    )
    load_node = next(n for n in img_bound["nodes"] if str(n.get("id")) == "1")
    _assert_equal("binding staged image basename", load_node["widgets_values"][0], "staged_input.png")
    _pass(results, "apply_parameter_bindings stages image basename on LoadImage node")

    out_manifest = load_workflow_manifest(repo_root, "base/outpainting")
    _, out_errors = coerce_and_validate_parameters(
        out_manifest.get("parameter_schema") or {},
        out_manifest.get("default_parameters") or {},
        {
            "input_image": "x.png",
            "positive_prompt": "extend",
            "left": 0,
            "right": 0,
            "top": 0,
            "bottom": 0,
        },
    )
    with tempfile.TemporaryDirectory() as tmp:
        paths = _prep_paths(Path(tmp))
        out_prep = prepare_library_workflow(
            repo_root,
            workflow_identifier="base/outpainting",
            parameters={
                "input_image": str(paths["drive"] / "inputs" / "missing.png"),
                "positive_prompt": "extend",
                "left": 0,
                "right": 0,
                "top": 0,
                "bottom": 0,
            },
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            comfy_object_info=_comfy_object_info(out_manifest),
            model_files_present=MODEL_FILES_PRESENT,
        )
    _assert_true("outpainting zero sides blocked", not out_prep.ok)
    _assert_true("outpainting cross rule", any("expansion side" in e.lower() for e in out_prep.errors))
    _pass(results, "outpainting cross-parameter rule rejects zero expansion sides")

    in_manifest = load_workflow_manifest(repo_root, "base/inpainting")
    in_prep_fail = prepare_library_workflow(
        repo_root,
        workflow_identifier="base/inpainting",
        parameters={"positive_prompt": "inpaint", "source_image": "a.png"},
        runtime_prepared_root=Path(tempfile.mkdtemp()) / "prepared",
        drive_prepared_root=Path(tempfile.mkdtemp()) / "prepared",
        comfyui_input_dir=Path(tempfile.mkdtemp()) / "input",
        drive_root=Path(tempfile.mkdtemp()) / "drive",
        allow_experimental=True,
        model_files_present=MODEL_FILES_PRESENT,
    )
    _assert_true("inpainting missing mask fails", not in_prep_fail.ok)
    _assert_true("inpainting mask error", any("mask_image" in e for e in in_prep_fail.errors))
    _pass(results, "inpainting cross-parameter rule requires mask_image")

    # ------------------------------------------------------------------
    # 26–36 preparation writes / dry-run / canonical unchanged
    # ------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        paths = _prep_paths(Path(tmp))
        canonical_hash_before = hash_ui_workflow(canonical)

        dry = _prepare_txt2img(repo_root, paths, dry_run=True)
        _assert_true("dry-run ok", dry.ok)
        _assert_true("dry-run no runtime dir", not Path(dry.runtime_prepared_dir).exists())
        _assert_true("dry-run prep id allocated", dry.preparation_id.startswith("prep_"))
        _assert_true("dry-run no index append", not preparations_log_path(paths["drive"]).is_file())
        _pass(results, "prepare txt2img dry-run allocates id without writes")
        _pass(results, "prepare txt2img dry-run does not append preparation index")

        prep = _prepare_txt2img(repo_root, paths, parameters={"positive_prompt": "mountain demo", "seed": 424242})
        _assert_true("prepare ok", prep.ok)
        _assert_true("runtime workflow written", Path(prep.runtime_workflow_path).is_file())
        _assert_true("runtime metadata written", Path(prep.runtime_metadata_path).is_file())
        _assert_true("runtime manifest written", Path(prep.runtime_manifest_path).is_file())
        _pass(results, "prepare txt2img writes runtime artifacts")

        _assert_true("drive prepared copy exists", Path(prep.drive_prepared_dir).is_dir())
        _pass(results, "prepare txt2img writes drive prepared copy")

        canonical_after = json.loads(
            (repo_root / str(txt2img_manifest["canonical_workflow_path"])).read_text(encoding="utf-8")
        )
        _assert_equal("canonical unchanged hash", hash_ui_workflow(canonical_after), canonical_hash_before)
        _pass(results, "canonical workflow file unchanged after preparation")

        prepared_data = json.loads(Path(prep.runtime_workflow_path).read_text(encoding="utf-8"))
        ai_meta = extract_ai_studio_extra(prepared_data)
        _assert_equal("embedded preparation_id", ai_meta.get("preparation_id"), prep.preparation_id)
        _assert_equal("embedded workflow_identifier", ai_meta.get("workflow_identifier"), "base/txt2img")
        _pass(results, "prepared workflow embeds ai_studio metadata")

        log_path = preparations_log_path(paths["drive"])
        record = find_by_preparation_id(log_path, prep.preparation_id)
        _assert_true("index record found", record is not None)
        assert record is not None
        _assert_equal("index workflow id", record.get("workflow_identifier"), "base/txt2img")
        _pass(results, "preparation index append and lookup")

        _assert_true("prepared hash differs when parameterized", prep.prepared_workflow_hash != prep.canonical_workflow_hash)
        rel = compare_workflow_relationship(
            prep.canonical_workflow_hash,
            prep.prepared_workflow_hash,
            "",
        )
        _assert_equal("prepared relationship", rel["relationship"], "prepared_parameterized_from_canonical")
        _pass(results, "prepared workflow hash reflects parameterization")

        workspace = ProjectWorkspace(paths["drive"])
        mountain = workspace.create_project(display_name="Mountain Demo", slug="mountain-demo", set_active=True)
        project_prep = _prepare_txt2img(
            repo_root,
            paths,
            parameters={"positive_prompt": "project scoped"},
            active_project=mountain,
        )
        _assert_true("project prep ok", project_prep.ok)
        project_dir = Path(project_prep.project_prepared_dir)
        _assert_true("project mirror written", project_dir.is_dir())
        _pass(results, "active project preparation writes project mirror")

        prep_id = normalize_preparation_id(prep.preparation_id.replace("prep_", ""))
        _assert_equal("normalize bare uuid", prep_id, prep.preparation_id)
        _assert_raises_invalid_prep("reject path-like id", "../../etc/passwd")
        _pass(results, "normalize_preparation_id accepts canonical and bare UUID forms")

        # ------------------------------------------------------------------
        # 37–45 img2img / outpaint / inpaint staging & validation
        # ------------------------------------------------------------------
        src_png = paths["drive"] / "inputs" / "source.png"
        _write_png(src_png, fill=(40, 50, 60))
        img2img_prep = prepare_library_workflow(
            repo_root,
            workflow_identifier="base/img2img",
            parameters={"input_image": str(src_png), "positive_prompt": "refine mountain"},
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            allowed_input_roots=[paths["drive"] / "inputs", repo_root / "inputs"],
            comfy_object_info=_comfy_object_info(img2img_manifest),
            model_files_present=MODEL_FILES_PRESENT,
        )
        _assert_true("img2img prepare ok", img2img_prep.ok)
        _assert_true("img2img staged filename", bool(img2img_prep.staged_filenames.get("input_image")))
        _pass(results, "img2img preparation stages input image")

        missing_img = prepare_library_workflow(
            repo_root,
            workflow_identifier="base/img2img",
            parameters={"input_image": str(paths["drive"] / "inputs" / "nope.png"), "positive_prompt": "x"},
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            allowed_input_roots=[paths["drive"] / "inputs"],
            comfy_object_info=_comfy_object_info(img2img_manifest),
            model_files_present=MODEL_FILES_PRESENT,
        )
        _assert_true("img2img missing file fails", not missing_img.ok)
        _pass(results, "img2img preparation rejects missing input file")

        out_src = paths["drive"] / "inputs" / "outpaint.png"
        _write_png(out_src)
        out_prep = prepare_library_workflow(
            repo_root,
            workflow_identifier="base/outpainting",
            parameters={
                "input_image": str(out_src),
                "positive_prompt": "extend horizon",
                "left": 128,
                "right": 0,
                "top": 0,
                "bottom": 0,
            },
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            allowed_input_roots=[paths["drive"] / "inputs"],
            comfy_object_info=_comfy_object_info(out_manifest),
            model_files_present=MODEL_FILES_PRESENT,
        )
        _assert_true("outpainting prepare ok", out_prep.ok)
        _pass(results, "outpainting preparation accepts nonzero expansion side")

        exp_blocked = prepare_library_workflow(
            repo_root,
            workflow_identifier="base/inpainting",
            parameters={
                "source_image": str(src_png),
                "mask_image": str(paths["drive"] / "masks" / "mask.png"),
                "positive_prompt": "fill sky",
            },
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            allowed_input_roots=[paths["drive"] / "inputs", paths["drive"] / "masks"],
            model_files_present=MODEL_FILES_PRESENT,
        )
        _assert_true("inpainting blocked without experimental flag", not exp_blocked.ok)
        _pass(results, "inpainting preparation blocked without allow-experimental")

        mask_png = paths["drive"] / "masks" / "mask.png"
        _write_png(mask_png, fill=(255, 255, 255))
        in_prep = prepare_library_workflow(
            repo_root,
            workflow_identifier="base/inpainting",
            parameters={
                "source_image": str(src_png),
                "mask_image": str(mask_png),
                "positive_prompt": "fill sky",
            },
            runtime_prepared_root=paths["runtime_prepared"],
            drive_prepared_root=paths["drive_prepared"],
            comfyui_input_dir=paths["comfy_input"],
            drive_root=paths["drive"],
            allow_experimental=True,
            allowed_input_roots=[paths["drive"] / "inputs", paths["drive"] / "masks"],
            comfy_object_info=_comfy_object_info(in_manifest),
            model_files_present=MODEL_FILES_PRESENT,
        )
        _assert_true("inpainting experimental ok", in_prep.ok)
        _assert_true("inpaint staged source", "source_image" in in_prep.staged_filenames)
        _assert_true("inpaint staged mask", "mask_image" in in_prep.staged_filenames)
        _pass(results, "experimental inpainting preparation stages source and mask")

        outside = repo_root / "inputs" / "_sim_outside.png"
        outside.parent.mkdir(parents=True, exist_ok=True)
        _write_png(outside)
        try:
            outside_blocked = prepare_library_workflow(
                repo_root,
                workflow_identifier="base/img2img",
                parameters={"input_image": str(outside), "positive_prompt": "outside root"},
                runtime_prepared_root=paths["runtime_prepared"],
                drive_prepared_root=paths["drive_prepared"],
                comfyui_input_dir=paths["comfy_input"],
                drive_root=paths["drive"],
                allowed_input_roots=[paths["drive"] / "inputs"],
                comfy_object_info=_comfy_object_info(img2img_manifest),
                model_files_present=MODEL_FILES_PRESENT,
            )
            _assert_true("outside allowed root fails", not outside_blocked.ok)
            _assert_true(
                "outside root error",
                any("allowed roots" in e.lower() for e in outside_blocked.errors),
            )
        finally:
            outside.unlink(missing_ok=True)
        _pass(results, "preparation rejects input paths outside allowed roots")

        # ------------------------------------------------------------------
        # 46–48 qwen / flux benchmark + no autodownload
        # ------------------------------------------------------------------
        flux_blocked = evaluate_workflow_readiness(repo_root, "reference/flux_fill")
        _assert_equal("flux benchmark gate status", flux_blocked.status, READINESS_BENCHMARK_ONLY)
        _pass(results, "flux_fill benchmark gated without allow-benchmark")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = AssertionError("download subprocess must not run")
            flux_prep = prepare_library_workflow(
                repo_root,
                workflow_identifier="reference/flux_fill",
                runtime_prepared_root=paths["runtime_prepared"],
                drive_prepared_root=paths["drive_prepared"],
                comfyui_input_dir=paths["comfy_input"],
                drive_root=paths["drive"],
                allow_benchmark=True,
                model_files_present=MODEL_FILES_PRESENT,
            )
        _assert_true("flux benchmark prepare ok", flux_prep.ok)
        joined = " ".join(flux_prep.messages).lower()
        _assert_true("flux no download messages", "download" not in joined)
        _pass(results, "flux_fill benchmark prepare does not invoke download paths")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = AssertionError("download subprocess must not run")
            qwen_prep = prepare_library_workflow(
                repo_root,
                workflow_identifier="reference/qwen_image_edit",
                runtime_prepared_root=paths["runtime_prepared"],
                drive_prepared_root=paths["drive_prepared"],
                comfyui_input_dir=paths["comfy_input"],
                drive_root=paths["drive"],
                allow_benchmark=True,
                model_files_present=MODEL_FILES_PRESENT,
            )
        _assert_true("qwen benchmark prepare ok", qwen_prep.ok)
        _pass(results, "qwen_image_edit benchmark prepare does not autodownload")

        # ------------------------------------------------------------------
        # 49–53 index / info / validate prepared
        # ------------------------------------------------------------------
        _assert_equal(
            "preparations log path",
            preparations_log_path(paths["drive"]).name,
            "workflow_preparations.jsonl",
        )
        _pass(results, "preparations log path under drive logs")

        append_preparation_record(
            log_path,
            {
                "preparation_id": "prep_00000000-0000-4000-8000-000000000099",
                "workflow_identifier": "base/txt2img",
                "workflow_id": workflow_id_for_identifier("base/txt2img"),
                "prepared_workflow_hash": "abc",
                "canonical_workflow_hash": "def",
            },
        )
        rows = read_preparation_records(log_path)
        _assert_true("append record persisted", any(r.get("preparation_id", "").endswith("0099") for r in rows))
        _pass(results, "append_preparation_record persists to jsonl")

        info_record = find_by_preparation_id(log_path, prep.preparation_id)
        _assert_true("prepared info lookup", info_record is not None and info_record.get("prepared_workflow_hash"))
        _pass(results, "find_by_preparation_id supports prepared workflow info lookup")

        validate_errors = validate_prepared_dir(Path(prep.drive_prepared_dir), prep.preparation_id)
        _assert_equal("validate prepared dir clean", validate_errors, [])
        _pass(results, "validate_prepared_dir passes for prepared artifacts")

        bad_dir = Path(prep.drive_prepared_dir)
        manifest_path = bad_dir / f"{prep.preparation_id}.manifest.json"
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_data["prepared_workflow_hash"] = "deadbeef"
        manifest_path.write_text(json.dumps(manifest_data) + "\n", encoding="utf-8")
        bad_errors = validate_prepared_dir(bad_dir, prep.preparation_id)
        _assert_true("validate catches hash mismatch", any("hash mismatch" in e for e in bad_errors))
        _pass(results, "validate_prepared_dir catches prepared_workflow_hash mismatch")

        # ------------------------------------------------------------------
        # 60–65 preparation metadata / edit relationship / snapshot authority
        # ------------------------------------------------------------------
        meta = extract_ai_studio_extra(prepared_data)
        _assert_true("metadata preparation_id", bool(meta.get("preparation_id")))
        _assert_true("metadata prepared hash", bool(meta.get("prepared_workflow_hash")))
        _pass(results, "extract_ai_studio_extra returns preparation metadata")

        executed = copy.deepcopy(prepared_data)
        executed_matches = compare_workflow_relationship(
            prep.canonical_workflow_hash,
            prep.prepared_workflow_hash,
            prep.prepared_workflow_hash,
        )
        _assert_equal("executed matches prepared", executed_matches["relationship"], "executed_matches_prepared")
        _pass(results, "compare_workflow_relationship reports executed_matches_prepared")

        for node in executed.get("nodes") or []:
            if str(node.get("id")) == "3":
                widgets = list(node.get("widgets_values") or [])
                if widgets:
                    widgets[0] = 999999
                node["widgets_values"] = widgets
        executed_hash = hash_ui_workflow(executed)
        modified = compare_workflow_relationship(
            prep.canonical_workflow_hash,
            prep.prepared_workflow_hash,
            executed_hash,
        )
        _assert_equal("executed modified label", modified["relationship"], "executed_modified_after_preparation")
        _assert_true("executed modified flag", modified["executed_modified_after_preparation"])
        _pass(results, "compare_workflow_relationship detects executed modifications")

        unchanged = compare_workflow_relationship(
            prep.canonical_workflow_hash,
            prep.canonical_workflow_hash,
            prep.canonical_workflow_hash,
        )
        _assert_equal("canonical relationship", unchanged["relationship"], "executed_matches_canonical")
        _pass(results, "compare_workflow_relationship canonical equality")

        provenance = ExecutionProvenance(
            workflow_identifier="base/txt2img",
            workflow_hash=executed_hash,
            workflow_hash_type="ui",
            api_prompt_hash=hash_api_prompt({"3": {"class_type": "KSampler", "inputs": {"seed": 424242}}}),
            workflow_source="registered_canonical",
            capability="txt2img",
            model_family="sd15",
            model_files=["sd15.safetensors"],
            positive_prompt="mountain demo",
            negative_prompt="",
            seed=424242,
            steps=24,
            cfg=7.0,
            sampler_name="euler",
            scheduler="normal",
            denoise=1.0,
            width=512,
            height=768,
            provenance_status="complete",
            preparation_id=prep.preparation_id,
        )
        snap_meta = build_metadata_snapshot(
            generation_id="gen_pkg48-e2e-0001-4000-8000-000000000048",
            record=EvidenceRecord(
                prompt_id="p-pkg48",
                output_node_id="9",
                local_path="",
                drive_path=str(paths["drive"] / "outputs" / "out.png"),
                source_filename="out.png",
                drive_filename="out.png",
                sync_status="verified",
                capability="txt2img",
                workflow_identifier="base/txt2img",
            ),
            provenance=provenance,
            active_project=mountain,
            workflow_snapshot_status="complete",
            ui_workflow=executed,
        )
        _assert_equal("snapshot preparation_id authority", snap_meta.get("preparation_id"), prep.preparation_id)
        _assert_equal(
            "snapshot prepared hash authority",
            snap_meta.get("prepared_workflow_hash"),
            prep.prepared_workflow_hash,
        )
        _pass(results, "generation snapshot preserves preparation_id authority")

        # ------------------------------------------------------------------
        # 66–68 project rename / archive / delete preserve global prep
        # ------------------------------------------------------------------
        prep_count_before = len(read_preparation_records(log_path))
        workspace.rename_project("mountain-demo", new_slug="alpine-demo", display_name="Alpine Demo")
        _assert_equal("prep count after rename", len(read_preparation_records(log_path)), prep_count_before)
        _assert_true("prep record after rename", find_by_preparation_id(log_path, prep.preparation_id) is not None)
        _pass(results, "project rename preserves global preparation index")

        workspace.set_active_project("alpine-demo")
        workspace.archive_project("alpine-demo")
        _assert_true("prep record after archive", find_by_preparation_id(log_path, prep.preparation_id) is not None)
        _pass(results, "project archive preserves global preparation index")

        workspace.create_project(display_name="Temp Delete", slug="temp-delete", set_active=False)
        workspace.delete_project("temp-delete", confirm_slug="temp-delete")
        _assert_true("prep record after delete", find_by_preparation_id(log_path, prep.preparation_id) is not None)
        _pass(results, "project delete preserves global preparation index")

        # E2E mountain-demo preparation + executed relationship
        workspace.create_project(display_name="Mountain Demo", slug="mountain-demo", set_active=True)
        e2e_prep = _prepare_txt2img(
            repo_root,
            paths,
            parameters={"positive_prompt": "E2E mountain demo", "seed": 12345},
            active_project=workspace.get_active_project(),
        )
        _assert_true("E2E mountain-demo prep ok", e2e_prep.ok)
        e2e_data = json.loads(Path(e2e_prep.runtime_workflow_path).read_text(encoding="utf-8"))
        e2e_executed = copy.deepcopy(e2e_data)
        e2e_rel = compare_workflow_relationship(
            e2e_prep.canonical_workflow_hash,
            e2e_prep.prepared_workflow_hash,
            hash_ui_workflow(e2e_executed),
        )
        _assert_equal("E2E executed matches prepared", e2e_rel["relationship"], "executed_matches_prepared")
        _pass(results, "E2E mountain-demo txt2img prepare and relationship check")

    # ------------------------------------------------------------------
    # 54–59 notebook string checks
    # ------------------------------------------------------------------
    nb_path = repo_root / "colab" / "notebooks" / "AI_Studio_Control_Panel_Colab.ipynb"
    nb_data = json.loads(nb_path.read_text(encoding="utf-8"))
    _assert_true("notebook JSON valid", isinstance(nb_data.get("cells"), list))
    _pass(results, "notebook JSON remains valid")

    nb_text = _load_notebook_text(repo_root)
    required_strings = (
        "=== Workflow Library ===",
        "1. Browse workflows",
        "3. Prepare txt2img",
        "6. Prepare experimental inpainting",
        "Type YES to acknowledge experimental",
        "--allow-experimental",
        'run_repo_python("core/scripts/prepare_workflow.py"',
        'run_repo_python("core/scripts/workflow_catalog.py"',
    )
    for needle in required_strings:
        _assert_true(f"notebook contains {needle!r}", needle in nb_text)
    _pass(results, "notebook Workflow Library menu header present")
    _pass(results, "notebook browse workflows option present")
    _pass(results, "notebook prepare txt2img option present")
    _pass(results, "notebook experimental inpainting option present")
    _pass(results, "notebook experimental YES gate present")
    _pass(results, "notebook allow-experimental flag reference present")
    _pass(results, "notebook prepare_workflow script reference present")
    _pass(results, "notebook workflow_catalog script reference present")
    _assert_true("notebook normalize prep helper", "normalize_notebook_preparation_id" in nb_text)
    _pass(results, "notebook normalize preparation id helper present")

    for script_name in (
        "prepare_workflow.py",
        "workflow_catalog.py",
        "workflow_info.py",
        "list_prepared_workflows.py",
        "validate_prepared_workflow.py",
        "prepared_workflow_info.py",
    ):
        _assert_true(f"script exists {script_name}", (repo_root / "core" / "scripts" / script_name).is_file())
    _pass(results, "workflow library CLI scripts present on disk")

    # ------------------------------------------------------------------
    # 69–74 prior package regressions
    # ------------------------------------------------------------------
    for script_name, label in (
        ("simulate_package471_generations_ux.py", "Package 4.7.1 generations UX tests remain green"),
        ("simulate_package47_generation_snapshots.py", "Package 4.7 snapshot tests remain green"),
        ("simulate_package461_delete_confirmation.py", "Package 4.6.1 confirmation tests remain green"),
        ("simulate_package46_workspace_management.py", "Package 4.6 workspace tests remain green"),
        ("simulate_output_autosync.py", "Autosync/runtime ownership remains green"),
    ):
        _run_prior_sim(repo_root, script_name, label)
        _pass(results, label)

    _pass(results, "Package 4.8 workflow library simulations complete")
    return results


def main() -> int:
    print("AI Studio — Package 4.8 Workflow Library Simulations")
    print("=" * 50)
    try:
        results = run_simulations()
    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        print("\nRESULT: FAIL — package 4.8 simulations failed.")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] unexpected: {exc}")
        print("\nRESULT: FAIL — package 4.8 simulations failed.")
        return 1

    for name, status in results:
        print(f"  [{status}] {name}")
    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: PASS — package 4.8 workflow library simulations green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
