#!/usr/bin/env python3
"""Package 4.12 — character identity + identity-method benchmark simulations."""

from __future__ import annotations

import json
import hashlib
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
    INTEGRITY_MISSING,
    INTEGRITY_PRESENT,
    INTEGRITY_SHA256_MISMATCH,
    INTEGRITY_SIZE_MISMATCH,
    INTEGRITY_VERIFIED,
    IdentityBenchmarkRecord,
    PREPARATION_KIND_IDENTITY_BENCHMARK,
    SCENARIO_IDS,
    append_identity_benchmark_record,
    assert_identity_benchmark_graph,
    assess_identity_benchmark_dependencies,
    assess_reactor_model_readiness,
    backfill_identity_benchmark_preparation,
    is_benchmark_generation_metadata,
    load_identity_benchmark_records,
    normalize_scenario_id,
    prepare_identity_benchmark,
    restage_identity_benchmark_face,
    verify_model_asset_integrity,
    verify_required_model_assets,
)
from core.runtime.prepared_workflow_index import find_by_preparation_id, preparations_log_path
from core.runtime.reactor_model_bridge import (
    default_canonical_insightface_dir,
    ensure_reactor_insightface_bridge,
    reactor_runtime_inswapper_path,
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
    (comfy / "custom_nodes" / "ComfyUI-ReActor" / "nodes.py").write_text(
        'NODE_CLASS_MAPPINGS = {"ReActorFaceSwap": object}\n',
        encoding="utf-8",
    )
    (comfy / "custom_nodes" / "ComfyUI_IPAdapter_plus" / "nodes.py").write_text(
        'NODE_CLASS_MAPPINGS = {"IPAdapterUnifiedLoaderFaceID": object, "IPAdapterFaceID": object}\n',
        encoding="utf-8",
    )
    # Model stubs for fail-open allow-missing tests and optional present-path tests.
    insight = drive / "models" / "shared" / "insightface" / "models" / "buffalo_l" / "w600k_r50.onnx"
    insight.parent.mkdir(parents=True, exist_ok=True)
    insight.write_bytes(b"onnx-stub")
    inswapper = drive / "models" / "shared" / "insightface" / "inswapper_128.onnx"
    inswapper.parent.mkdir(parents=True, exist_ok=True)
    inswapper.write_bytes(b"inswapper-stub")
    return {
        "drive": drive,
        "runtime": runtime,
        "comfy": comfy,
        "prepared": prepared,
        "input": comfy / "input",
        "insight": insight,
        "inswapper": inswapper,
        "drive_prepared": drive / "workflows" / "prepared",
    }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _faceid_integrity_models(
    bundle_models: list[dict],
    drive: Path,
    *,
    bin_content: bytes | None = b"faceid-bin-ok",
    lora_content: bytes | None = b"faceid-lora-ok",
    clip_content: bytes | None = b"faceid-clip-ok",
    bin_size_override: int | None = None,
    lora_size_override: int | None = None,
    clip_size_override: int | None = None,
) -> list[dict]:
    asset_specs = {
        "ipadapter_faceid_plusv2_sd15": (
            drive / "models/shared/ipadapter/ip-adapter-faceid-plusv2_sd15.bin",
            bin_content,
            bin_size_override,
        ),
        "ipadapter_faceid_plusv2_sd15_lora": (
            drive / "models/shared/loras/ip-adapter-faceid-plusv2_sd15_lora.safetensors",
            lora_content,
            lora_size_override,
        ),
        "clip_vision_sd15": (
            drive / "models/shared/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
            clip_content,
            clip_size_override,
        ),
    }
    models: list[dict] = []
    for entry in bundle_models:
        row = dict(entry)
        name = str(row.get("name") or "")
        if name == "insightface":
            row["runtime_path"] = str(
                drive / "models/shared/insightface/models/buffalo_l/w600k_r50.onnx"
            )
            insight = Path(row["runtime_path"])
            insight.parent.mkdir(parents=True, exist_ok=True)
            if not insight.is_file():
                insight.write_bytes(b"onnx-stub")
        elif name == "reactor_inswapper_128":
            row["runtime_path"] = str(drive / "models/shared/insightface/inswapper_128.onnx")
            swap = Path(row["runtime_path"])
            swap.parent.mkdir(parents=True, exist_ok=True)
            if not swap.is_file():
                swap.write_bytes(b"inswapper-stub")
        elif name in asset_specs:
            path, content, size_override = asset_specs[name]
            row["runtime_path"] = str(path)
            if content is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                row["expected_sha256"] = _sha256_bytes(content)
                row["expected_size_bytes"] = (
                    size_override if size_override is not None else len(content)
                )
            elif size_override is not None:
                row["expected_size_bytes"] = size_override
        models.append(row)
    return models


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

        # Patch model runtime paths for present InsightFace + inswapper in temp drive
        models = []
        for entry in bundle.models:
            row = dict(entry)
            if row.get("name") == "insightface":
                row["runtime_path"] = str(paths["insight"])
            if row.get("name") == "reactor_inswapper_128":
                row["runtime_path"] = str(paths["inswapper"])
            models.append(row)

        # Canonical graphs contain real candidate nodes (structural readiness)
        reactor_wf = json.loads(
            (repo_root / "workflows/reference/identity_reactor_benchmark/workflow.json").read_text(
                encoding="utf-8"
            )
        )
        faceid_wf = json.loads(
            (repo_root / "workflows/reference/identity_faceid_benchmark/workflow.json").read_text(
                encoding="utf-8"
            )
        )
        _assert_equal(
            "reactor graph structural",
            assert_identity_benchmark_graph(reactor_wf, CANDIDATE_REACTOR),
            [],
        )
        _assert_equal(
            "faceid graph structural",
            assert_identity_benchmark_graph(faceid_wf, CANDIDATE_FACEID),
            [],
        )
        _pass(results, "Canonical workflows include real ReActor/FaceID nodes (structural)")

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
            drive_prepared_root=paths["drive_prepared"],
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
            drive_prepared_root=paths["drive_prepared"],
            require_models=True,
            require_nodes=True,
            allow_benchmark=True,
        )
        _assert_false("faceid missing models", faceid_missing.ok)
        _assert_true("reports missing models", bool(faceid_missing.missing_models))
        _assert_true(
            "manual instructions",
            any("MISSING" in e for e in faceid_missing.errors),
        )
        _pass(results, "FaceID missing weights fail closed (no auto-download)")

        # Missing ReActor inswapper fails closed
        models_no_swap = [dict(m) for m in models]
        for row in models_no_swap:
            if row.get("name") == "reactor_inswapper_128":
                row["runtime_path"] = str(paths["drive"] / "models" / "shared" / "insightface" / "missing.onnx")
        reactor_missing = prepare_identity_benchmark(
            repo_root,
            drive_root=paths["drive"],
            candidate=CANDIDATE_REACTOR,
            scenario="S1_near_front_portrait",
            character_id=reg.character.character_id,
            runtime_prepared_root=paths["prepared"],
            comfyui_input_dir=paths["input"],
            bundle_models=models_no_swap,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            require_models=True,
            require_nodes=True,
            allow_benchmark=True,
        )
        _assert_false("reactor missing inswapper", reactor_missing.ok)
        _assert_true(
            "inswapper listed",
            "reactor_inswapper_128" in reactor_missing.missing_models,
        )
        _pass(results, "ReActor missing inswapper fails closed (no auto-download)")

        # --- ReActor Drive->runtime InsightFace bridge (Package 4.12 Case C) ---
        canonical_insight = default_canonical_insightface_dir(
            paths["drive"] / "models" / "shared"
        )
        runtime_inswapper = reactor_runtime_inswapper_path(paths["comfy"])
        _assert_false("bridge absent initially", runtime_inswapper.exists())
        dep_no_bridge = assess_identity_benchmark_dependencies(
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            candidate=CANDIDATE_REACTOR,
        )
        _assert_true(
            "canonical present without bridge",
            dep_no_bridge["candidates"][CANDIDATE_REACTOR]["detail"]["canonical_inswapper_present"],
        )
        _assert_false(
            "runtime not verified without bridge",
            dep_no_bridge["candidates"][CANDIDATE_REACTOR]["detail"]["reactor_runtime_inswapper_verified"],
        )
        _assert_false(
            "candidate not ready without bridge",
            dep_no_bridge["candidates"][CANDIDATE_REACTOR]["ready"],
        )
        prep_no_bridge = prepare_identity_benchmark(
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
            require_models=True,
            require_nodes=True,
            allow_benchmark=True,
        )
        _assert_false("prepare fails without runtime bridge", prep_no_bridge.ok)
        _assert_true(
            "reports runtime missing",
            "reactor_inswapper_128" in prep_no_bridge.missing_models,
        )
        _pass(results, "Canonical present + runtime bridge absent -> candidate not ready")

        bridge1 = ensure_reactor_insightface_bridge(
            comfyui_runtime=paths["comfy"],
            canonical_insightface_dir=canonical_insight,
            dry_run=False,
            require_inswapper=True,
        )
        _assert_true(f"bridge create ok ({bridge1.errors})", bridge1.ok)
        _assert_true("runtime inswapper exists after bridge", runtime_inswapper.exists())
        _assert_true("inswapper verified after bridge", bridge1.inswapper_verified)
        _pass(results, "Canonical exists + runtime bridge absent -> setup creates valid bridge")

        bridge2 = ensure_reactor_insightface_bridge(
            comfyui_runtime=paths["comfy"],
            canonical_insightface_dir=canonical_insight,
            dry_run=False,
            require_inswapper=True,
        )
        _assert_true("bridge idempotent ok", bridge2.ok)
        _assert_true(
            "idempotent unchanged/create only",
            all(a.action in {"unchanged", "create"} for a in bridge2.actions)
            or not bridge2.actions
            or any(a.action == "unchanged" for a in bridge2.actions),
        )
        _pass(results, "Repeated bridge setup is idempotent")

        # Stale/broken runtime link -> repaired
        if runtime_inswapper.is_symlink() or runtime_inswapper.parent.is_symlink():
            stale_target = paths["drive"] / "models" / "shared" / "insightface" / "stale_missing.onnx"
            link_path = runtime_inswapper
            if runtime_inswapper.parent.is_symlink():
                # Whole-dir bridge: break by replacing dir symlink with stale file link slot
                import os

                insight_runtime = runtime_inswapper.parent
                insight_runtime.unlink()
                insight_runtime.mkdir(parents=True, exist_ok=True)
                try:
                    os.symlink(str(stale_target), str(runtime_inswapper))
                except OSError:
                    runtime_inswapper.write_bytes(b"wrong-inswapper-bytes")
            else:
                import os

                runtime_inswapper.unlink()
                try:
                    os.symlink(str(stale_target), str(runtime_inswapper))
                except OSError:
                    runtime_inswapper.write_bytes(b"wrong-inswapper-bytes")
        else:
            runtime_inswapper.unlink(missing_ok=True)
            runtime_inswapper.write_bytes(b"wrong-inswapper-bytes")

        bridge_repair = ensure_reactor_insightface_bridge(
            comfyui_runtime=paths["comfy"],
            canonical_insightface_dir=canonical_insight,
            dry_run=False,
            require_inswapper=True,
        )
        _assert_true(f"bridge repair ok ({bridge_repair.errors})", bridge_repair.ok)
        _assert_true("repaired matches canonical", bridge_repair.inswapper_verified)
        _pass(results, "Stale/broken runtime link repaired")

        # Canonical missing -> fail closed
        missing_canonical_dir = paths["drive"] / "models" / "shared" / "insightface_missing"
        bridge_missing = ensure_reactor_insightface_bridge(
            comfyui_runtime=paths["comfy"],
            canonical_insightface_dir=missing_canonical_dir,
            dry_run=False,
            require_inswapper=True,
        )
        _assert_false("bridge fails when canonical missing", bridge_missing.ok)
        models_no_canonical = [dict(m) for m in models]
        for row in models_no_canonical:
            if row.get("name") == "reactor_inswapper_128":
                row["runtime_path"] = str(missing_canonical_dir / "inswapper_128.onnx")
        present_m, missing_m, _ = assess_reactor_model_readiness(
            bundle_models=models_no_canonical,
            comfyui_runtime=paths["comfy"],
        )
        _assert_true("canonical missing listed", "reactor_inswapper_128" in missing_m)
        _pass(results, "Canonical inswapper missing -> fail closed / candidate not ready")

        # Runtime points at wrong file -> checker refuses
        wrong = paths["comfy"] / "models" / "insightface" / "inswapper_128.onnx"
        # Ensure a real directory with a wrong file (not bridged to canonical)
        insight_rt = paths["comfy"] / "models" / "insightface"
        if insight_rt.is_symlink():
            insight_rt.unlink()
            insight_rt.mkdir(parents=True, exist_ok=True)
        if wrong.exists() or wrong.is_symlink():
            wrong.unlink()
        wrong.write_bytes(b"totally-wrong-inswapper")
        dep_wrong = assess_identity_benchmark_dependencies(
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            candidate=CANDIDATE_REACTOR,
        )
        _assert_false(
            "wrong runtime file not ready",
            dep_wrong["candidates"][CANDIDATE_REACTOR]["ready"],
        )
        _assert_true(
            "wrong file status mismatch",
            dep_wrong["candidates"][CANDIDATE_REACTOR]["detail"]["reactor_runtime_inswapper_status"]
            in {"RUNTIME_SIZE_MISMATCH", "RUNTIME_SHA256_MISMATCH"},
        )
        _pass(results, "Runtime-visible asset points to wrong file -> checker refuses readiness")

        # Restore valid bridge for remaining happy-path tests
        if wrong.exists() or wrong.is_symlink():
            wrong.unlink()
        if insight_rt.is_dir() and not insight_rt.is_symlink():
            shutil.rmtree(insight_rt)
        bridge_ok = ensure_reactor_insightface_bridge(
            comfyui_runtime=paths["comfy"],
            canonical_insightface_dir=canonical_insight,
            dry_run=False,
            require_inswapper=True,
        )
        _assert_true(f"restore bridge ({bridge_ok.errors})", bridge_ok.ok)
        dep_bridged = assess_identity_benchmark_dependencies(
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            candidate=CANDIDATE_REACTOR,
        )
        _assert_true(
            "reactor ready with valid bridge",
            dep_bridged["candidates"][CANDIDATE_REACTOR]["ready"],
        )
        _assert_true(
            "runtime verified label",
            dep_bridged["candidates"][CANDIDATE_REACTOR]["detail"]["reactor_runtime_inswapper_verified"],
        )
        _pass(results, "Valid canonical + valid runtime bridge -> ReActor readiness passes")

        # ReActor prepare with present node + insightface + inswapper + runtime bridge
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
            drive_prepared_root=paths["drive_prepared"],
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
        bound_wf = json.loads(
            (Path(prep.prepared_dir) / f"{prep.preparation_id}.workflow.json").read_text(encoding="utf-8")
        )
        _assert_equal(
            "prepared reactor structural",
            assert_identity_benchmark_graph(bound_wf, CANDIDATE_REACTOR),
            [],
        )
        load = next(n for n in bound_wf["nodes"] if n.get("type") == "LoadImage")
        pos = next(
            n
            for n in bound_wf["nodes"]
            if n.get("type") == "CLIPTextEncode" and str(n.get("id")) == "3"
        )
        sampler = next(n for n in bound_wf["nodes"] if n.get("type") == "KSampler")
        _assert_equal("bound face filename", load["widgets_values"][0], prep.staged_face_filename)
        _assert_equal("bound prompt", pos["widgets_values"][0], prep.positive_prompt)
        _assert_equal("bound seed", sampler["widgets_values"][0], 135791357)
        _assert_equal("bound seed mode", sampler["widgets_values"][1], "fixed")
        _pass(results, "ReActor prepare binds face/prompt/seed on executable graph")

        prep_log = preparations_log_path(paths["drive"])
        index_row = find_by_preparation_id(prep_log, prep.preparation_id)
        _assert_true("identity prep indexed", index_row is not None)
        _assert_equal("index kind", index_row.get("preparation_kind"), PREPARATION_KIND_IDENTITY_BENCHMARK)
        _assert_true("index benchmark_run", index_row.get("benchmark_run") is True)
        drive_prep_dir = paths["drive_prepared"] / prep.preparation_id
        _assert_true("drive mirror dir", drive_prep_dir.is_dir())
        _assert_true(
            "archived face mirrored",
            (drive_prep_dir / "benchmark_source" / "primary_face.png").is_file(),
        )
        _pass(results, "Identity benchmark prep appends standard preparation index + Drive mirror")

        prep_s1 = prepare_identity_benchmark(
            repo_root,
            drive_root=paths["drive"],
            candidate=CANDIDATE_REACTOR,
            scenario="S1",
            character_id=reg.character.character_id,
            runtime_prepared_root=paths["prepared"],
            comfyui_input_dir=paths["input"],
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            drive_prepared_root=paths["drive_prepared"],
            require_models=True,
            require_nodes=True,
            allow_benchmark=True,
            seed=42424242,
        )
        _assert_true("shorthand S1 prep", prep_s1.ok)
        _assert_equal("shorthand maps canonical", prep_s1.scenario, "S1_near_front_portrait")
        _pass(results, "Scenario shorthand S1 maps to S1_near_front_portrait")

        _assert_equal("normalize S2", normalize_scenario_id("S2"), "S2_head_angle_pose")
        _assert_equal(
            "canonical unchanged",
            normalize_scenario_id("S3_expression_change"),
            "S3_expression_change",
        )
        _assert_true("invalid shorthand closed", normalize_scenario_id("S9") is None)
        _pass(results, "Scenario shorthand + canonical IDs validated")

        bad_scenario = prepare_identity_benchmark(
            repo_root,
            drive_root=paths["drive"],
            candidate=CANDIDATE_REACTOR,
            scenario="S9",
            character_id=reg.character.character_id,
            runtime_prepared_root=paths["prepared"],
            comfyui_input_dir=paths["input"],
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            drive_prepared_root=paths["drive_prepared"],
            require_models=False,
            require_nodes=True,
            allow_benchmark=True,
        )
        _assert_false("invalid scenario prep", bad_scenario.ok)
        _pass(results, "Invalid scenario shorthand fails closed")

        # Backfill: strip index + drive mirror, recover from runtime tree only
        shutil.rmtree(drive_prep_dir, ignore_errors=True)
        kept_lines = [
            line
            for line in prep_log.read_text(encoding="utf-8").splitlines()
            if prep.preparation_id not in line
        ]
        prep_log.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""), encoding="utf-8")
        _assert_true("index removed for backfill test", find_by_preparation_id(prep_log, prep.preparation_id) is None)
        backfill = backfill_identity_benchmark_preparation(
            drive_root=paths["drive"],
            preparation_id=prep.preparation_id,
            runtime_prepared_dir=Path(prep.prepared_dir),
            drive_prepared_root=paths["drive_prepared"],
        )
        _assert_true(f"backfill ok ({backfill.errors})", backfill.ok)
        _assert_true("backfill re-indexed", find_by_preparation_id(prep_log, prep.preparation_id) is not None)
        _assert_true("backfill drive mirror", drive_prep_dir.is_dir())
        _pass(results, "Backfill recovers runtime-only identity benchmark prep into index + Drive")

        # Backfill refuses when workflow file no longer matches prepared_workflow_hash
        orphan_dir = paths["prepared"] / prep.preparation_id
        wf_path = orphan_dir / f"{prep.preparation_id}.workflow.json"
        meta_path = orphan_dir / f"{prep.preparation_id}.metadata.json"
        shutil.rmtree(drive_prep_dir, ignore_errors=True)
        kept_lines = [
            line
            for line in prep_log.read_text(encoding="utf-8").splitlines()
            if prep.preparation_id not in line
        ]
        prep_log.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""), encoding="utf-8")
        tampered = json.loads(wf_path.read_text(encoding="utf-8"))
        nodes = tampered.get("nodes") or []
        load = next(n for n in nodes if isinstance(n, dict) and n.get("type") == "LoadImage")
        widgets = list(load.get("widgets_values") or ["face.png", "image"])
        widgets[0] = "tampered_face_after_prepare.png"
        load["widgets_values"] = widgets
        wf_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
        mismatch = backfill_identity_benchmark_preparation(
            drive_root=paths["drive"],
            preparation_id=prep.preparation_id,
            runtime_prepared_dir=orphan_dir,
            drive_prepared_root=paths["drive_prepared"],
        )
        _assert_false("tampered workflow backfill refused", mismatch.ok)
        _assert_true(
            "hash mismatch message",
            any("hash mismatch" in e.lower() for e in mismatch.errors),
        )
        _assert_false("no drive mirror after mismatch", drive_prep_dir.is_dir())
        _assert_true(
            "no index after mismatch",
            find_by_preparation_id(prep_log, prep.preparation_id) is None,
        )
        _pass(results, "Backfill refuses modified workflow (hash mismatch; no Drive/index write)")

        # Restore matching workflow from Drive-less runtime by re-writing from metadata hash path:
        # recreate a clean prep for missing-hash refusal (separate orphan).
        missing_hash_prep = prepare_identity_benchmark(
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
            drive_prepared_root=paths["drive_prepared"],
            require_models=True,
            require_nodes=True,
            allow_benchmark=True,
            seed=55555555,
        )
        _assert_true("missing-hash fixture prep", missing_hash_prep.ok)
        miss_drive = paths["drive_prepared"] / missing_hash_prep.preparation_id
        miss_runtime = Path(missing_hash_prep.prepared_dir)
        miss_meta = miss_runtime / f"{missing_hash_prep.preparation_id}.metadata.json"
        shutil.rmtree(miss_drive, ignore_errors=True)
        kept_lines = [
            line
            for line in prep_log.read_text(encoding="utf-8").splitlines()
            if missing_hash_prep.preparation_id not in line
        ]
        prep_log.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""), encoding="utf-8")
        meta_obj = json.loads(miss_meta.read_text(encoding="utf-8"))
        del meta_obj["prepared_workflow_hash"]
        miss_meta.write_text(json.dumps(meta_obj, indent=2) + "\n", encoding="utf-8")
        missing = backfill_identity_benchmark_preparation(
            drive_root=paths["drive"],
            preparation_id=missing_hash_prep.preparation_id,
            runtime_prepared_dir=miss_runtime,
            drive_prepared_root=paths["drive_prepared"],
        )
        _assert_false("missing hash backfill refused", missing.ok)
        _assert_true(
            "missing hash message",
            any("prepared_workflow_hash" in e and "missing" in e.lower() for e in missing.errors),
        )
        _assert_false("no drive mirror after missing hash", miss_drive.is_dir())
        _assert_true(
            "no index after missing hash",
            find_by_preparation_id(prep_log, missing_hash_prep.preparation_id) is None,
        )
        _pass(results, "Backfill refuses missing prepared_workflow_hash (no Drive/index write)")

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
            drive_prepared_root=paths["drive_prepared"],
            require_models=False,
            require_nodes=True,
            allow_benchmark=True,
        )
        _assert_true(f"faceid prep plumbing ({faceid_prep.errors})", faceid_prep.ok)
        faceid_bound = json.loads(
            (
                Path(faceid_prep.prepared_dir) / f"{faceid_prep.preparation_id}.workflow.json"
            ).read_text(encoding="utf-8")
        )
        _assert_equal(
            "prepared faceid structural",
            assert_identity_benchmark_graph(faceid_bound, CANDIDATE_FACEID),
            [],
        )
        _pass(results, "FaceID prepare binds executable FaceID graph (allow-missing-models)")

        # Dependency assessor does not claim quality PASS
        dep = assess_identity_benchmark_dependencies(
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
        )
        _assert_true("dep quality disclaimer", "not a visual" in str(dep.get("quality_claim") or "").lower())
        _pass(results, "Dependency assessor is structural/readiness only (no quality PASS)")

        # --- FaceID integrity verification (deterministic registry metadata) ---
        missing_models = _faceid_integrity_models(
            bundle.models,
            paths["drive"],
            bin_content=None,
            lora_content=None,
            clip_content=None,
        )
        _, not_ready, integrity = verify_required_model_assets(
            missing_models,
            [
                "ipadapter_faceid_plusv2_sd15",
                "ipadapter_faceid_plusv2_sd15_lora",
                "clip_vision_sd15",
            ],
        )
        _assert_equal("missing count", len(not_ready), 3)
        _assert_equal(
            "missing bin status",
            integrity["ipadapter_faceid_plusv2_sd15"]["status"],
            INTEGRITY_MISSING,
        )
        dep_missing = assess_identity_benchmark_dependencies(
            bundle_models=missing_models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
        )
        _assert_false("missing assets not ready", dep_missing["candidates"][CANDIDATE_FACEID]["ready"])
        _pass(results, "FaceID missing asset -> not ready (MISSING)")

        wrong_size_models = _faceid_integrity_models(
            bundle.models,
            paths["drive"],
            bin_size_override=999,
        )
        _, not_ready_size, integrity_size = verify_required_model_assets(
            wrong_size_models,
            ["ipadapter_faceid_plusv2_sd15"],
        )
        _assert_true("wrong size not ready", "ipadapter_faceid_plusv2_sd15" in not_ready_size)
        _assert_equal(
            "wrong size status",
            integrity_size["ipadapter_faceid_plusv2_sd15"]["status"],
            INTEGRITY_SIZE_MISMATCH,
        )
        _pass(results, "FaceID wrong-size asset -> SIZE MISMATCH -> not ready")

        wrong_hash_models = _faceid_integrity_models(bundle.models, paths["drive"])
        for row in wrong_hash_models:
            if row.get("name") == "ipadapter_faceid_plusv2_sd15_lora":
                row["expected_sha256"] = _sha256_bytes(b"expected-not-actual")
        _, not_ready_sha, integrity_sha = verify_required_model_assets(
            wrong_hash_models,
            ["ipadapter_faceid_plusv2_sd15_lora"],
        )
        _assert_true("wrong sha not ready", "ipadapter_faceid_plusv2_sd15_lora" in not_ready_sha)
        _assert_equal(
            "wrong sha status",
            integrity_sha["ipadapter_faceid_plusv2_sd15_lora"]["status"],
            INTEGRITY_SHA256_MISMATCH,
        )
        _pass(results, "FaceID wrong-content (matching size) -> SHA256 MISMATCH -> not ready")

        verified_models = _faceid_integrity_models(bundle.models, paths["drive"])
        ready_names, not_ready_ok, integrity_ok = verify_required_model_assets(
            verified_models,
            [
                "ipadapter_faceid_plusv2_sd15",
                "ipadapter_faceid_plusv2_sd15_lora",
                "clip_vision_sd15",
            ],
        )
        _assert_equal("verified count", len(ready_names), 3)
        _assert_equal("verified bin", integrity_ok["ipadapter_faceid_plusv2_sd15"]["status"], INTEGRITY_VERIFIED)
        _pass(results, "FaceID correct hash/size -> VERIFIED")

        dep_all_verified = assess_identity_benchmark_dependencies(
            bundle_models=verified_models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
        )
        _assert_true(
            "faceid ready when verified",
            dep_all_verified["candidates"][CANDIDATE_FACEID]["ready"],
        )
        _assert_true("case c ready when all verified", dep_all_verified["ready_for_case_c"])
        _pass(results, "All three FaceID assets VERIFIED -> FaceID candidate ready")

        one_bad_models = _faceid_integrity_models(bundle.models, paths["drive"], clip_content=None)
        dep_one_bad = assess_identity_benchmark_dependencies(
            bundle_models=one_bad_models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
        )
        _assert_false(
            "one invalid blocks faceid",
            dep_one_bad["candidates"][CANDIDATE_FACEID]["ready"],
        )
        _assert_false("one invalid blocks case c", dep_one_bad["ready_for_case_c"])
        _pass(results, "Any one invalid FaceID asset -> ready_for_case_c false")

        no_meta_row = verify_model_asset_integrity(
            {
                "name": "reactor_inswapper_128",
                "runtime_path": str(paths["inswapper"]),
                "filename": "inswapper_128.onnx",
            }
        )
        _assert_equal("no metadata status", no_meta_row["status"], INTEGRITY_PRESENT)
        _assert_true("no metadata verified", no_meta_row["verified"])
        _pass(results, "Registry entries without integrity metadata still presence-only")

        dep_reactor = assess_identity_benchmark_dependencies(
            bundle_models=one_bad_models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
        )
        _assert_true(
            "reactor unchanged when faceid invalid",
            dep_reactor["candidates"][CANDIDATE_REACTOR]["ready"],
        )
        _pass(results, "ReActor readiness unchanged (regression)")

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
