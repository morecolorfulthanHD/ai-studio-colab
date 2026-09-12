#!/usr/bin/env python3
"""Package 4.12.3 — InstantID identity architecture benchmark simulations."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.character_identity import register_character
from core.runtime.generation_derivation import assess_derivation_eligibility
from core.runtime.generation_reproduction import assess_reproduction_eligibility
from core.runtime.identity_architecture_benchmark import (
    ARCHITECTURE_SCENARIO_PROMPTS,
    ARCHITECTURE_STATUS,
    CANDIDATE_INSTANTID,
    PREPARATION_KIND,
    SCENARIO_DIMENSIONS,
    SECONDARY_CANDIDATE_PULID,
    SECONDARY_CANDIDATE_STATUS,
    IdentityArchitectureRecord,
    append_architecture_benchmark_record,
    architecture_ledger_path,
    architecture_status_for,
    assert_instantid_graph,
    is_identity_architecture_metadata,
    load_architecture_benchmark_records,
    prepare_identity_architecture_benchmark,
    restage_identity_architecture_benchmark_face,
)
from core.runtime.identity_benchmark import (
    PREPARATION_KIND_IDENTITY_BENCHMARK,
    SCENARIO_PROMPTS,
    is_benchmark_generation_metadata,
)
from core.runtime.identity_visual_qa import (
    evaluate_scenario_qa,
    image_integrity_gate,
    load_qa_config,
    reset_qa_test_hooks,
    set_qa_test_hooks,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.studio_timezone import get_studio_timezone_name, studio_date_stamp


def _pass(results: list[tuple[str, str]], label: str) -> None:
    results.append(("PASS", label))
    print(f"  [PASS] {label}")


def _assert_true(label: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {label}")


def _assert_equal(label: str, a: object, b: object) -> None:
    if a != b:
        raise AssertionError(f"FAIL: {label} ({a!r} != {b!r})")


def _make_synthetic_face(path: Path, *, yaw_hint: float = 0.0) -> None:
    from PIL import Image
    import numpy as np

    arr = np.full((256, 256, 3), 180, dtype=np.uint8)
    # Face oval
    cy, cx = 128, 128 + int(yaw_hint * 2)
    for y in range(256):
        for x in range(256):
            if ((x - cx) / 90) ** 2 + ((y - cy) / 110) ** 2 <= 1:
                arr[y, x] = (220, 190, 170)
    # Eyes
    arr[100:115, 95:125] = (40, 40, 40)
    arr[100:115, 155:185] = (40, 40, 40)
    # Mouth region — brighter for smile fixture
    if yaw_hint == 0.0:
        arr[170:190, 110:150] = (240, 240, 240)
    Image.fromarray(arr).save(path)


def main() -> int:
    results: list[tuple[str, str]] = []
    repo_root = find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()

    workflow_path = repo_root / "workflows/reference/identity_instantid_sdxl_benchmark/workflow.json"
    workflow_data = json.loads(workflow_path.read_text(encoding="utf-8"))
    graph_errors = assert_instantid_graph(workflow_data)
    _assert_true("InstantID graph structural assert", not graph_errors)
    _pass(results, "InstantID graph structural assert")

    _assert_equal(
        "reactor rejected",
        architecture_status_for("reactor_faceswap_benchmark"),
        "REJECTED_FOR_PRODUCTION_IDENTITY",
    )
    _assert_equal(
        "faceid rejected",
        architecture_status_for("ipadapter_faceid_sd15_benchmark"),
        "REJECTED_FOR_PRODUCTION_IDENTITY",
    )
    _assert_equal(
        "sweep failed",
        architecture_status_for("faceid_conditioning_sweep"),
        "FAILED_FIRST_SWEEP",
    )
    _assert_equal(
        "instantid investigation",
        architecture_status_for(CANDIDATE_INSTANTID),
        "INVESTIGATION",
    )
    _pass(results, "rejected architecture status constants")

    _assert_true(
        "S2 prompt differs from FaceID",
        ARCHITECTURE_SCENARIO_PROMPTS["S2_head_angle_pose"] != SCENARIO_PROMPTS["S2_head_angle_pose"],
    )
    _assert_true(
        "S3 prompt improved",
        "unmistakable genuine broad smile" in ARCHITECTURE_SCENARIO_PROMPTS["S3_expression_change"],
    )
    _assert_true(
        "S4 full-body prompt",
        "full-body environmental" in ARCHITECTURE_SCENARIO_PROMPTS["S4_wardrobe_environment"],
    )
    _pass(results, "architecture prompts differ from old FaceID where intended")

    _assert_equal("S1 dims", SCENARIO_DIMENSIONS["S1_near_front_portrait"], (1024, 1024))
    _assert_equal("S4 dims", SCENARIO_DIMENSIONS["S4_wardrobe_environment"], (1024, 768))
    _pass(results, "S1/S4 dimension binding")

    _assert_equal(
        "PuLID not selected",
        SECONDARY_CANDIDATE_STATUS,
        "investigated_not_selected",
    )
    _assert_equal("PuLID id documented", SECONDARY_CANDIDATE_PULID, "pulid_sdxl")
    _pass(results, "secondary candidate PuLID documented as not selected")

    # Pacific evening while UTC calendar already rolled forward (PDT UTC-7)
    pacific_evening_utc = datetime(2026, 9, 12, 2, 31, tzinfo=timezone.utc)
    stamp = studio_date_stamp(pacific_evening_utc)
    _assert_equal("studio timezone name default", get_studio_timezone_name(), "America/Los_Angeles")
    _assert_equal(
        "Pacific evening uses studio local date not UTC",
        stamp,
        "20260911",
    )
    _pass(results, "timezone studio date stamp Pacific evening UTC next day")

    tmp = Path(tempfile.mkdtemp(prefix="pkg4123_"))
    try:
        drive = tmp / "drive"
        runtime = tmp / "runtime"
        comfy = tmp / "comfy"
        for p in (drive, runtime, comfy / "input"):
            p.mkdir(parents=True)

        face_src = tmp / "face.png"
        _make_synthetic_face(face_src)
        reg = register_character(drive, display_name="Arch Persona", primary_face_image=face_src)
        _assert_true("character register", reg.ok and reg.character is not None)
        assert reg.character is not None

        prep = prepare_identity_architecture_benchmark(
            repo_root,
            drive_root=drive,
            scenario="S4",
            character_id=reg.character.character_id,
            runtime_prepared_root=runtime / "prepared_workflows",
            drive_prepared_root=drive / "workflows" / "prepared",
            comfyui_input_dir=comfy / "input",
            bundle_models=list(bundle.models),
            bundle_nodes=list(bundle.nodes),
            allow_benchmark=True,
            require_models=False,
            require_nodes=False,
        )
        _assert_true(f"prepare S4 ok ({prep.errors})", prep.ok)
        _assert_equal("S4 width", prep.width, 1024)
        _assert_equal("S4 height", prep.height, 768)
        meta_path = Path(prep.prepared_dir) / f"{prep.preparation_id}.metadata.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        _assert_equal("metadata kind", meta.get("preparation_kind"), PREPARATION_KIND)
        _assert_equal("metadata architecture", meta.get("architecture"), "instantid_sdxl")
        _assert_equal("metadata package", meta.get("package_version"), "4.12.3")
        _assert_equal("promotion pending", meta.get("promotion_status"), "pending")
        wf = json.loads(
            (Path(prep.prepared_dir) / f"{prep.preparation_id}.workflow.json").read_text(encoding="utf-8")
        )
        latent = next(
            n for n in wf["nodes"] if n.get("type") == "EmptyLatentImage" and str(n.get("id")) == "5"
        )
        _assert_equal("bound width", latent["widgets_values"][0], 1024)
        _assert_equal("bound height", latent["widgets_values"][1], 768)
        _pass(results, "prepare InstantID with fixtures (allow missing models)")

        bad_seed = prepare_identity_architecture_benchmark(
            repo_root,
            drive_root=drive,
            scenario="S1",
            character_id=reg.character.character_id,
            runtime_prepared_root=runtime / "prepared_workflows",
            comfyui_input_dir=comfy / "input",
            bundle_models=list(bundle.models),
            bundle_nodes=list(bundle.nodes),
            seed=9007199254740992,
            allow_benchmark=True,
            require_models=False,
            require_nodes=False,
        )
        _assert_true("unsafe seed refused", not bad_seed.ok)
        _pass(results, "unsafe seed refused")

        no_ack = prepare_identity_architecture_benchmark(
            repo_root,
            drive_root=drive,
            scenario="S1",
            character_id=reg.character.character_id,
            runtime_prepared_root=runtime / "prepared_workflows",
            comfyui_input_dir=comfy / "input",
            bundle_models=list(bundle.models),
            bundle_nodes=list(bundle.nodes),
            allow_benchmark=False,
            require_models=False,
            require_nodes=False,
        )
        _assert_true("missing allow_benchmark refused", not no_ack.ok)
        _pass(results, "missing allow_benchmark refused")

        msgs, errs = restage_identity_architecture_benchmark_face(
            prepared_dir=Path(prep.prepared_dir),
            metadata=meta,
            comfyui_input_dir=comfy / "input",
        )
        _assert_true("restage no errors", not errs)
        _assert_true("restage messages", bool(msgs))
        _pass(results, "restage identity architecture benchmark face")

        arch_meta = {
            "preparation_kind": PREPARATION_KIND,
            "benchmark_run": True,
            "capability": "identity_architecture_benchmark",
            "candidate": CANDIDATE_INSTANTID,
        }
        _assert_true("is architecture metadata", is_identity_architecture_metadata(arch_meta))
        _assert_true(
            "refuses ordinary parent via is_benchmark_generation_metadata",
            is_benchmark_generation_metadata(arch_meta),
        )
        deriv = assess_derivation_eligibility(metadata=arch_meta, manifest={})
        repro = assess_reproduction_eligibility(
            metadata=arch_meta, workflow_payload={}, manifest={}
        )
        _assert_true("derivation refused", not deriv.eligible)
        _assert_true("reproduction refused", not repro.eligible)
        _pass(results, "metadata refuses as ordinary parent")

        method_meta = {"preparation_kind": PREPARATION_KIND_IDENTITY_BENCHMARK}
        _assert_true(
            "method benchmark still isolated",
            is_benchmark_generation_metadata(method_meta)
            and not is_identity_architecture_metadata(method_meta),
        )

        ledger = architecture_ledger_path(drive)
        method_ledger = drive / "logs" / "identity_benchmark.jsonl"
        tuning_ledger = drive / "logs" / "identity_benchmark_tuning.jsonl"
        method_ledger.parent.mkdir(parents=True, exist_ok=True)
        method_ledger.write_text('{"candidate":"ipadapter_faceid_sd15_benchmark"}\n', encoding="utf-8")
        tuning_ledger.write_text('{"subtype":"faceid_conditioning_sweep"}\n', encoding="utf-8")
        append_architecture_benchmark_record(
            ledger,
            IdentityArchitectureRecord(
                candidate=CANDIDATE_INSTANTID,
                architecture="instantid_sdxl",
                scenario="S1_near_front_portrait",
                character_id=reg.character.character_id,
                preparation_id=prep.preparation_id,
            ),
        )
        arch_rows = load_architecture_benchmark_records(ledger)
        method_rows = [json.loads(l) for l in method_ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
        _assert_equal("architecture ledger count", len(arch_rows), 1)
        _assert_equal("method ledger untouched", len(method_rows), 1)
        _assert_true("ledgers separate files", ledger.name != method_ledger.name)
        _pass(results, "ledger isolation from identity_benchmark.jsonl and tuning")

        # Visual QA synthetic fixtures
        cfg = load_qa_config(repo_root)
        _assert_equal("qa calibration", cfg.get("calibration_status"), "uncalibrated")
        ref = tmp / "ref.png"
        frontal = tmp / "frontal.png"
        yaw_img = tmp / "yaw.png"
        smile_img = tmp / "smile.png"
        _make_synthetic_face(ref)
        _make_synthetic_face(frontal, yaw_hint=0.0)
        _make_synthetic_face(yaw_img, yaw_hint=35.0)
        _make_synthetic_face(smile_img, yaw_hint=0.0)

        set_qa_test_hooks(
            inject_embeddings=lambda p: [1.0, 0.0, 0.0] if "ref" in p or "frontal" in p else [0.99, 0.01, 0.0],
            inject_yaw=lambda p: 5.0 if "frontal" in p else (40.0 if "yaw" in p else 0.0),
            inject_smile=lambda p: (0.1, 0.05) if "frontal" in p else (0.8, 0.7),
        )
        integ = image_integrity_gate(frontal, expected_width=256, expected_height=256)
        _assert_equal("integrity pass", integ.get("image_integrity_gate"), "pass")

        s2_front = evaluate_scenario_qa("S2_head_angle_pose", ref, frontal, cfg)
        _assert_equal("near-front fails S2 gate", s2_front.get("scenario_adherence_gate"), "fail")

        s2_yaw = evaluate_scenario_qa("S2_head_angle_pose", ref, yaw_img, cfg)
        _assert_equal("yaw fixture passes S2 gate", s2_yaw.get("scenario_adherence_gate"), "pass")

        s3_neutral = evaluate_scenario_qa("S3_expression_change", ref, frontal, cfg)
        _assert_equal("neutral fails S3", s3_neutral.get("scenario_adherence_gate"), "fail")

        set_qa_test_hooks(
            inject_embeddings=lambda p: None,
            inject_yaw=lambda p: None,
            inject_smile=lambda p: None,
        )
        no_face = evaluate_scenario_qa("S2_head_angle_pose", ref, tmp / "missing.png", cfg)
        _assert_equal("no-face integrity fail", no_face.get("image_integrity_gate"), "fail")
        reset_qa_test_hooks()
        _pass(results, "visual QA synthetic fixtures and gates")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    passed = sum(1 for status, _ in results if status == "PASS")
    print(f"RESULT: {passed}/{len(results)} Package 4.12.3 simulations passed.")
    failed = [label for status, label in results if status != "PASS"]
    if failed:
        print("FAILED:", "; ".join(failed), file=sys.stderr)
        return 1
    print("NOTE: Simulations do NOT quality-benchmark InstantID SDXL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
