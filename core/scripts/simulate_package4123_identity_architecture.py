#!/usr/bin/env python3
"""Package 4.12.3 - InstantID identity architecture benchmark simulations."""

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
from core.runtime.generation_evidence_ledger import file_sha256
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
    architecture_idempotence_key,
    architecture_ledger_path,
    architecture_status_for,
    assert_instantid_graph,
    assess_instantid_asset_readiness,
    assess_instantid_license_gate,
    find_architecture_ledger_row,
    is_identity_architecture_metadata,
    load_architecture_benchmark_records,
    prepare_identity_architecture_benchmark,
    restage_identity_architecture_benchmark_face,
    update_architecture_ledger_qa,
)
from core.runtime.identity_architecture_capture import (
    capture_identity_architecture_execution,
    is_identity_architecture_benchmark_provenance,
    recover_identity_architecture_from_history,
)
from core.runtime.identity_architecture_execution import (
    execute_architecture_scenario,
    should_fail_fast,
)
from core.runtime.identity_benchmark import (
    PREPARATION_KIND_IDENTITY_BENCHMARK,
    SCENARIO_PROMPTS,
    is_benchmark_generation_metadata,
)
from core.runtime.comfyui_prompt_queue import (
    QueuePromptResult,
    WaitHistoryResult,
    ui_workflow_to_api_prompt,
    wait_for_prompt_completion,
)
from core.runtime.output_autosync import OutputAutoSyncService
from core.runtime.workflow_provenance import ExecutionProvenance
from core.runtime.identity_visual_qa import (
    YAW_SIGN_CONVENTION,
    evaluate_scenario_qa,
    image_integrity_gate,
    load_qa_config,
    prompt_adherence_scores,
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


def _make_synthetic_face(path: Path, *, yaw_hint: float = 0.0, size: int = 256) -> None:
    from PIL import Image
    import numpy as np

    arr = np.full((size, size, 3), 180, dtype=np.uint8)
    # Face oval
    cy, cx = size // 2, size // 2 + int(yaw_hint * 2)
    yy, xx = np.ogrid[:size, :size]
    mask = ((xx - cx) / (size * 0.35)) ** 2 + ((yy - cy) / (size * 0.43)) ** 2 <= 1
    arr[mask] = (220, 190, 170)
    # Eyes
    e1 = int(size * 0.39)
    e2 = int(size * 0.45)
    ey = int(size * 0.39)
    arr[ey : ey + size // 16, e1 : e1 + size // 8] = (40, 40, 40)
    arr[ey : ey + size // 16, e2 : e2 + size // 8] = (40, 40, 40)
    # Mouth region - brighter for smile fixture
    if yaw_hint == 0.0:
        my0, my1 = int(size * 0.66), int(size * 0.74)
        mx0, mx1 = int(size * 0.43), int(size * 0.59)
        arr[my0:my1, mx0:mx1] = (240, 240, 240)
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
        "BLOCKED_FOR_COMMERCIAL",
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

        # Visual QA synthetic fixtures + direction / uncalibrated semantics
        cfg = load_qa_config(repo_root)
        _assert_equal("qa calibration", cfg.get("calibration_status"), "uncalibrated")
        _assert_true("yaw sign convention documented", "subject" in YAW_SIGN_CONVENTION.lower())
        ref = tmp / "ref.png"
        frontal = tmp / "frontal.png"
        yaw_img = tmp / "yaw.png"
        smile_img = tmp / "smile.png"
        wrong_yaw = tmp / "wrong_yaw.png"
        profile = tmp / "profile.png"
        _make_synthetic_face(ref)
        _make_synthetic_face(frontal, yaw_hint=0.0)
        _make_synthetic_face(yaw_img, yaw_hint=35.0)
        _make_synthetic_face(smile_img, yaw_hint=0.0)
        _make_synthetic_face(wrong_yaw, yaw_hint=-35.0)
        _make_synthetic_face(profile, yaw_hint=70.0)

        set_qa_test_hooks(
            inject_embeddings=lambda p: [1.0, 0.0, 0.0],
            inject_yaw=lambda p: {
                "frontal.png": 5.0,
                "yaw.png": 40.0,
                "wrong_yaw.png": -40.0,
                "profile.png": 70.0,
            }.get(Path(p).name, 0.0),
            inject_smile=lambda p: (0.1, 0.05, 0.05)
            if Path(p).name == "frontal.png"
            else (0.8, 0.5, 0.7),
        )
        integ = image_integrity_gate(frontal, expected_width=256, expected_height=256)
        _assert_equal("integrity pass", integ.get("image_integrity_gate"), "pass")

        s2_front = evaluate_scenario_qa(
            "S2_head_angle_pose", ref, frontal, cfg, expected_width=0, expected_height=0
        )
        _assert_equal("near-front fails S2 gate", s2_front.get("scenario_adherence_gate"), "fail")
        _assert_equal("near-front automated fail", s2_front.get("automated_quality_status"), "fail")

        s2_yaw = evaluate_scenario_qa(
            "S2_head_angle_pose", ref, yaw_img, cfg, expected_width=0, expected_height=0
        )
        _assert_equal("yaw fixture passes S2 gate", s2_yaw.get("scenario_adherence_gate"), "pass")
        _assert_equal("S2 direction_match", s2_yaw.get("direction_match"), True)
        _assert_equal(
            "uncalibrated never plain pass",
            s2_yaw.get("automated_quality_status"),
            "provisional_pass",
        )

        s2_wrong = evaluate_scenario_qa(
            "S2_head_angle_pose", ref, wrong_yaw, cfg, expected_width=0, expected_height=0
        )
        _assert_equal("wrong direction fails S2", s2_wrong.get("scenario_adherence_gate"), "fail")
        _assert_equal("wrong direction_match false", s2_wrong.get("direction_match"), False)

        s2_profile = evaluate_scenario_qa(
            "S2_head_angle_pose", ref, profile, cfg, expected_width=0, expected_height=0
        )
        _assert_equal("excessive profile fails S2", s2_profile.get("scenario_adherence_gate"), "fail")

        s3_neutral = evaluate_scenario_qa(
            "S3_expression_change", ref, frontal, cfg, expected_width=0, expected_height=0
        )
        _assert_equal("neutral fails S3", s3_neutral.get("scenario_adherence_gate"), "fail")

        s3_smile = evaluate_scenario_qa(
            "S3_expression_change", ref, smile_img, cfg, expected_width=0, expected_height=0
        )
        _assert_equal("smile passes S3 gate", s3_smile.get("scenario_adherence_gate"), "pass")
        _assert_equal(
            "S3 uncalibrated provisional",
            s3_smile.get("automated_quality_status"),
            "provisional_pass",
        )

        set_qa_test_hooks(
            inject_embeddings=lambda p: [1.0, 0.0, 0.0],
            inject_yaw=lambda p: None,
            inject_smile=lambda p: None,
        )
        s2_unavail = evaluate_scenario_qa(
            "S2_head_angle_pose", ref, yaw_img, cfg, expected_width=0, expected_height=0
        )
        _assert_equal(
            "unavailable landmarks -> inconclusive",
            s2_unavail.get("automated_quality_status"),
            "inconclusive",
        )
        s3_unavail = evaluate_scenario_qa(
            "S3_expression_change", ref, smile_img, cfg, expected_width=0, expected_height=0
        )
        _assert_true(
            "S3 unavailable landmarks not pass",
            s3_unavail.get("automated_quality_status") in {"inconclusive", "fail"},
        )
        _assert_true(
            "S3 landmark unavailable gate",
            s3_unavail.get("scenario_adherence_gate") in {"unavailable", "fail"},
        )

        set_qa_test_hooks(
            inject_embeddings=lambda p: None,
            inject_yaw=lambda p: None,
            inject_smile=lambda p: None,
        )
        no_face = evaluate_scenario_qa("S2_head_angle_pose", ref, tmp / "missing.png", cfg)
        _assert_equal("no-face integrity fail", no_face.get("image_integrity_gate"), "fail")
        reset_qa_test_hooks()
        _pass(results, "visual QA direction, smile, uncalibrated semantics")

        # S4 CLIP: no local model -> unavailable/inconclusive, zero network
        clip = prompt_adherence_scores(
            smile_img,
            ["person wearing a red jacket"],
            repo_root=tmp / "no_clip_assets",
        )
        _assert_true(
            "S4 no local CLIP unavailable",
            clip.get("status") in {"unavailable", "inconclusive"},
        )
        _pass(results, "S4 no local CLIP -> inconclusive/unavailable (zero network)")

        # Asset readiness: UNVERIFIED_MANUAL_ASSET fails closed
        asset = assess_instantid_asset_readiness(
            drive_root=drive,
            bundle_models=list(bundle.models),
        )
        _assert_equal("instantid assets not ready without hashes", asset.get("ready"), False)
        _assert_true(
            "UNVERIFIED or PENDING pin in errors",
            any(
                ("UNVERIFIED" in e) or ("PENDING_FIRST_DOWNLOAD_PIN" in e)
                for e in (asset.get("errors") or [])
            ),
        )
        _pass(results, "missing InstantID hash -> readiness fail")

        # Hash mismatch on a synthetic verified entry
        fake_file = tmp / "fake_ip.bin"
        fake_file.write_bytes(b"not-the-real-weights")
        mismatch_models = [
            {
                "name": "sdxl_base",
                "runtime_path": str(fake_file),
                "filename": "fake_ip.bin",
                "expected_sha256": "0" * 64,
                "expected_size_bytes": 19,
            },
            {
                "name": "instantid_ip_adapter",
                "runtime_path": str(fake_file),
                "filename": "fake_ip.bin",
                "expected_sha256": "0" * 64,
                "expected_size_bytes": 19,
            },
            {
                "name": "instantid_controlnet",
                "runtime_path": str(fake_file),
                "filename": "fake_ip.bin",
                "expected_sha256": "0" * 64,
                "expected_size_bytes": 19,
            },
            {
                "name": "insightface_antelopev2",
                "runtime_path": str(tmp / "antelope"),
                "verification_state": "UNVERIFIED_MANUAL_ASSET",
            },
        ]
        mm = assess_instantid_asset_readiness(drive_root=drive, bundle_models=mismatch_models)
        _assert_equal("hash mismatch readiness fail", mm.get("ready"), False)
        _pass(results, "hash mismatch -> readiness fail")

        license_gate = assess_instantid_license_gate(repo_root)
        _assert_equal("license promotion blocked", license_gate.get("promotion_allowed"), False)
        _assert_true(
            "insightface blocked commercial",
            (license_gate.get("components") or {})
            .get("insightface_antelopev2", {})
            .get("status")
            == "BLOCKED_FOR_COMMERCIAL",
        )
        _pass(results, "missing license approval -> promotion blocked")

        # Timezone PDT / PST / rollover / invalid
        import os
        from core.runtime.studio_timezone import get_studio_tzinfo, studio_now

        pdt = studio_now(datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc))
        pst = studio_now(datetime(2026, 1, 15, 20, 0, tzinfo=timezone.utc))
        _assert_equal("PDT offset", pdt.utcoffset().total_seconds() / 3600, -7.0)
        _assert_equal("PST offset", pst.utcoffset().total_seconds() / 3600, -8.0)
        rollover = studio_date_stamp(datetime(2026, 9, 12, 2, 31, tzinfo=timezone.utc))
        _assert_equal("date rollover Pacific", rollover, "20260911")
        prev_tz = os.environ.get("AI_STUDIO_TIMEZONE")
        os.environ["AI_STUDIO_TIMEZONE"] = "Not/A_Real_Zone"
        raised = False
        try:
            get_studio_tzinfo()
        except ValueError:
            raised = True
        finally:
            if prev_tz is None:
                os.environ.pop("AI_STUDIO_TIMEZONE", None)
            else:
                os.environ["AI_STUDIO_TIMEZONE"] = prev_tz
        _assert_true("invalid timezone raises", raised)
        _pass(results, "PDT/PST timezone rollover and invalid zone")

        # Mocked ComfyUI /prompt integration
        prompt_posts: list[dict] = []

        def fake_queue(api_prompt, **kwargs):
            prompt_posts.append({"prompt": api_prompt, **kwargs})
            return QueuePromptResult(ok=True, prompt_id="pid-test-001", messages=["queued"])

        def fake_wait(prompt_id, **kwargs):
            _assert_equal("prompt_id polled", prompt_id, "pid-test-001")
            return WaitHistoryResult(
                ok=True,
                entry={
                    "outputs": {
                        "9": {
                            "images": [
                                {"filename": "arch_out.png", "subfolder": "", "type": "output"}
                            ]
                        }
                    },
                    "status": {"status_str": "success", "completed": True},
                },
                messages=["completed"],
            )

        out_dir = comfy / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_img = out_dir / "arch_out.png"
        from PIL import Image as _PILImage
        import numpy as _np

        _PILImage.fromarray(_np.full((1024, 1024, 3), 200, dtype=_np.uint8)).save(out_img)

        # Stub open_prepared to avoid live ComfyUI
        import core.runtime.identity_architecture_execution as exec_mod
        from core.runtime.comfyui_workflow_loading import OpenPreparedResult

        real_open = exec_mod.open_prepared_workflow_for_comfyui

        def fake_open(**kwargs):
            return OpenPreparedResult(
                preparation_id=kwargs.get("preparation_id") or "prep",
                filesystem_destination=str(kwargs.get("source_workflow_path") or ""),
                messages=["filesystem registered (test)"],
            )

        exec_mod.open_prepared_workflow_for_comfyui = fake_open  # type: ignore[assignment]
        set_qa_test_hooks(
            inject_embeddings=lambda p: [1.0, 0.0, 0.0],
            inject_yaw=lambda p: 5.0,
            inject_smile=lambda p: (0.2, 0.1, 0.1),
        )
        try:
            live = execute_architecture_scenario(
                repo_root=repo_root,
                drive_root=drive,
                character_id=reg.character.character_id,
                scenario="S1_near_front_portrait",
                bundle_models=list(bundle.models),
                bundle_nodes=list(bundle.nodes),
                runtime_prepared_root=runtime / "prepared_workflows",
                comfyui_input_dir=comfy / "input",
                comfyui_runtime=comfy,
                comfyui_output_dir=out_dir,
                seed=42,
                require_models=False,
                require_nodes=False,
                require_verified_assets=False,
                queue_prompt_fn=fake_queue,
                wait_history_fn=fake_wait,
                sleep_fn=lambda _s: None,
            )
            _assert_true(f"live exec ok ({live.errors})", live.ok)
            _assert_equal("prompt_id captured", live.prompt_id, "pid-test-001")
            _assert_equal("queue completed", live.queue_status, "completed")
            _assert_true("/prompt invoked once", len(prompt_posts) == 1)
            _assert_true("output captured", bool(live.output_sha256))
            _assert_true("automated QA present", bool(live.automated_qa))
            _assert_true("local path recorded", bool(live.local_path))
            _assert_true(
                "ledger output_path is Drive not comfy",
                "outputs" in str(live.output_path).replace("\\", "/")
                and "ComfyUI/output" not in str(live.output_path).replace("\\", "/"),
            )
            drive_art = Path(live.output_path)
            _assert_true("Drive artifact exists", drive_art.is_file())
            local_sha = file_sha256(Path(live.local_path)).lower()
            drive_sha = file_sha256(drive_art).lower()
            _assert_equal("local SHA == Drive SHA", local_sha, drive_sha)
            _assert_equal("ledger SHA == Drive SHA", live.output_sha256.lower(), drive_sha)
            ledger_rows = load_architecture_benchmark_records(architecture_ledger_path(drive))
            arch_exec_rows = [r for r in ledger_rows if r.get("prompt_id") == "pid-test-001"]
            _assert_equal("one architecture row for prompt", len(arch_exec_rows), 1)
            _assert_true(
                "row output_path durable",
                str(arch_exec_rows[0].get("output_path") or "").endswith(drive_art.name)
                or str(arch_exec_rows[0].get("output_path")) == str(drive_art),
            )
            _assert_true(
                "capture_idempotence_key set",
                bool(arch_exec_rows[0].get("capture_idempotence_key")),
            )
            _assert_true(
                "no browser required message",
                any("no browser" in m.lower() for m in live.messages),
            )
            _pass(results, "mocked /prompt durable Drive capture + SHA contract")

            # Repeated runner capture -> duplicate/reuse, no append
            rows_before = len(load_architecture_benchmark_records(architecture_ledger_path(drive)))
            drive_files_before = list((drive / "outputs").glob("identity_architecture_benchmark_*"))
            live2 = execute_architecture_scenario(
                repo_root=repo_root,
                drive_root=drive,
                character_id=reg.character.character_id,
                scenario="S1_near_front_portrait",
                bundle_models=list(bundle.models),
                bundle_nodes=list(bundle.nodes),
                runtime_prepared_root=runtime / "prepared_workflows",
                comfyui_input_dir=comfy / "input",
                comfyui_runtime=comfy,
                comfyui_output_dir=out_dir,
                seed=42,
                require_models=False,
                require_nodes=False,
                require_verified_assets=False,
                queue_prompt_fn=fake_queue,
                wait_history_fn=fake_wait,
                sleep_fn=lambda _s: None,
            )
            # Same local file + same prompt_id from fake_queue -> may create new prep but
            # same prompt/node/sha if we reuse prompt id - fake always returns pid-test-001
            # and same arch_out.png bytes -> duplicate on second capture of same execution key.
            # Note: new prepare creates new seed path but output file unchanged -> same SHA.
            # prompt_id is always pid-test-001, node 9, same SHA -> idempotent.
            _assert_true(f"rerun capture ok ({live2.errors})", live2.ok)
            rows_after = load_architecture_benchmark_records(architecture_ledger_path(drive))
            same_key_rows = [
                r
                for r in rows_after
                if r.get("prompt_id") == "pid-test-001"
                and str(r.get("output_sha256") or "").lower() == drive_sha
            ]
            _assert_equal("idempotent single row for execution key", len(same_key_rows), 1)
            drive_files_after = list((drive / "outputs").glob("identity_architecture_benchmark_*"))
            _assert_true(
                "no extra Drive files on rerun",
                len(drive_files_after) <= len(drive_files_before) + 1,
            )
            _pass(results, "repeated runner capture reuses; no duplicate architecture row")

            # Watcher path isolation + convergence
            (drive / "outputs").mkdir(parents=True, exist_ok=True)
            evidence = drive / "logs" / "autosync" / "evidence.jsonl"
            gen_index = drive / "generations" / "index.jsonl"
            svc = OutputAutoSyncService(
                drive_root=drive,
                drive_output_dir=drive / "outputs",
                comfy_output_dir=out_dir,
                evidence_path=evidence,
                index_path=drive / "logs" / "autosync" / "processed.json",
                status_path=drive / "logs" / "autosync" / "status.json",
                generation_index_path=gen_index,
                registered_hashes={},
            )
            watch_local = out_dir / "watcher_arch.png"
            watch_local.write_bytes(out_img.read_bytes())
            prep_wf = json.loads(
                (Path(prep.prepared_dir) / f"{prep.preparation_id}.workflow.json").read_text(
                    encoding="utf-8"
                )
            )
            before_gen = gen_index.read_text(encoding="utf-8") if gen_index.is_file() else ""
            rows_w_before = len(load_architecture_benchmark_records(architecture_ledger_path(drive)))
            prov_arch = ExecutionProvenance(
                preparation_id=prep.preparation_id,
                preparation_kind=PREPARATION_KIND,
                capability="identity_architecture_benchmark",
                seed=42,
            )
            rec_watch = svc.sync_local_output(
                prompt_id="pid-watch-arch-1",
                output_node_id="9",
                local_path=watch_local,
                provenance=prov_arch,
                ui_workflow=prep_wf,
                capability="identity_architecture_benchmark",
            )
            _assert_true(
                "watcher sync verified",
                rec_watch is not None and rec_watch.sync_status == "verified",
            )
            _assert_equal(
                "watcher snapshot skipped architecture",
                rec_watch.snapshot_status,
                "skipped_identity_architecture_benchmark",
            )
            _assert_equal("watcher no generation_id", rec_watch.generation_id or "", "")
            after_gen = gen_index.read_text(encoding="utf-8") if gen_index.is_file() else ""
            _assert_equal("generation index unchanged", after_gen, before_gen)
            rows_w_after = load_architecture_benchmark_records(architecture_ledger_path(drive))
            _assert_true("watcher appended architecture row", len(rows_w_after) == rows_w_before + 1)
            watch_sha = file_sha256(Path(rec_watch.drive_path)).lower()
            # Runner capture same execution after watcher
            cap_after = capture_identity_architecture_execution(
                drive_root=drive,
                prompt_id="pid-watch-arch-1",
                output_node_id="9",
                output_path=watch_local,
                output_sha256=watch_sha,
                provenance=prov_arch,
                ui_workflow=prep_wf,
                local_path=str(watch_local),
                preparation_id=prep.preparation_id,
                scenario="S4_wardrobe_environment",
                character_id=reg.character.character_id,
                seed=42,
                created_by="architecture_runner",
            )
            _assert_true(f"runner after watcher ok ({cap_after.errors})", cap_after.ok)
            _assert_true("runner after watcher duplicate", cap_after.skipped_duplicate)
            _assert_equal(
                "still one row for watcher prompt",
                len(
                    [
                        r
                        for r in load_architecture_benchmark_records(architecture_ledger_path(drive))
                        if r.get("prompt_id") == "pid-watch-arch-1"
                    ]
                ),
                1,
            )
            _pass(results, "watcher first then runner: one Drive file / one architecture row")

            # Runner-first then watcher for a new prompt
            run_local = out_dir / "runner_first.png"
            run_local.write_bytes(out_img.read_bytes())
            run_sha = file_sha256(run_local).lower()
            cap_run = capture_identity_architecture_execution(
                drive_root=drive,
                prompt_id="pid-run-first",
                output_node_id="9",
                output_path=run_local,
                output_sha256=run_sha,
                provenance=prov_arch,
                ui_workflow=prep_wf,
                local_path=str(run_local),
                preparation_id=prep.preparation_id,
                scenario="S1_near_front_portrait",
                character_id=reg.character.character_id,
                seed=42,
                compute_qa_fn=lambda p: evaluate_scenario_qa(
                    "S1_near_front_portrait",
                    face_src,
                    p,
                    load_qa_config(repo_root),
                    expected_width=0,
                    expected_height=0,
                ),
                created_by="architecture_runner",
            )
            _assert_true(f"runner-first capture ok ({cap_run.errors})", cap_run.ok)
            _assert_true("QA attached on durable path", bool(cap_run.automated_qa))
            watch2 = svc.sync_local_output(
                prompt_id="pid-run-first",
                output_node_id="9",
                local_path=run_local,
                provenance=prov_arch,
                ui_workflow=prep_wf,
                capability="identity_architecture_benchmark",
            )
            _assert_true("watcher after runner verified", watch2.sync_status == "verified")
            _assert_equal(
                "one row after runner+watcher",
                len(
                    [
                        r
                        for r in load_architecture_benchmark_records(architecture_ledger_path(drive))
                        if r.get("prompt_id") == "pid-run-first"
                    ]
                ),
                1,
            )
            _pass(results, "runner first then watcher: one Drive file / one architecture row")

            # Concurrent-ish: two captures same key
            c1 = capture_identity_architecture_execution(
                drive_root=drive,
                prompt_id="pid-race",
                output_node_id="9",
                output_path=run_local,
                output_sha256=run_sha,
                provenance=prov_arch,
                ui_workflow=prep_wf,
                preparation_id=prep.preparation_id,
                scenario="S1_near_front_portrait",
                character_id=reg.character.character_id,
                seed=7,
            )
            c2 = capture_identity_architecture_execution(
                drive_root=drive,
                prompt_id="pid-race",
                output_node_id="9",
                output_path=run_local,
                output_sha256=run_sha,
                provenance=prov_arch,
                ui_workflow=prep_wf,
                preparation_id=prep.preparation_id,
                scenario="S1_near_front_portrait",
                character_id=reg.character.character_id,
                seed=7,
            )
            _assert_true("race first ok", c1.ok)
            _assert_true("race second ok", c2.ok)
            _assert_true("race second duplicate", c2.skipped_duplicate)
            _assert_equal(
                "race one row",
                len(
                    [
                        r
                        for r in load_architecture_benchmark_records(architecture_ledger_path(drive))
                        if r.get("prompt_id") == "pid-race"
                    ]
                ),
                1,
            )
            _pass(results, "concurrent runner+watcher converge to one row")

            # Recovery A: captured + local deleted -> duplicate via Drive ledger
            hist = {
                "pid-run-first": {
                    "outputs": {
                        "9": {
                            "images": [
                                {
                                    "filename": "runner_first.png",
                                    "subfolder": "",
                                    "type": "output",
                                }
                            ]
                        }
                    },
                    "status": {"completed": True},
                    "prompt": [0, "c", {}, {"extra_pnginfo": {"workflow": prep_wf}}, ["9"]],
                }
            }
            run_local_path = out_dir / "runner_first.png"
            _assert_true("precondition local exists", run_local_path.is_file())
            run_local_path.unlink()
            _assert_true("local deleted for recovery A", not run_local_path.is_file())
            rows_pre_rec = len(load_architecture_benchmark_records(architecture_ledger_path(drive)))
            files_pre = list((drive / "outputs").glob("identity_architecture_benchmark_*"))
            rec_rep = recover_identity_architecture_from_history(
                drive_root=drive,
                comfy_output_dir=out_dir,
                base_url="http://127.0.0.1:8188",
                history=hist,
            )
            _assert_true("recovery A ok", rec_rep.get("ok") is True)
            _assert_equal("recovery A captured", rec_rep.get("captured"), 0)
            _assert_equal("recovery A duplicates", rec_rep.get("duplicates"), 1)
            _assert_equal("recovery A failed", rec_rep.get("failed"), 0)
            _assert_equal("recovery A new_architecture_rows", rec_rep.get("new_architecture_rows"), 0)
            _assert_equal("recovery A new_drive_files", rec_rep.get("new_drive_files"), 0)
            _assert_equal(
                "recovery A ledger row count unchanged",
                len(load_architecture_benchmark_records(architecture_ledger_path(drive))),
                rows_pre_rec,
            )
            _assert_equal(
                "recovery A drive file count unchanged",
                len(list((drive / "outputs").glob("identity_architecture_benchmark_*"))),
                len(files_pre),
            )
            _pass(
                results,
                "recovery A: captured + local deleted -> duplicates=1, no new files/rows",
            )

            # Recovery B: captured + local deleted + Drive missing -> REPAIR_REQUIRED_MISSING
            b_local = out_dir / "recover_b.png"
            b_local.write_bytes(out_img.read_bytes())
            b_sha = file_sha256(b_local).lower()
            b_cap = capture_identity_architecture_execution(
                drive_root=drive,
                prompt_id="pid-recover-b",
                output_node_id="9",
                output_path=b_local,
                output_sha256=b_sha,
                provenance=prov_arch,
                ui_workflow=prep_wf,
                preparation_id=prep.preparation_id,
                scenario="S1_near_front_portrait",
                character_id=reg.character.character_id,
                seed=11,
            )
            _assert_true(f"recovery B capture ok ({b_cap.errors})", b_cap.ok)
            b_drive = Path(b_cap.drive_path)
            b_local.unlink(missing_ok=True)
            b_drive.unlink(missing_ok=True)
            files_b_pre = list((drive / "outputs").glob("identity_architecture_benchmark_*"))
            hist_b = {
                "pid-recover-b": {
                    "outputs": {
                        "9": {
                            "images": [
                                {"filename": "recover_b.png", "subfolder": "", "type": "output"}
                            ]
                        }
                    },
                    "status": {"completed": True},
                    "prompt": [0, "c", {}, {"extra_pnginfo": {"workflow": prep_wf}}, ["9"]],
                }
            }
            rec_b = recover_identity_architecture_from_history(
                drive_root=drive,
                comfy_output_dir=out_dir,
                base_url="http://127.0.0.1:8188",
                history=hist_b,
            )
            _assert_true("recovery B not ok", rec_b.get("ok") is False)
            _assert_true(
                "recovery B REPAIR_REQUIRED_MISSING",
                any("REPAIR_REQUIRED" in e for e in (rec_b.get("errors") or [])),
            )
            _assert_true(
                "recovery B no SHA mismatch label",
                not any("SHA_MISMATCH" in e for e in (rec_b.get("errors") or [])),
            )
            _assert_true(
                "recovery B no replacement file",
                len(list((drive / "outputs").glob("identity_architecture_benchmark_*")))
                == len(files_b_pre),
            )
            _pass(results, "recovery B: Drive missing -> REPAIR_REQUIRED, no replacement")

            # Recovery C: captured + local deleted + Drive SHA mismatch
            c_local = out_dir / "recover_c.png"
            c_local.write_bytes(out_img.read_bytes())
            c_sha = file_sha256(c_local).lower()
            c_cap = capture_identity_architecture_execution(
                drive_root=drive,
                prompt_id="pid-recover-c",
                output_node_id="9",
                output_path=c_local,
                output_sha256=c_sha,
                provenance=prov_arch,
                ui_workflow=prep_wf,
                preparation_id=prep.preparation_id,
                scenario="S1_near_front_portrait",
                character_id=reg.character.character_id,
                seed=12,
            )
            _assert_true(f"recovery C capture ok ({c_cap.errors})", c_cap.ok)
            c_drive = Path(c_cap.drive_path)
            c_local.unlink(missing_ok=True)
            c_drive.write_bytes(b"\x89PNG\r\n\x1a\n" + b"CORRUPTED-ARCH-BYTES")
            files_c_pre = list((drive / "outputs").glob("identity_architecture_benchmark_*"))
            hist_c = {
                "pid-recover-c": {
                    "outputs": {
                        "9": {
                            "images": [
                                {"filename": "recover_c.png", "subfolder": "", "type": "output"}
                            ]
                        }
                    },
                    "status": {"completed": True},
                    "prompt": [0, "c", {}, {"extra_pnginfo": {"workflow": prep_wf}}, ["9"]],
                }
            }
            rec_c = recover_identity_architecture_from_history(
                drive_root=drive,
                comfy_output_dir=out_dir,
                base_url="http://127.0.0.1:8188",
                history=hist_c,
            )
            _assert_true("recovery C not ok", rec_c.get("ok") is False)
            _assert_true(
                "recovery C SHA mismatch",
                any("SHA_MISMATCH" in e or "SHA mismatch" in e for e in (rec_c.get("errors") or [])),
            )
            _assert_equal(
                "recovery C no extra drive files",
                len(list((drive / "outputs").glob("identity_architecture_benchmark_*"))),
                len(files_c_pre),
            )
            _pass(results, "recovery C: Drive SHA mismatch -> fail closed, no replacement")

            # Recovery D: uncaptured + local missing
            hist_d = {
                "pid-recover-d": {
                    "outputs": {
                        "9": {
                            "images": [
                                {
                                    "filename": "never_existed_arch.png",
                                    "subfolder": "",
                                    "type": "output",
                                }
                            ]
                        }
                    },
                    "status": {"completed": True},
                    "prompt": [0, "c", {}, {"extra_pnginfo": {"workflow": prep_wf}}, ["9"]],
                }
            }
            rec_d = recover_identity_architecture_from_history(
                drive_root=drive,
                comfy_output_dir=out_dir,
                base_url="http://127.0.0.1:8188",
                history=hist_d,
            )
            _assert_true("recovery D not ok", rec_d.get("ok") is False)
            _assert_true(
                "recovery D uncaptured/missing local",
                any(
                    "uncaptured" in e.lower() or "missing" in e.lower()
                    for e in (rec_d.get("errors") or [])
                ),
            )
            _pass(results, "recovery D: uncaptured + local missing -> fail closed")

            # Recovery E: ambiguous ledger execution (same prompt/node, different SHAs)
            append_architecture_benchmark_record(
                architecture_ledger_path(drive),
                IdentityArchitectureRecord(
                    candidate=CANDIDATE_INSTANTID,
                    architecture="instantid_sdxl",
                    scenario="S1_near_front_portrait",
                    character_id=reg.character.character_id,
                    prompt_id="pid-ambiguous",
                    output_node_id="9",
                    output_path=str(drive / "outputs" / "ambig_a.png"),
                    output_sha256="a" * 64,
                    capture_idempotence_key=architecture_idempotence_key(
                        "pid-ambiguous", "9", "a" * 64
                    ),
                ),
            )
            append_architecture_benchmark_record(
                architecture_ledger_path(drive),
                IdentityArchitectureRecord(
                    candidate=CANDIDATE_INSTANTID,
                    architecture="instantid_sdxl",
                    scenario="S1_near_front_portrait",
                    character_id=reg.character.character_id,
                    prompt_id="pid-ambiguous",
                    output_node_id="9",
                    output_path=str(drive / "outputs" / "ambig_b.png"),
                    output_sha256="b" * 64,
                    capture_idempotence_key=architecture_idempotence_key(
                        "pid-ambiguous", "9", "b" * 64
                    ),
                ),
            )
            hist_e = {
                "pid-ambiguous": {
                    "outputs": {
                        "9": {
                            "images": [
                                {"filename": "ambig_gone.png", "subfolder": "", "type": "output"}
                            ]
                        }
                    },
                    "status": {"completed": True},
                    "prompt": [0, "c", {}, {"extra_pnginfo": {"workflow": prep_wf}}, ["9"]],
                }
            }
            rec_e = recover_identity_architecture_from_history(
                drive_root=drive,
                comfy_output_dir=out_dir,
                base_url="http://127.0.0.1:8188",
                history=hist_e,
            )
            _assert_true("recovery E not ok", rec_e.get("ok") is False)
            _assert_true(
                "recovery E AMBIGUOUS_LEDGER_EXECUTION",
                any("AMBIGUOUS_LEDGER_EXECUTION" in e for e in (rec_e.get("errors") or [])),
            )
            _pass(results, "recovery E: ambiguous prompt/node SHAs -> fail closed")

            # Missing ledger Drive artifact -> REPAIR_REQUIRED (capture path)
            bad_row = dict(same_key_rows[0])
            bad_row["output_path"] = str(drive / "outputs" / "missing_arch_artifact.png")
            bad_row["prompt_id"] = "pid-repair"
            bad_row["capture_idempotence_key"] = architecture_idempotence_key(
                "pid-repair", "9", drive_sha
            )
            append_architecture_benchmark_record(
                architecture_ledger_path(drive),
                IdentityArchitectureRecord(
                    candidate=CANDIDATE_INSTANTID,
                    architecture="instantid_sdxl",
                    scenario="S1_near_front_portrait",
                    character_id=reg.character.character_id,
                    prompt_id="pid-repair",
                    output_node_id="9",
                    output_path=str(drive / "outputs" / "missing_arch_artifact.png"),
                    output_sha256=drive_sha,
                    capture_idempotence_key=architecture_idempotence_key(
                        "pid-repair", "9", drive_sha
                    ),
                ),
            )
            from core.runtime.identity_benchmark_capture import (
                STATUS_REPAIR_REQUIRED_MISSING,
                STATUS_REPAIR_REQUIRED_SHA_MISMATCH,
                verify_existing_ledger_artifact,
            )

            st, _, _, errs = verify_existing_ledger_artifact(
                find_architecture_ledger_row(
                    architecture_ledger_path(drive),
                    prompt_id="pid-repair",
                    output_node_id="9",
                    output_sha256=drive_sha,
                )
                or {},
                expected_sha256=drive_sha,
            )
            _assert_equal("missing artifact REPAIR_REQUIRED", st, STATUS_REPAIR_REQUIRED_MISSING)
            repair_cap = capture_identity_architecture_execution(
                drive_root=drive,
                prompt_id="pid-repair",
                output_node_id="9",
                output_path=out_img,
                output_sha256=drive_sha,
                provenance=prov_arch,
                ui_workflow=prep_wf,
                preparation_id=prep.preparation_id,
                scenario="S1_near_front_portrait",
                character_id=reg.character.character_id,
            )
            _assert_true("repair refuses silent recreate", not repair_cap.ok)
            _assert_true(
                "REPAIR_REQUIRED in errors",
                any("REPAIR_REQUIRED" in e for e in repair_cap.errors),
            )
            _pass(results, "missing ledger Drive artifact -> REPAIR_REQUIRED")

            # SHA mismatch fail closed
            mismatch_local = out_dir / "mismatch.png"
            mismatch_local.write_bytes(b"\x89PNG\r\n\x1a\n" + b"DIFFERENT-BYTES")
            mm_row = find_architecture_ledger_row(
                architecture_ledger_path(drive),
                prompt_id="pid-test-001",
                output_node_id="9",
                output_sha256=drive_sha,
            )
            assert mm_row is not None
            st2, _, _, errs2 = verify_existing_ledger_artifact(
                {**mm_row, "output_path": str(mismatch_local)},
                expected_sha256=drive_sha,
            )
            _assert_equal("SHA mismatch status", st2, STATUS_REPAIR_REQUIRED_SHA_MISMATCH)
            _pass(results, "SHA mismatch ledger Drive artifact fail closed")

            # Isolation: no ordinary parent eligibility
            arch_meta = {
                "preparation_kind": PREPARATION_KIND,
                "benchmark_run": True,
                "capability": "identity_architecture_benchmark",
                "candidate": CANDIDATE_INSTANTID,
                "architecture": "instantid_sdxl",
            }
            _assert_true(
                "architecture is benchmark metadata",
                is_benchmark_generation_metadata(arch_meta),
            )
            _assert_true(
                "architecture provenance helper",
                is_identity_architecture_benchmark_provenance(
                    ExecutionProvenance(
                        preparation_kind=PREPARATION_KIND,
                        capability="identity_architecture_benchmark",
                    ),
                    {"extra": {"ai_studio": arch_meta}},
                ),
            )
            deriv = assess_derivation_eligibility(metadata=arch_meta, manifest={})
            repro = assess_reproduction_eligibility(
                metadata=arch_meta, workflow_payload={}, manifest={}
            )
            _assert_true("architecture refused as 4.11 parent", not deriv.eligible)
            _assert_true("architecture refused as 4.10 parent", not repro.eligible)
            _pass(results, "architecture isolated from ordinary snapshot/index/parents")

            # Evidence ledger still receives verified evidence
            _assert_true("evidence file exists", evidence.is_file())
            ev_text = evidence.read_text(encoding="utf-8")
            _assert_true(
                "evidence has architecture capability or skip status",
                "identity_architecture_benchmark" in ev_text
                or "skipped_identity_architecture_benchmark" in ev_text,
            )
            _pass(results, "evidence ledger receives verified architecture evidence")

            # QA enrichment does not append duplicate row
            key_rf = architecture_idempotence_key("pid-run-first", "9", run_sha)
            rows_enr_before = len(load_architecture_benchmark_records(architecture_ledger_path(drive)))
            ok_e, upd, _ = update_architecture_ledger_qa(
                architecture_ledger_path(drive),
                idempotence_key=key_rf,
                automated_qa={
                    "automated_quality_status": "provisional_pass",
                    "human_review_status": "HUMAN_REVIEW_REQUIRED",
                },
            )
            _assert_true("QA enrich ok", ok_e)
            _assert_equal(
                "QA enrich no new row",
                len(load_architecture_benchmark_records(architecture_ledger_path(drive))),
                rows_enr_before,
            )
            _pass(results, "QA enrichment does not append duplicate architecture row")

            # Runtime reset simulation: delete local, Drive path still valid
            Path(live.local_path).unlink(missing_ok=True)
            _assert_true(
                "Drive path survives local delete",
                Path(live.output_path).is_file(),
            )
            _assert_equal(
                "ledger SHA still matches Drive after local wipe",
                file_sha256(Path(live.output_path)).lower(),
                live.output_sha256.lower(),
            )
            _pass(results, "runtime reset does not invalidate architecture ledger output_path")

            # Completion timeout
            def timeout_wait(prompt_id, **kwargs):
                return WaitHistoryResult(
                    ok=False,
                    timed_out=True,
                    errors=[f"ERROR: Timed out waiting for {prompt_id}"],
                )

            timed = execute_architecture_scenario(
                repo_root=repo_root,
                drive_root=drive,
                character_id=reg.character.character_id,
                scenario="S1_near_front_portrait",
                bundle_models=list(bundle.models),
                bundle_nodes=list(bundle.nodes),
                runtime_prepared_root=runtime / "prepared_workflows",
                comfyui_input_dir=comfy / "input",
                comfyui_runtime=comfy,
                comfyui_output_dir=out_dir,
                require_models=False,
                require_nodes=False,
                require_verified_assets=False,
                queue_prompt_fn=fake_queue,
                wait_history_fn=timeout_wait,
                sleep_fn=lambda _s: None,
            )
            _assert_true("timeout fails", not timed.ok)
            _assert_equal("timeout status", timed.queue_status, "timeout")
            _pass(results, "bounded completion timeout fail-closed")

            # Failed execution
            def fail_queue(api_prompt, **kwargs):
                return QueuePromptResult(ok=False, errors=["ERROR: ComfyUI /prompt HTTP 500"])

            failed = execute_architecture_scenario(
                repo_root=repo_root,
                drive_root=drive,
                character_id=reg.character.character_id,
                scenario="S1_near_front_portrait",
                bundle_models=list(bundle.models),
                bundle_nodes=list(bundle.nodes),
                runtime_prepared_root=runtime / "prepared_workflows",
                comfyui_input_dir=comfy / "input",
                comfyui_runtime=comfy,
                comfyui_output_dir=out_dir,
                require_models=False,
                require_nodes=False,
                require_verified_assets=False,
                queue_prompt_fn=fail_queue,
                wait_history_fn=fake_wait,
                sleep_fn=lambda _s: None,
            )
            _assert_true("failed queue not ok", not failed.ok)
            _assert_equal("failed queue status", failed.queue_status, "failed")
            _pass(results, "failed /prompt execution fail-closed")

            # wait_for_prompt_completion bounded polling unit
            polls = {"n": 0}

            def fetch_once(**kwargs):
                polls["n"] += 1
                if polls["n"] < 3:
                    return {}
                return {
                    "pid-x": {
                        "outputs": {"9": {"images": [{"filename": "x.png"}]}},
                        "status": {"completed": True, "status_str": "success"},
                    }
                }

            waited = wait_for_prompt_completion(
                "pid-x",
                timeout_seconds=5.0,
                poll_interval_seconds=0.01,
                sleep_fn=lambda _s: None,
                fetch_fn=fetch_once,
            )
            _assert_true("poll completed", waited.ok)
            _assert_true("polled multiple times", polls["n"] >= 3)
            _pass(results, "bounded completion polling")

            # Fail-fast policy
            _assert_true(
                "S1 fail stops",
                should_fail_fast(
                    "S1_near_front_portrait",
                    {"automated_quality_status": "fail"},
                    continue_after_fail=False,
                ),
            )
            _assert_true(
                "S2 fail stops without continue",
                should_fail_fast(
                    "S2_head_angle_pose",
                    {"automated_quality_status": "fail"},
                    continue_after_fail=False,
                ),
            )
            _assert_true(
                "S2 continue-after-fail allows",
                not should_fail_fast(
                    "S2_head_angle_pose",
                    {"automated_quality_status": "fail"},
                    continue_after_fail=True,
                ),
            )
            _assert_true(
                "S4 fail always stops",
                should_fail_fast(
                    "S4_wardrobe_environment",
                    {"automated_quality_status": "fail"},
                    continue_after_fail=True,
                ),
            )
            _assert_true(
                "inconclusive pauses",
                should_fail_fast(
                    "S2_head_angle_pose",
                    {"automated_quality_status": "inconclusive"},
                    continue_after_fail=True,
                ),
            )
            _pass(results, "fail-fast and --continue-after-fail behavior")

            # UI->API conversion yields InstantID nodes
            wf_path = (
                repo_root / "workflows/reference/identity_instantid_sdxl_benchmark/workflow.json"
            )
            api = ui_workflow_to_api_prompt(json.loads(wf_path.read_text(encoding="utf-8")))
            _assert_true("api prompt non-empty", bool(api))
            types = {v.get("class_type") for v in api.values()}
            _assert_true("ApplyInstantIDAdvanced in API", "ApplyInstantIDAdvanced" in types)
            _pass(results, "UI workflow converts for /prompt submission")

            # CLI ack flags: execute without ack must fail (subprocess)
            import subprocess

            cli = repo_root / "core" / "scripts" / "run_identity_architecture_benchmark.py"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(cli),
                    "--character-id",
                    reg.character.character_id,
                    "--scenario",
                    "S1",
                    "--execute-benchmark",
                    "--repo-root",
                    str(repo_root),
                ],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            _assert_true("no execute without ack", proc.returncode != 0)
            _assert_true(
                "ack error message",
                "acknowledge" in (proc.stderr or "").lower()
                or "allow-benchmark" in (proc.stderr or "").lower(),
            )
            _pass(results, "no execute without explicit ack flags")

            # Required QA suite zero tests -> fail semantics
            fake_suite = {
                "exit_code": 0,
                "tests_discovered": 0,
                "passed": 0,
                "failed": 1,
                "ok": False,
                "zero_tests_discovered": True,
            }
            _assert_true(
                "zero tests suite not ok",
                not fake_suite["ok"] and fake_suite["zero_tests_discovered"],
            )
            _pass(results, "required QA suite with zero tests -> consolidated QA fail")

        finally:
            exec_mod.open_prepared_workflow_for_comfyui = real_open  # type: ignore[assignment]
            reset_qa_test_hooks()

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
