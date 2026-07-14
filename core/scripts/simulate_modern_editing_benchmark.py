#!/usr/bin/env python3
"""Simulations for Package 4.4 modern editing benchmark scaffolding."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.editing_benchmark import (
    HUMAN_REVIEW_RUBRIC,
    EditingBenchmarkRecord,
    append_benchmark_record,
    empty_human_review_template,
    load_benchmark_records,
)
from core.runtime.modern_editing_preparation import prepare_modern_editing_workflow
from core.runtime.png_utils import write_rgb_png
from core.runtime.registry_loader import RegistryLoader, find_repo_root

_REPO_ROOT = find_repo_root(script_file=Path(__file__))


class SimulationFailure(Exception):
    pass


def _assert_equal(label, actual, expected):
    if actual != expected:
        raise SimulationFailure(f"{label}: expected {expected!r}, got {actual!r}")


def _assert_true(label, value):
    if not value:
        raise SimulationFailure(f"{label}: expected True")


def run_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    bundle = RegistryLoader(_REPO_ROOT).load_all()

    cap_ids = {cap.get("id") for cap in bundle.capabilities}
    _assert_true("qwen capability", "qwen_image_edit_benchmark" in cap_ids)
    _assert_true("flux capability", "flux_fill_benchmark" in cap_ids)
    qwen = next(c for c in bundle.capabilities if c["id"] == "qwen_image_edit_benchmark")
    flux = next(c for c in bundle.capabilities if c["id"] == "flux_fill_benchmark")
    _assert_equal("qwen not implemented default", qwen.get("implementation_status"), "benchmark")
    _assert_equal("flux not implemented default", flux.get("implementation_status"), "benchmark")
    results.append(("Benchmark capabilities registered without replacing production inpainting", "PASS"))

    qwen_wf = _REPO_ROOT / "workflows/reference/qwen_image_edit/workflow.json"
    flux_wf = _REPO_ROOT / "workflows/reference/flux_fill/workflow.json"
    qwen_prov = json.loads((_REPO_ROOT / "workflows/reference/qwen_image_edit/provenance.json").read_text(encoding="utf-8"))
    flux_prov = json.loads((_REPO_ROOT / "workflows/reference/flux_fill/provenance.json").read_text(encoding="utf-8"))
    _assert_equal("qwen hash", hashlib.sha256(qwen_wf.read_bytes()).hexdigest(), qwen_prov["extracted_workflow_json_sha256"])
    _assert_equal("flux hash", hashlib.sha256(flux_wf.read_bytes()).hexdigest(), flux_prov["extracted_workflow_json_sha256"])
    _assert_equal("qwen not reconstruction", qwen_prov.get("reconstruction"), False)
    _assert_equal("flux extracted", flux_prov.get("status"), "extracted_from_official_workflow_png")
    results.append(("Official reference provenance hashes match", "PASS"))

    license_doc = (_REPO_ROOT / "docs/model-compatibility-modern-editing.md").read_text(encoding="utf-8")
    _assert_true("apache noted", "Apache-2.0" in license_doc)
    _assert_true("flux noncommercial noted", "Non-Commercial" in license_doc)
    results.append(("License constraints documented", "PASS"))

    decision = (_REPO_ROOT / "docs/decisions/modern-editing-selection-gate.md").read_text(encoding="utf-8")
    _assert_true("selection gate open", "Deferred" in decision or "Open" in decision)
    results.append(("Selection gate does not promote new default yet", "PASS"))

    manifest = json.loads((_REPO_ROOT / "configs/benchmarks/modern_editing_benchmark.json").read_text(encoding="utf-8"))
    task_ids = {t["id"] for t in manifest["tasks"]}
    _assert_true("object removal task", "object_removal" in task_ids)
    _assert_true("object replacement task", "object_replacement" in task_ids)
    results.append(("Benchmark manifest tasks present", "PASS"))

    _assert_true("rubric completeness", len(HUMAN_REVIEW_RUBRIC) >= 7)
    template = empty_human_review_template()
    _assert_equal("rubric pending", template["instruction_adherence"], "pending_human_review")
    results.append(("Human review rubric without invented scores", "PASS"))

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        source = tmp / "source.png"
        rows = [[(120, 120, 120) for _ in range(16)] for _ in range(16)]
        write_rgb_png(source, 16, 16, rows)
        runtime = tmp / "runtime_workflows"
        comfy_in = tmp / "ComfyUI" / "input"
        before = hashlib.sha256(qwen_wf.read_bytes()).hexdigest()
        result = prepare_modern_editing_workflow(
            _REPO_ROOT,
            candidate="qwen_image_edit_benchmark",
            reference_relpath="workflows/reference/qwen_image_edit/workflow.json",
            required_models=["qwen_image_edit_2511_diffusion", "qwen_image_edit_text_encoder", "qwen_image_vae"],
            input_path=source,
            runtime_dir=runtime,
            comfyui_input_dir=comfy_in,
            positive_prompt="replace bicycle with wooden bench",
            require_models=False,
        )
        _assert_true("prep ok without models", result.ok)
        _assert_true("prepared written", Path(result.prepared_path).is_file())
        after = hashlib.sha256(qwen_wf.read_bytes()).hexdigest()
        _assert_equal("reference unchanged", before, after)
        prepared = json.loads(Path(result.prepared_path).read_text(encoding="utf-8"))
        load = next(n for n in prepared["nodes"] if n.get("type") == "LoadImage")
        _assert_equal("staged filename patched", load["widgets_values"][0], result.staged_input_filename)
        results.append(("Qwen prepare patches LoadImage and leaves reference intact", "PASS"))

        flux_before = hashlib.sha256(flux_wf.read_bytes()).hexdigest()
        flux_result = prepare_modern_editing_workflow(
            _REPO_ROOT,
            candidate="flux_fill_benchmark",
            reference_relpath="workflows/reference/flux_fill/workflow.json",
            required_models=["flux_fill_dev_diffusion", "flux_clip_l", "flux_t5xxl", "flux_ae_vae"],
            input_path=source,
            runtime_dir=runtime,
            comfyui_input_dir=comfy_in,
            positive_prompt="a wooden bench",
            require_models=False,
        )
        _assert_true("flux prep ok", flux_result.ok)
        _assert_equal("flux reference unchanged", flux_before, hashlib.sha256(flux_wf.read_bytes()).hexdigest())
        results.append(("FLUX prepare leaves extracted reference intact", "PASS"))

        ledger = tmp / "editing_benchmark.jsonl"
        record = EditingBenchmarkRecord(
            candidate_model="qwen_image_edit_2511",
            workflow="reference_qwen_image_edit",
            task="object_removal",
            prompt="remove the bicycle",
            success=True,
            human_review=empty_human_review_template(),
        )
        append_benchmark_record(ledger, record)
        rows = load_benchmark_records(ledger)
        _assert_equal("ledger rows", len(rows), 1)
        results.append(("Benchmark ledger append/read", "PASS"))

    # production inpainting still present
    inpaint = next(c for c in bundle.capabilities if c["id"] == "inpainting")
    _assert_equal("sd15 inpaint remains implemented", inpaint.get("implementation_status"), "implemented")
    results.append(("SD1.5 production inpainting capability retained", "PASS"))

    return results


def main() -> int:
    print("AI Studio — Package 4.4 Modern Editing Benchmark Simulations")
    print("=" * 50)
    try:
        results = run_simulations()
    except SimulationFailure as exc:
        print(f"[FAIL] {exc}")
        print("RESULT: FAIL")
        return 1
    for name, status in results:
        print(f"  [{status}] {name}")
    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: OK — modern editing benchmark simulations passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
