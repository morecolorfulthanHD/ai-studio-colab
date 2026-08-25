#!/usr/bin/env python3
"""Package 4.11.1 — JavaScript-safe seed precision simulations.

Proves AI Studio seeds stay within Number.MAX_SAFE_INTEGER so preparation →
ComfyUI browser JSON.parse → Run → snapshot cannot mutate the integer.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import uuid
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.comfyui_workflow_loading import build_comfyui_load_workflow
from core.runtime.generation_derivation import (
    build_default_variation_parameters,
    prepare_variation_from_generation,
)
from core.runtime.generation_evidence_ledger import EvidenceRecord, file_sha256
from core.runtime.generation_reproduction import (
    assess_reproduction_eligibility,
    prepare_from_generation,
)
from core.runtime.generation_snapshot import (
    METADATA_FILENAME,
    WORKFLOW_FILENAME,
    create_generation_snapshot,
    load_snapshot_by_id,
)
from core.runtime.png_utils import write_rgb_png
from core.runtime.registry_loader import find_repo_root
from core.runtime.seed_mode import (
    COMFYUI_FRONTEND_SAFE_INTEGER_MAX,
    COMFYUI_FRONTEND_VALUE_CONTROL_SOURCE,
    COMFYUI_KSAMPLER_SEED_RAW_MAX,
    MAX_SAFE_SEED,
    MIN_SAFE_SEED,
    SEED_PRECISION_ERROR,
    SEED_MODE_FIXED,
    SEED_MODE_RANDOMIZE,
    assert_verified_stock_randomize_contract,
    comfyui_frontend_randomize_int_bounds,
    generate_js_safe_seed,
    is_js_safe_seed,
    seed_precision_warning,
    simulate_comfyui_frontend_randomize_int,
    simulate_js_number_round_trip,
    validate_js_safe_seed,
)
from core.runtime.workflow_library_preparation import prepare_library_workflow
from core.runtime.workflow_manifest import load_workflow_manifest
from core.runtime.workflow_parameters import coerce_and_validate_parameters
from core.runtime.workflow_provenance import ExecutionProvenance


LIVE_FAILURE_SEED = 5353471740757167144
LIVE_BROWSER_MUTATED = 5353471740757167104
# Post-first-Run widget seed observed in live Package 4.11 Case A (pre-hotfix prep).
LIVE_CASE_A_POST_RUN_RANDOMIZED = 643903136860266

MODEL_FILES_PRESENT = {"sd15.safetensors": True}


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


def _assert_false(label: str, condition: bool) -> None:
    if condition:
        raise SimulationFailure(label)


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
        checkpoint.write_bytes(b"PK4111-SIM-MODEL-STUB")
    return {
        "drive": drive,
        "runtime_prepared": runtime / "prepared_workflows",
        "drive_prepared": drive / "workflows" / "prepared",
        "comfy_input": comfy_input,
        "comfy_root": root / "ComfyUI",
        "runtime": runtime,
    }


def _make_temp_repo(real_repo: Path, drive_root: Path, comfy_root: Path, runtime_root: Path) -> Path:
    temp_repo = Path(tempfile.mkdtemp(prefix="ai-studio-pkg4111-"))
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


def _mirror_workflows(real_repo: Path, temp_repo: Path) -> None:
    src = real_repo / "workflows"
    dst = temp_repo / "workflows"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _ksampler_seed(workflow: dict) -> int | None:
    for node in workflow.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "KSampler":
            widgets = node.get("widgets_values") or []
            if widgets:
                return int(widgets[0])
    return None


def _js_round_trip_workflow(workflow: dict) -> dict:
    """Simulate ComfyUI browser JSON.parse numeric coercion on a UI workflow."""
    text = json.dumps(workflow, ensure_ascii=False)
    parsed = json.loads(text)  # Python keeps ints; rewrite seeds via float64

    def _walk(obj):
        if isinstance(obj, dict):
            out = {}
            for key, value in obj.items():
                if key in {"seed"} and isinstance(value, int):
                    out[key] = simulate_js_number_round_trip(value)
                else:
                    out[key] = _walk(value)
            if obj.get("type") == "KSampler":
                widgets = out.get("widgets_values")
                if isinstance(widgets, list) and widgets and isinstance(widgets[0], int):
                    widgets = list(widgets)
                    widgets[0] = simulate_js_number_round_trip(widgets[0])
                    out["widgets_values"] = widgets
            return out
        if isinstance(obj, list):
            return [_walk(item) for item in obj]
        return obj

    return _walk(parsed)


def _txt2img_api(*, seed: int, positive: str = "seed precision mountain") -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd15.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["4", 1]}},
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
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "sim4111", "images": ["8", 0]}},
    }


def _create_source_generation(
    *,
    repo_root: Path,
    paths: dict[str, Path],
    seed: int,
    fill: tuple[int, int, int] = (11, 22, 33),
    suffix: str = "",
) -> dict:
    prep = prepare_library_workflow(
        repo_root,
        workflow_identifier="base/txt2img",
        parameters={
            "positive_prompt": "mountain cabin",
            "negative_prompt": "blurry",
            "seed": seed,
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
        dry_run=False,
        allowed_input_roots=[paths["drive"] / "inputs"],
        comfy_object_info=_comfy_object_info(load_workflow_manifest(repo_root, "base/txt2img")),
        model_files_present=MODEL_FILES_PRESENT,
    )
    _assert_true(f"source prep ok seed={seed}", prep.ok)
    prep_workflow = json.loads(Path(prep.runtime_workflow_path).read_text(encoding="utf-8"))
    out_name = f"sim4111_{seed}{suffix}.png"
    out_path = paths["drive"] / "outputs" / out_name
    _write_png(out_path, fill=fill)
    sha = file_sha256(out_path)
    prompt_id = str(uuid.uuid4())
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
        positive_prompt="mountain cabin",
        negative_prompt="blurry",
        seed=seed,
        steps=24,
        cfg=7.0,
        sampler_name="euler",
        scheduler="normal",
        width=512,
        height=768,
        workflow_identifier="base/txt2img",
        preparation_id=prep.preparation_id,
    )
    provenance = ExecutionProvenance(
        workflow_identifier="base/txt2img",
        capability="txt2img",
        model_family="sd15",
        model_files=["sd15.safetensors"],
        positive_prompt="mountain cabin",
        negative_prompt="blurry",
        seed=seed,
        steps=24,
        cfg=7.0,
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
        active_project=None,
        index_path=paths["drive"] / "logs" / "generation_index.jsonl",
        ui_workflow=prep_workflow,
        api_prompt=_txt2img_api(seed=seed),
        repo_root=repo_root,
    )
    _assert_true("snapshot ok", snap.ok)
    return {
        "generation_id": snap.generation_id,
        "seed": seed,
        "sha": sha,
        "prep_id": prep.preparation_id,
        "workflow": prep_workflow,
        "snapshot_root": str(snap.snapshot_root),
    }



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
    real_repo = find_repo_root(script_file=Path(__file__))
    print("Package 4.11.1 seed precision simulations")
    print("=" * 60)

    try:
        # 1. authoritative max safe seed
        _assert_equal("MAX_SAFE_SEED", MAX_SAFE_SEED, 9007199254740991)
        _assert_equal("MIN_SAFE_SEED", MIN_SAFE_SEED, 0)
        _assert_equal("2**53-1", (2**53) - 1, MAX_SAFE_SEED)
        _pass(results, "1 authoritative max safe seed")

        # Verified stock ComfyUI randomize compatibility (valueControl.ts)
        _assert_equal(
            "upstream SAFE_INTEGER_MAX",
            COMFYUI_FRONTEND_SAFE_INTEGER_MAX,
            1125899906842624,
        )
        _assert_equal("upstream SAFE_INTEGER_MAX is 2^50", COMFYUI_FRONTEND_SAFE_INTEGER_MAX, 2**50)
        rand_lo, rand_hi = comfyui_frontend_randomize_int_bounds()
        _assert_equal("KSampler randomize min", rand_lo, 0)
        _assert_equal("KSampler randomize max", rand_hi, COMFYUI_FRONTEND_SAFE_INTEGER_MAX - 1)
        _assert_true("native randomize max <= MAX_SAFE_SEED", rand_hi <= MAX_SAFE_SEED)
        assert_verified_stock_randomize_contract()
        _pass(results, "verified stock randomize bounds traced from valueControl.ts")

        # Mirror computeNextNumberValue randomize across representative random units.
        for unit in (0.0, 0.000001, 0.5, 0.999999, 1.0 - 1e-15):
            sample = simulate_comfyui_frontend_randomize_int(random_unit=unit)
            _assert_true(f"randomize sample {unit} in bounds", rand_lo <= sample <= rand_hi)
            _assert_true(f"randomize sample {unit} js-safe", is_js_safe_seed(sample))
            _assert_equal(
                f"randomize sample {unit} round-trip",
                simulate_js_number_round_trip(sample),
                sample,
            )
        edge_max = simulate_comfyui_frontend_randomize_int(random_unit=0.9999999999999999)
        _assert_equal("randomize near-1 output", edge_max, rand_hi)
        _pass(results, "native randomize outputs are exact JS integers")

        _assert_true(
            "live post-run randomized seed within native bounds",
            rand_lo <= LIVE_CASE_A_POST_RUN_RANDOMIZED <= rand_hi,
        )
        _assert_true(
            "live post-run randomized seed js-safe",
            is_js_safe_seed(LIVE_CASE_A_POST_RUN_RANDOMIZED),
        )
        _pass(results, "live Case A post-run randomized seed fits native bound")

        # Contract guard for the verified compatibility constants (static).
        _assert_true(
            "verified clamp constant within AI Studio contract",
            COMFYUI_FRONTEND_SAFE_INTEGER_MAX <= MAX_SAFE_SEED,
        )
        if COMFYUI_FRONTEND_SAFE_INTEGER_MAX > MAX_SAFE_SEED:
            raise SimulationFailure(
                f"verified constant from {COMFYUI_FRONTEND_VALUE_CONTROL_SOURCE} exceeds MAX_SAFE_SEED"
            )
        _pass(results, "verified stock randomize compatibility guard")

        # Live failure class: Python exact → JS Number mutation
        _assert_true("live seed above max", LIVE_FAILURE_SEED > MAX_SAFE_SEED)
        _assert_equal(
            "live JS mutation",
            simulate_js_number_round_trip(LIVE_FAILURE_SEED),
            LIVE_BROWSER_MUTATED,
        )
        _assert_true(
            "live seed not exact after JS",
            simulate_js_number_round_trip(LIVE_FAILURE_SEED) != LIVE_FAILURE_SEED,
        )
        _pass(results, "live Case A precision-loss class reproduced")

        # 2. generated variation seed <= max
        for _ in range(32):
            seed = generate_js_safe_seed()
            _assert_true("generated in range", is_js_safe_seed(seed))
            _assert_equal("generated JS round-trip", simulate_js_number_round_trip(seed), seed)
        params = build_default_variation_parameters(
            inherited={
                "positive_prompt": "x",
                "negative_prompt": "",
                "steps": 20,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "checkpoint": "sd15.safetensors",
            },
            generation_id="gen_00000000-0000-0000-0000-000000000001",
        )
        _assert_true("variation default seed safe", is_js_safe_seed(params["seed"]))
        _assert_equal("variation default seed_mode", params["seed_mode"], SEED_MODE_RANDOMIZE)
        _pass(results, "2 generated variation seed <= max")

        # 3–6. fixed/max accepted; 2^53 and live failure rejected
        ok_seed, ok_err = validate_js_safe_seed(424242)
        _assert_equal("fixed safe accepted", ok_seed, 424242)
        _assert_equal("fixed safe no error", ok_err, None)
        _pass(results, "3 fixed safe seed accepted")

        max_seed, max_err = validate_js_safe_seed(MAX_SAFE_SEED)
        _assert_equal("max accepted", max_seed, MAX_SAFE_SEED)
        _assert_equal("max no error", max_err, None)
        _assert_equal("max JS round-trip", simulate_js_number_round_trip(MAX_SAFE_SEED), MAX_SAFE_SEED)
        _pass(results, "4 max safe seed accepted")

        for bad, label in (
            (2**53, "2**53"),
            (2**53 + 1, "2**53+1"),
            (LIVE_FAILURE_SEED, "live-failure"),
            (-1, "negative"),
        ):
            got, err = validate_js_safe_seed(bad)
            _assert_equal(f"{label} rejected value", got, None)
            _assert_equal(f"{label} message", err, SEED_PRECISION_ERROR)
        _pass(results, "5 2^53 rejected")
        _pass(results, "6 larger live-failure seed rejected")

        # 7–8. no silent clamp / rounding
        before = LIVE_FAILURE_SEED
        got, err = validate_js_safe_seed(before)
        _assert_equal("no clamp return", got, None)
        _assert_equal("input unchanged", before, LIVE_FAILURE_SEED)
        _assert_true("error present", err == SEED_PRECISION_ERROR)
        _assert_false("not rounded to browser value", got == LIVE_BROWSER_MUTATED)
        _pass(results, "7 no silent clamp")
        _pass(results, "8 no silent rounding")

        with tempfile.TemporaryDirectory(prefix="pkg4111_") as tmp:
            root = Path(tmp)
            paths = _prep_paths(root)
            temp_repo = _make_temp_repo(real_repo, paths["drive"], paths["comfy_root"], paths["runtime"])
            try:
                txt_manifest = load_workflow_manifest(temp_repo, "base/txt2img")
                img_manifest = load_workflow_manifest(temp_repo, "base/img2img")
                txt_schema = txt_manifest.get("parameter_schema") or {}
                img_schema = img_manifest.get("parameter_schema") or {}
                txt_defaults = txt_manifest.get("default_parameters") or {}
                img_defaults = img_manifest.get("default_parameters") or {}

                # 9–10. txt2img / img2img validation consistent
                _assert_equal("txt2img max", txt_schema["seed"].get("maximum"), MAX_SAFE_SEED)
                _assert_equal("img2img max", img_schema["seed"].get("maximum"), MAX_SAFE_SEED)
                _assert_equal("txt2img min", txt_schema["seed"].get("minimum"), MIN_SAFE_SEED)
                _assert_equal("img2img min", img_schema["seed"].get("minimum"), MIN_SAFE_SEED)

                dummy_image = paths["drive"] / "inputs" / "seed_precision.png"
                _write_png(dummy_image, fill=(1, 2, 3))

                for name, schema, defaults, extra in (
                    ("txt2img", txt_schema, txt_defaults, {}),
                    (
                        "img2img",
                        img_schema,
                        img_defaults,
                        {"input_image": str(dummy_image)},
                    ),
                ):
                    base = {"positive_prompt": "ok", **extra}
                    params_ok, errors_ok = coerce_and_validate_parameters(
                        schema, defaults, {**base, "seed": 135791357}
                    )
                    _assert_equal(f"{name} safe errors", errors_ok, [])
                    _assert_equal(f"{name} safe seed", params_ok.get("seed"), 135791357)

                    params_max, errors_max = coerce_and_validate_parameters(
                        schema, defaults, {**base, "seed": MAX_SAFE_SEED}
                    )
                    _assert_equal(f"{name} max errors", errors_max, [])
                    _assert_equal(f"{name} max seed", params_max.get("seed"), MAX_SAFE_SEED)

                    params_bad, errors_bad = coerce_and_validate_parameters(
                        schema, defaults, {**base, "seed": LIVE_FAILURE_SEED}
                    )
                    _assert_true(
                        f"{name} rejects live seed",
                        SEED_PRECISION_ERROR in errors_bad,
                    )
                    _assert_equal(
                        f"{name} preserves raw rejected value",
                        params_bad.get("seed"),
                        LIVE_FAILURE_SEED,
                    )
                    _assert_false(
                        f"{name} did not clamp",
                        params_bad.get("seed") == MAX_SAFE_SEED,
                    )
                _pass(results, "9 txt2img validation consistent")
                _pass(results, "10 img2img validation consistent")

                # 11. randomize initial seed safe (ordinary prep)
                rand_prep = prepare_library_workflow(
                    temp_repo,
                    workflow_identifier="base/txt2img",
                    parameters={
                        "positive_prompt": "randomize safe",
                        "seed": generate_js_safe_seed(),
                        "seed_mode": SEED_MODE_RANDOMIZE,
                    },
                    runtime_prepared_root=paths["runtime_prepared"],
                    drive_prepared_root=paths["drive_prepared"],
                    comfyui_input_dir=paths["comfy_input"],
                    drive_root=paths["drive"],
                    dry_run=False,
                    allowed_input_roots=[paths["drive"] / "inputs"],
                    comfy_object_info=_comfy_object_info(txt_manifest),
                    model_files_present=MODEL_FILES_PRESENT,
                )
                _assert_true("randomize prep ok", rand_prep.ok)
                _assert_true("randomize seed safe", is_js_safe_seed(rand_prep.parameters.get("seed")))
                _assert_equal("randomize mode", rand_prep.parameters.get("seed_mode"), SEED_MODE_RANDOMIZE)
                _assert_equal(
                    "randomize control",
                    rand_prep.parameters.get("control_after_generate"),
                    "randomize",
                )
                _pass(results, "11 randomize initial seed safe")

                # 12. fixed seed survives preparation serialization + JS round-trip
                fixed_seed = 975318642
                fixed_prep = prepare_library_workflow(
                    temp_repo,
                    workflow_identifier="base/txt2img",
                    parameters={
                        "positive_prompt": "fixed exact",
                        "seed": fixed_seed,
                        "seed_mode": SEED_MODE_FIXED,
                    },
                    runtime_prepared_root=paths["runtime_prepared"],
                    drive_prepared_root=paths["drive_prepared"],
                    comfyui_input_dir=paths["comfy_input"],
                    drive_root=paths["drive"],
                    dry_run=False,
                    allowed_input_roots=[paths["drive"] / "inputs"],
                    comfy_object_info=_comfy_object_info(txt_manifest),
                    model_files_present=MODEL_FILES_PRESENT,
                )
                _assert_true("fixed prep ok", fixed_prep.ok)
                archived = json.loads(Path(fixed_prep.runtime_workflow_path).read_text(encoding="utf-8"))
                _assert_equal("archived ksampler seed", _ksampler_seed(archived), fixed_seed)
                load_copy = build_comfyui_load_workflow(archived)
                _assert_equal("load-copy seed", _ksampler_seed(load_copy), fixed_seed)
                py_round = json.loads(json.dumps(load_copy))
                _assert_equal("python json seed", _ksampler_seed(py_round), fixed_seed)
                js_round = _js_round_trip_workflow(load_copy)
                _assert_equal("js round-trip fixed seed", _ksampler_seed(js_round), fixed_seed)
                _pass(results, "12 fixed seed survives preparation serialization")

                for boundary in (0, 1, MAX_SAFE_SEED):
                    b_prep = prepare_library_workflow(
                        temp_repo,
                        workflow_identifier="base/txt2img",
                        parameters={
                            "positive_prompt": f"boundary {boundary}",
                            "seed": boundary,
                            "seed_mode": SEED_MODE_FIXED,
                        },
                        runtime_prepared_root=paths["runtime_prepared"],
                        drive_prepared_root=paths["drive_prepared"],
                        comfyui_input_dir=paths["comfy_input"],
                        drive_root=paths["drive"],
                        dry_run=False,
                        allowed_input_roots=[paths["drive"] / "inputs"],
                        comfy_object_info=_comfy_object_info(txt_manifest),
                        model_files_present=MODEL_FILES_PRESENT,
                    )
                    _assert_true(f"boundary {boundary} prep", b_prep.ok)
                    wf = json.loads(Path(b_prep.runtime_workflow_path).read_text(encoding="utf-8"))
                    _assert_equal(f"boundary {boundary} archived", _ksampler_seed(wf), boundary)
                    _assert_equal(
                        f"boundary {boundary} js",
                        _ksampler_seed(_js_round_trip_workflow(wf)),
                        boundary,
                    )
                _pass(results, "boundary seeds 0 / 1 / MAX_SAFE_SEED exact")

                bad_prep = prepare_library_workflow(
                    temp_repo,
                    workflow_identifier="base/txt2img",
                    parameters={
                        "positive_prompt": "too large",
                        "seed": LIVE_FAILURE_SEED,
                        "seed_mode": SEED_MODE_FIXED,
                    },
                    runtime_prepared_root=paths["runtime_prepared"],
                    drive_prepared_root=paths["drive_prepared"],
                    comfyui_input_dir=paths["comfy_input"],
                    drive_root=paths["drive"],
                    dry_run=False,
                    allowed_input_roots=[paths["drive"] / "inputs"],
                    comfy_object_info=_comfy_object_info(txt_manifest),
                    model_files_present=MODEL_FILES_PRESENT,
                )
                _assert_false("oversized prep rejected", bad_prep.ok)
                _assert_true(
                    "oversized error message",
                    any(SEED_PRECISION_ERROR in e for e in bad_prep.errors),
                )
                _pass(results, "manual seed above range fails cleanly")

                # 13. variation seed survives preparation serialization
                src = _create_source_generation(
                    repo_root=temp_repo, paths=paths, seed=135791357, suffix="_var"
                )
                var = prepare_variation_from_generation(
                    temp_repo,
                    generation_id=src["generation_id"],
                    runtime_prepared_root=paths["runtime_prepared"],
                    drive_prepared_root=paths["drive_prepared"],
                    comfyui_input_dir=paths["comfy_input"],
                    drive_root=paths["drive"],
                    use_global=True,
                    dry_run=False,
                    comfy_object_info=_comfy_object_info(img_manifest),
                    model_files_present=MODEL_FILES_PRESENT,
                )
                _assert_true("variation ok", var.ok)
                var_seed = int(var.parameters.get("seed"))
                _assert_true("variation seed safe", is_js_safe_seed(var_seed))
                var_wf = json.loads(Path(var.preparation.runtime_workflow_path).read_text(encoding="utf-8"))
                _assert_equal("variation archived seed", _ksampler_seed(var_wf), var_seed)
                _assert_equal(
                    "variation js round-trip",
                    _ksampler_seed(_js_round_trip_workflow(var_wf)),
                    var_seed,
                )
                var_bad = prepare_variation_from_generation(
                    temp_repo,
                    generation_id=src["generation_id"],
                    runtime_prepared_root=paths["runtime_prepared"],
                    drive_prepared_root=paths["drive_prepared"],
                    comfyui_input_dir=paths["comfy_input"],
                    drive_root=paths["drive"],
                    use_global=True,
                    dry_run=False,
                    parameter_overrides={"seed": LIVE_FAILURE_SEED, "seed_mode": "fixed"},
                    comfy_object_info=_comfy_object_info(img_manifest),
                    model_files_present=MODEL_FILES_PRESENT,
                )
                _assert_false("variation oversized rejected", var_bad.ok)
                _assert_true(
                    "variation oversized message",
                    any(SEED_PRECISION_ERROR in e for e in var_bad.errors),
                )
                _pass(results, "13 variation seed survives preparation serialization")

                # 14. reproduction safe-seed behavior unchanged
                repro = prepare_from_generation(
                    temp_repo,
                    generation_id=src["generation_id"],
                    runtime_prepared_root=paths["runtime_prepared"],
                    drive_prepared_root=paths["drive_prepared"],
                    comfyui_input_dir=paths["comfy_input"],
                    drive_root=paths["drive"],
                    use_global=True,
                    dry_run=False,
                    comfy_object_info=_comfy_object_info(txt_manifest),
                    model_files_present=MODEL_FILES_PRESENT,
                )
                _assert_true("reproduction ok", repro.ok)
                _assert_equal("reproduction seed", repro.parameters.get("seed"), 135791357)
                _assert_equal("reproduction seed_mode", repro.parameters.get("seed_mode"), SEED_MODE_FIXED)
                _pass(results, "14 reproduction safe-seed behavior unchanged")

                # Historical oversized metadata: display unchanged, reproduction refused, no rewrite
                hist_seed = LIVE_FAILURE_SEED
                hist = _create_source_generation(
                    repo_root=temp_repo,
                    paths=paths,
                    seed=111222333,
                    fill=(90, 91, 92),
                    suffix="_hist",
                )
                snap = load_snapshot_by_id(paths["drive"], hist["generation_id"])
                snap_root = Path(str(snap.get("snapshot_root") or ""))
                meta_path = snap_root / METADATA_FILENAME
                wf_path = snap_root / WORKFLOW_FILENAME
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                wf_payload = json.loads(wf_path.read_text(encoding="utf-8"))
                meta_before = copy.deepcopy(meta)
                meta["seed"] = hist_seed
                if isinstance(wf_payload.get("api_prompt"), dict):
                    k = wf_payload["api_prompt"].get("3") or {}
                    if isinstance(k.get("inputs"), dict):
                        k["inputs"]["seed"] = hist_seed
                ui = wf_payload.get("ui_workflow")
                if isinstance(ui, dict):
                    for node in ui.get("nodes") or []:
                        if isinstance(node, dict) and node.get("type") == "KSampler":
                            widgets = list(node.get("widgets_values") or [])
                            if widgets:
                                widgets[0] = hist_seed
                                node["widgets_values"] = widgets
                meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
                wf_path.write_text(json.dumps(wf_payload, indent=2) + "\n", encoding="utf-8")

                meta_after = json.loads(meta_path.read_text(encoding="utf-8"))
                _assert_equal("historical seed displayed", meta_after.get("seed"), hist_seed)
                _assert_true("historical warning", bool(seed_precision_warning(hist_seed)))
                elig = assess_reproduction_eligibility(
                    metadata=meta_after,
                    workflow_payload=wf_payload,
                    manifest=snap,
                )
                _assert_false("historical repro refused", elig.eligible)
                _assert_true(
                    "historical repro reason",
                    SEED_PRECISION_ERROR in elig.reason,
                )
                meta_still = json.loads(meta_path.read_text(encoding="utf-8"))
                _assert_equal("historical not rewritten", meta_still.get("seed"), hist_seed)
                _assert_true(
                    "only seed field changed from injection",
                    meta_before.get("seed") != hist_seed,
                )
                _pass(results, "15 historical metadata not rewritten")

                repro_bad = prepare_from_generation(
                    temp_repo,
                    generation_id=hist["generation_id"],
                    runtime_prepared_root=paths["runtime_prepared"],
                    drive_prepared_root=paths["drive_prepared"],
                    comfyui_input_dir=paths["comfy_input"],
                    drive_root=paths["drive"],
                    use_global=True,
                    dry_run=False,
                    comfy_object_info=_comfy_object_info(txt_manifest),
                    model_files_present=MODEL_FILES_PRESENT,
                )
                _assert_false("repro oversized fails", repro_bad.ok)
                _assert_true(
                    "repro oversized message",
                    any(SEED_PRECISION_ERROR in e for e in repro_bad.errors),
                )
                _pass(results, "reproduction refuses unsafe executed seed")

                # 16. normal user error has no traceback (CLI)
                cli = _run_cli(
                    real_repo,
                    temp_repo,
                    "prepare_workflow.py",
                    "--workflow",
                    "base/txt2img",
                    "--param",
                    "positive_prompt=too large seed",
                    "--param",
                    f"seed={LIVE_FAILURE_SEED}",
                    "--global",
                    "--dry-run",
                )
                combined = (cli.stdout or "") + (cli.stderr or "")
                _assert_true("cli nonzero", cli.returncode != 0)
                _assert_true("cli has seed message", SEED_PRECISION_ERROR in combined)
                _assert_false("cli no traceback", "Traceback (most recent call last)" in combined)
                _pass(results, "16 normal user error has no traceback")
            finally:
                shutil.rmtree(temp_repo, ignore_errors=True)

        # 0 / 1 / MAX accepted via validate
        for edge in (0, 1, MAX_SAFE_SEED):
            s, e = validate_js_safe_seed(edge)
            _assert_equal(f"edge {edge}", s, edge)
            _assert_equal(f"edge {edge} err", e, None)
        _pass(results, "edge accepts 0, 1, MAX_SAFE_SEED")

    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        results.append(("FAIL", str(exc)))
    except Exception as exc:  # noqa: BLE001 — surface unexpected sim crashes
        print(f"  [FAIL] unexpected: {exc}")
        traceback.print_exc()
        results.append(("FAIL", f"unexpected: {exc}"))

    passed = sum(1 for s, _ in results if s == "PASS")
    failed = sum(1 for s, _ in results if s == "FAIL")
    print("=" * 60)
    print(f"Package 4.11.1 seed precision: {passed} passed, {failed} failed, {len(results)} total")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
