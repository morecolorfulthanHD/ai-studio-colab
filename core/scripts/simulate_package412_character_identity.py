#!/usr/bin/env python3
"""Package 4.12 — character identity + identity-method benchmark simulations."""

from __future__ import annotations

import json
import shutil
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

from core.runtime.character_identity import (
    list_characters,
    load_character,
    register_character,
    verify_character_face,
)
from core.runtime.generation_derivation import assess_derivation_eligibility
from core.runtime.generation_evidence_ledger import file_sha256
from core.runtime.generation_reproduction import assess_reproduction_eligibility
from core.runtime.identity_benchmark import (
    CANDIDATE_FACEID,
    CANDIDATE_REACTOR,
    IdentityBenchmarkRecord,
    PREPARATION_KIND_IDENTITY_BENCHMARK,
    SCENARIO_IDS,
    append_identity_benchmark_record,
    is_benchmark_generation_metadata,
    load_identity_benchmark_records,
    prepare_identity_benchmark,
    restage_identity_benchmark_face,
)
from core.runtime.registry_loader import RegistryLoader


def _assert_true(label: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {label}")


def _assert_false(label: str, cond: bool) -> None:
    if cond:
        raise AssertionError(f"FAIL: {label}")


def _assert_equal(label: str, actual, expected) -> None:
    if actual != expected:
        raise AssertionError(f"FAIL: {label}: {actual!r} != {expected!r}")


def _pass(results: list[tuple[str, str]], label: str) -> None:
    results.append((label, "PASS"))
    print(f"PASS: {label}")


def _write_png(path: Path, payload: bytes = b"PK412-FACE") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal non-empty file treated as image bytes for SHA tests (not a decode check).
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + payload)


def _setup_temp_repo(repo_root: Path) -> dict[str, Path]:
    drive = Path(tempfile.mkdtemp(prefix="pk412_drive_"))
    runtime = Path(tempfile.mkdtemp(prefix="pk412_runtime_"))
    comfy = Path(tempfile.mkdtemp(prefix="pk412_comfy_"))
    for sub in ("outputs", "inputs", "logs", "characters", "workflows/prepared", "benchmarks"):
        (drive / sub).mkdir(parents=True, exist_ok=True)
    prepared = runtime / "prepared_workflows"
    prepared.mkdir(parents=True, exist_ok=True)
    (comfy / "input").mkdir(parents=True, exist_ok=True)
    (comfy / "custom_nodes" / "ComfyUI-ReActor").mkdir(parents=True, exist_ok=True)
    (comfy / "custom_nodes" / "ComfyUI_IPAdapter_plus").mkdir(parents=True, exist_ok=True)
    # Model stubs for fail-open allow-missing tests and optional present-path tests.
    insight = drive / "models" / "shared" / "insightface" / "models" / "buffalo_l" / "w600k_r50.onnx"
    insight.parent.mkdir(parents=True, exist_ok=True)
    insight.write_bytes(b"onnx-stub")
    return {
        "drive": drive,
        "runtime": runtime,
        "comfy": comfy,
        "prepared": prepared,
        "input": comfy / "input",
        "insight": insight,
    }


def main() -> int:
    results: list[tuple[str, str]] = []
    repo_root = Path(__file__).resolve().parents[2]
    bundle = RegistryLoader(repo_root).load_all()
    paths = _setup_temp_repo(repo_root)

    try:
        # Character register / list / verify
        face = paths["drive"] / "inputs" / "face_ref.png"
        _write_png(face, b"face-a")
        reg = register_character(
            paths["drive"],
            display_name="Benchmark Persona",
            primary_face_image=face,
        )
        _assert_true("register ok", reg.ok)
        _assert_true("char id prefix", reg.character.character_id.startswith("char_"))
        _pass(results, "Character register creates Drive-backed char_* record")

        loaded = load_character(paths["drive"], reg.character.character_id)
        _assert_true("load ok", loaded is not None)
        ok, err = verify_character_face(paths["drive"], loaded)
        _assert_true(f"face verify ({err})", ok)
        listed = list_characters(paths["drive"])
        _assert_equal("list count", len(listed), 1)
        _pass(results, "Character list/info/SHA verify")

        # SHA mismatch fail-closed
        face_path = Path(reg.character_dir) / "references" / "primary_face.png"
        face_path.write_bytes(b"\x89PNG\r\n\x1a\ntampered")
        ok2, _ = verify_character_face(paths["drive"], loaded)
        _assert_false("tamper detected", ok2)
        # restore
        shutil.copy2(face, face_path)
        _pass(results, "Character face SHA mismatch fails closed")

        # Restart persistence (Drive only)
        shutil.rmtree(paths["runtime"], ignore_errors=True)
        still = load_character(paths["drive"], reg.character.character_id)
        _assert_true("survives runtime wipe", still is not None)
        ok3, _ = verify_character_face(paths["drive"], still)
        _assert_true("face survives runtime wipe", ok3)
        _pass(results, "Character persists after runtime-local wipe")

        # Unknown character
        missing = load_character(paths["drive"], f"char_{uuid.uuid4()}")
        _assert_true("unknown missing", missing is None)
        _pass(results, "Unknown character ID fails closed")

        # Patch model runtime paths for present InsightFace in temp drive
        models = []
        for entry in bundle.models:
            row = dict(entry)
            if row.get("name") == "insightface":
                row["runtime_path"] = str(paths["insight"])
            models.append(row)

        # Prepare without --allow-benchmark fails
        blocked = prepare_identity_benchmark(
            repo_root,
            drive_root=paths["drive"],
            candidate=CANDIDATE_REACTOR,
            scenario="S1_near_front_portrait",
            character_id=reg.character.character_id,
            runtime_prepared_root=paths["prepared"],
            comfyui_input_dir=paths["input"],
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            require_models=False,
            require_nodes=True,
            allow_benchmark=False,
        )
        _assert_false("blocked without allow", blocked.ok)
        _pass(results, "Identity benchmark requires explicit --allow-benchmark")

        # Missing FaceID models fail closed when required
        faceid_missing = prepare_identity_benchmark(
            repo_root,
            drive_root=paths["drive"],
            candidate=CANDIDATE_FACEID,
            scenario="S1_near_front_portrait",
            character_id=reg.character.character_id,
            runtime_prepared_root=paths["prepared"],
            comfyui_input_dir=paths["input"],
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            require_models=True,
            require_nodes=True,
            allow_benchmark=True,
        )
        _assert_false("faceid missing models", faceid_missing.ok)
        _assert_true("reports missing models", bool(faceid_missing.missing_models))
        _pass(results, "FaceID missing weights fail closed (no auto-download)")

        # ReActor prepare with present node + insightface
        prep = prepare_identity_benchmark(
            repo_root,
            drive_root=paths["drive"],
            candidate=CANDIDATE_REACTOR,
            scenario="S2_head_angle_pose",
            character_id=reg.character.character_id,
            runtime_prepared_root=paths["prepared"],
            comfyui_input_dir=paths["input"],
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            seed=135791357,
            require_models=True,
            require_nodes=True,
            allow_benchmark=True,
        )
        _assert_true(f"reactor prep ({prep.errors})", prep.ok)
        _assert_equal("prep kind", PREPARATION_KIND_IDENTITY_BENCHMARK, "identity_benchmark")
        meta = json.loads((Path(prep.prepared_dir) / f"{prep.preparation_id}.metadata.json").read_text(encoding="utf-8"))
        _assert_equal("benchmark_run", meta.get("benchmark_run"), True)
        _assert_equal("kind", meta.get("preparation_kind"), PREPARATION_KIND_IDENTITY_BENCHMARK)
        _assert_true("staged face", (paths["input"] / prep.staged_face_filename).is_file())
        _pass(results, "ReActor identity benchmark prepare stages archived face")

        # Restage after clearing Comfy input
        for item in paths["input"].glob("*"):
            if item.is_file():
                item.unlink()
        msgs, errs = restage_identity_benchmark_face(
            prepared_dir=Path(prep.prepared_dir),
            metadata=meta,
            comfyui_input_dir=paths["input"],
        )
        _assert_true(f"restage ({errs})", not errs)
        _assert_true("restaged file", (paths["input"] / prep.staged_face_filename).is_file())
        _pass(results, "Identity benchmark face restages after input clear")

        # FaceID prepare with allow-missing-models for plumbing-only sim
        faceid_prep = prepare_identity_benchmark(
            repo_root,
            drive_root=paths["drive"],
            candidate=CANDIDATE_FACEID,
            scenario="S4_wardrobe_environment",
            character_id=reg.character.character_id,
            runtime_prepared_root=paths["prepared"],
            comfyui_input_dir=paths["input"],
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            require_models=False,
            require_nodes=True,
            allow_benchmark=True,
        )
        _assert_true(f"faceid prep plumbing ({faceid_prep.errors})", faceid_prep.ok)
        _pass(results, "FaceID benchmark prepare works as plumbing with allow-missing-models")

        # Deferred InstantID rejected
        bad = prepare_identity_benchmark(
            repo_root,
            drive_root=paths["drive"],
            candidate="instantid_sdxl_deferred",
            scenario="S1_near_front_portrait",
            character_id=reg.character.character_id,
            runtime_prepared_root=paths["prepared"],
            comfyui_input_dir=paths["input"],
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            allow_benchmark=True,
            require_models=False,
            require_nodes=False,
        )
        _assert_false("instantid deferred", bad.ok)
        _pass(results, "InstantID/SDXL deferred candidate refused")

        # Scenario coverage constant
        _assert_equal("four scenarios", len(SCENARIO_IDS), 4)
        _pass(results, "S1–S4 scenario matrix defined")

        # Ledger append
        ledger = paths["drive"] / "logs" / "identity_benchmark.jsonl"
        append_identity_benchmark_record(
            ledger,
            IdentityBenchmarkRecord(
                candidate=CANDIDATE_REACTOR,
                scenario="S1_near_front_portrait",
                character_id=reg.character.character_id,
                preparation_id=prep.preparation_id,
                success=None,
                notes=["simulation plumbing record — not a quality claim"],
            ),
        )
        rows = load_identity_benchmark_records(ledger)
        _assert_equal("ledger rows", len(rows), 1)
        _assert_equal("promotion pending", rows[0].get("promotion_status"), "pending")
        _pass(results, "Identity benchmark ledger append/report")

        # Benchmark gens refused as variation/reproduction parents
        bench_meta = {
            "benchmark_run": True,
            "preparation_kind": PREPARATION_KIND_IDENTITY_BENCHMARK,
            "capability": "identity_benchmark",
            "workflow_identifier": "reference/identity_reactor_benchmark",
            "image_sha256": "abc",
            "positive_prompt": "x",
            "steps": 20,
            "cfg": 7,
            "sampler_name": "euler",
            "scheduler": "normal",
            "model_files": ["sd15.safetensors"],
        }
        _assert_true("detector", is_benchmark_generation_metadata(bench_meta))
        elig = assess_derivation_eligibility(metadata=bench_meta, manifest={"image_sha256": "abc"})
        _assert_false("variation refused", elig.eligible)
        repro = assess_reproduction_eligibility(
            metadata=bench_meta,
            workflow_payload={"workflow_identifier": "base/txt2img", "workflow_snapshot_status": "complete"},
            manifest={},
        )
        _assert_false("reproduction refused", repro.eligible)
        _pass(results, "Benchmark generations refused as ordinary variation/reproduction parents")

        # Registry presence
        cap_ids = {c.get("id") for c in bundle.capabilities}
        _assert_true("capability registered", "identity_benchmark" in cap_ids)
        manifest = json.loads(
            (repo_root / "configs/benchmarks/identity_method_benchmark.json").read_text(encoding="utf-8")
        )
        _assert_equal("two live candidates", len(manifest.get("live_candidates") or []), 2)
        _pass(results, "Benchmark manifest + capability registry present")

        # No quality claim from prepare
        _assert_true(
            "quality warning",
            any("quality-benchmarked" in w.lower() or "quality" in w.lower() for w in prep.warnings),
        )
        _pass(results, "Prepare path explicitly disclaims quality benchmarking")

    finally:
        shutil.rmtree(paths["drive"], ignore_errors=True)
        shutil.rmtree(paths["runtime"], ignore_errors=True)
        shutil.rmtree(paths["comfy"], ignore_errors=True)

    print()
    print(f"RESULT: {sum(1 for _, s in results if s == 'PASS')}/{len(results)} Package 4.12 simulations passed.")
    failed = [label for label, status in results if status != "PASS"]
    if failed:
        print("FAILED:", "; ".join(failed), file=sys.stderr)
        return 1
    print("NOTE: Simulations do NOT quality-benchmark ReActor or FaceID.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
