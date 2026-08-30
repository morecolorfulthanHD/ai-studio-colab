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
    append_identity_benchmark_record_if_absent,
    assert_identity_benchmark_graph,
    assess_identity_benchmark_dependencies,
    assess_reactor_model_readiness,
    backfill_identity_benchmark_preparation,
    format_identity_benchmark_report,
    is_benchmark_generation_metadata,
    load_identity_benchmark_records,
    normalize_scenario_id,
    prepare_identity_benchmark,
    restage_identity_benchmark_face,
    verify_model_asset_integrity,
    verify_required_model_assets,
)
from core.runtime.prepared_workflow_index import (
    append_preparation_record,
    find_by_preparation_id,
    preparations_log_path,
)
from core.runtime.reactor_model_bridge import (
    default_canonical_insightface_dir,
    ensure_reactor_insightface_bridge,
    reactor_glob_discovers_inswapper,
    reactor_runtime_inswapper_path,
    reactor_style_list_swap_models,
)
from core.runtime.faceid_model_bridge import (
    CLIP_VISION_CANONICAL_FILENAME,
    IPADAPTER_DISCOVERY_FILENAME,
    LORA_DISCOVERY_FILENAME,
    assess_faceid_pinned_resolver,
    default_canonical_clip_vision_dir,
    default_canonical_ipadapter_dir,
    default_canonical_lora_dir,
    ensure_faceid_runtime_bridge,
    runtime_clip_vision_path,
    runtime_ipadapter_discovery_path,
    runtime_lora_discovery_path,
)
from core.runtime.registry_loader import RegistryLoader


def _reactor_object_info(*, swap_models: list[str] | None = None, include_node: bool = True) -> dict:
    """Minimal ComfyUI object_info shaped like pinned ReActorFaceSwap INPUT_TYPES."""
    payload: dict = {
        "CheckpointLoaderSimple": {"input": {"required": {}}},
        "IPAdapterUnifiedLoaderFaceID": {"input": {"required": {}}},
        "IPAdapterFaceID": {"input": {"required": {}}},
    }
    if include_node:
        models = list(swap_models) if swap_models is not None else ["inswapper_128.onnx"]
        payload["ReActorFaceSwap"] = {
            "input": {
                "required": {
                    "enabled": ["BOOLEAN", {}],
                    "input_image": ["IMAGE"],
                    "swap_model": [models],
                }
            }
        }
    return payload


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


def _concurrent_append_worker(payload: dict) -> tuple[bool, bool]:
    """Picklable worker for ProcessPoolExecutor concurrent ledger appends."""
    from core.runtime.identity_benchmark import (
        IdentityBenchmarkRecord,
        append_identity_benchmark_record_if_absent,
    )

    record = IdentityBenchmarkRecord(
        candidate=str(payload["candidate"]),
        scenario=str(payload["scenario"]),
        character_id=str(payload["character_id"]),
        seed=int(payload["seed"]),
        preparation_id=str(payload["preparation_id"]),
        prompt_id=str(payload["prompt_id"]),
        output_node_id=str(payload["output_node_id"]),
        output_path=str(payload["output_path"]),
        output_sha256=str(payload["output_sha256"]),
        capture_idempotence_key=str(payload["idempotence_key"]),
        success=True,
    )
    return append_identity_benchmark_record_if_absent(
        Path(payload["ledger_path"]),
        record,
        idempotence_key=str(payload["idempotence_key"]),
    )


def _concurrent_evidence_worker(payload: dict) -> str:
    from core.runtime.generation_evidence_ledger import EvidenceLedger, EvidenceRecord

    prompt_id = str(payload["prompt_id"])
    EvidenceLedger(Path(payload["path"])).append(
        EvidenceRecord(
            prompt_id=prompt_id,
            output_node_id="9",
            local_sha256=str(payload["sha"]),
            drive_sha256=str(payload["sha"]),
            sync_status="verified",
            capability=str(payload.get("capability") or "txt2img"),
            snapshot_status=str(payload.get("snapshot_status") or ""),
            generation_id=str(payload.get("generation_id") or ""),
        )
    )
    return prompt_id


def _concurrent_index_worker(payload: dict) -> str:
    from core.runtime.generation_index import GenerationIndex, GenerationIndexRecord

    gid = str(payload["generation_id"])
    GenerationIndex(Path(payload["path"])).append(
        GenerationIndexRecord(
            generation_id=gid,
            dedupe_key=str(payload["dedupe_key"]),
            prompt_id=str(payload["prompt_id"]),
            output_node_id="9",
            capability=str(payload.get("capability") or "txt2img"),
            snapshot_status=str(payload.get("snapshot_status") or "snapshot_complete"),
            image_sha256=str(payload.get("image_sha256") or ""),
        )
    )
    return gid


def _concurrent_audit_worker(payload: dict) -> str:
    import json

    from core.runtime.jsonl_file_lock import append_jsonl_line

    action = str(payload["action"])
    append_jsonl_line(
        Path(payload["path"]),
        json.dumps({"action": action, "seq": int(payload["seq"])}, ensure_ascii=False),
    )
    return action


def _valid_jsonl_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


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


def _faceid_canonical_dirs(drive: Path) -> tuple[Path, Path, Path]:
    shared = drive / "models" / "shared"
    return (
        default_canonical_clip_vision_dir(shared),
        default_canonical_ipadapter_dir(shared),
        default_canonical_lora_dir(shared),
    )


def _ensure_faceid_test_bridges(comfy: Path, drive: Path) -> None:
    clip_dir, ipa_dir, lora_dir = _faceid_canonical_dirs(drive)
    ensure_reactor_insightface_bridge(
        comfyui_runtime=comfy,
        canonical_insightface_dir=default_canonical_insightface_dir(drive / "models" / "shared"),
        dry_run=False,
        require_inswapper=True,
    )
    bridge = ensure_faceid_runtime_bridge(
        comfyui_runtime=comfy,
        canonical_clip_vision_dir=clip_dir,
        canonical_ipadapter_dir=ipa_dir,
        canonical_lora_dir=lora_dir,
        dry_run=False,
    )
    if not bridge.ok:
        raise AssertionError(f"FaceID test bridge failed: {bridge.errors}")


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
            object_info_payload=_reactor_object_info(),
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
            object_info_payload=_reactor_object_info(),
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
        _assert_true(
            "glob discovers after file-level bridge",
            reactor_glob_discovers_inswapper(paths["comfy"]),
        )
        dep_bridged = assess_identity_benchmark_dependencies(
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            candidate=CANDIDATE_REACTOR,
            object_info_payload=_reactor_object_info(),
        )
        _assert_true(
            "reactor ready with valid bridge",
            dep_bridged["candidates"][CANDIDATE_REACTOR]["ready"],
        )
        _assert_true(
            "runtime verified label",
            dep_bridged["candidates"][CANDIDATE_REACTOR]["detail"]["reactor_runtime_inswapper_verified"],
        )
        _assert_true(
            "live swap option verified",
            dep_bridged["candidates"][CANDIDATE_REACTOR]["detail"]["live_swap_model_option_verified"],
        )
        _pass(results, "Valid canonical + valid runtime bridge -> ReActor readiness passes")

        # Live object_info must advertise inswapper — filesystem alone is insufficient
        dep_omit = assess_identity_benchmark_dependencies(
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            candidate=CANDIDATE_REACTOR,
            object_info_payload=_reactor_object_info(swap_models=["reswapper_128.onnx"]),
        )
        _assert_false(
            "omitted swap option not ready",
            dep_omit["candidates"][CANDIDATE_REACTOR]["ready"],
        )
        _assert_equal(
            "live option missing status",
            dep_omit["candidates"][CANDIDATE_REACTOR]["detail"]["live_swap_model_option_status"],
            "MISSING",
        )
        _pass(
            results,
            "Canonical + runtime valid but object_info omits inswapper_128.onnx -> not ready",
        )

        dep_wrong_name = assess_identity_benchmark_dependencies(
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            candidate=CANDIDATE_REACTOR,
            object_info_payload=_reactor_object_info(swap_models=["inswapper_128_fp16.onnx"]),
        )
        _assert_false(
            "wrong option name not ready",
            dep_wrong_name["candidates"][CANDIDATE_REACTOR]["ready"],
        )
        _pass(results, "Wrong live swap_model option/name -> candidate not ready")

        dep_no_node = assess_identity_benchmark_dependencies(
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            candidate=CANDIDATE_REACTOR,
            object_info_payload=_reactor_object_info(include_node=False),
        )
        _assert_false(
            "absent reactor node not ready",
            dep_no_node["candidates"][CANDIDATE_REACTOR]["ready"],
        )
        _pass(results, "ReActor node absent from object_info -> candidate not ready")

        dep_live_ok = assess_identity_benchmark_dependencies(
            bundle_models=models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            candidate=CANDIDATE_REACTOR,
            object_info_payload=_reactor_object_info(swap_models=["inswapper_128.onnx"]),
        )
        _assert_equal(
            "live option verified status",
            dep_live_ok["candidates"][CANDIDATE_REACTOR]["detail"]["live_swap_model_option_status"],
            "VERIFIED",
        )
        _assert_true(
            "live option verified ready",
            dep_live_ok["candidates"][CANDIDATE_REACTOR]["ready"],
        )
        _pass(results, "object_info advertises inswapper_128.onnx -> live option VERIFIED")

        # Directory symlink (prior bridge shape) must be converted to file-level for glob
        import os as _os

        insight_rt = paths["comfy"] / "models" / "insightface"
        if insight_rt.exists() or insight_rt.is_symlink():
            if insight_rt.is_symlink():
                insight_rt.unlink()
            elif insight_rt.is_dir():
                shutil.rmtree(insight_rt)
        dir_symlink_ok = False
        try:
            _os.symlink(str(canonical_insight), str(insight_rt), target_is_directory=True)
            dir_symlink_ok = insight_rt.is_symlink()
        except OSError:
            dir_symlink_ok = False

        if dir_symlink_ok:
            bridge_migrate = ensure_reactor_insightface_bridge(
                comfyui_runtime=paths["comfy"],
                canonical_insightface_dir=canonical_insight,
                dry_run=False,
                require_inswapper=True,
            )
            _assert_true(f"dir symlink migrated ({bridge_migrate.errors})", bridge_migrate.ok)
            _assert_false("insightface is real dir after migrate", insight_rt.is_symlink())
            _assert_true("glob after migrate", reactor_glob_discovers_inswapper(paths["comfy"]))
            from core.runtime.reactor_model_bridge import INSWAPPER_FILENAME as _INS

            _assert_true("basename listed", _INS in reactor_style_list_swap_models(paths["comfy"]))
            _pass(results, "Full Reset/Launch-style bridge recreates glob-discoverable runtime state")
        else:
            # Windows hosts without symlink privilege: recreate via file-level bridge path.
            bridge_recreate = ensure_reactor_insightface_bridge(
                comfyui_runtime=paths["comfy"],
                canonical_insightface_dir=canonical_insight,
                dry_run=False,
                require_inswapper=True,
            )
            _assert_true(f"recreate after wipe ({bridge_recreate.errors})", bridge_recreate.ok)
            _assert_false("insightface not a dir symlink", insight_rt.is_symlink())
            _assert_true("glob after recreate", reactor_glob_discovers_inswapper(paths["comfy"]))
            _pass(results, "Full Reset/Launch-style bridge recreates glob-discoverable runtime state")

        bridge_again = ensure_reactor_insightface_bridge(
            comfyui_runtime=paths["comfy"],
            canonical_insightface_dir=canonical_insight,
            dry_run=False,
            require_inswapper=True,
        )
        _assert_true("repeated launch idempotent", bridge_again.ok)
        _pass(results, "Repeated launch/bridge remains idempotent")

        # Bridge before enumeration: setup then glob (ordering contract)
        _assert_true(
            "bridge precedes enumeration contract",
            bridge_again.reactor_glob_discoverable and reactor_glob_discovers_inswapper(paths["comfy"]),
        )
        _pass(results, "Bridge/setup occurs before model enumeration (glob sees inswapper)")

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
            object_info_payload=_reactor_object_info(),
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
            object_info_payload=_reactor_object_info(),
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
        _pass(results, "FaceID correct hash/size -> VERIFIED (canonical only)")

        # A/G: canonical VERIFIED but runtime discovery missing -> NOT ready (false-positive guard)
        dep_canonical_only = assess_identity_benchmark_dependencies(
            bundle_models=verified_models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            comfyui_runtime=paths["comfy"],
            object_info_payload=_reactor_object_info(),
        )
        _assert_false(
            "faceid not ready without runtime bridge",
            dep_canonical_only["candidates"][CANDIDATE_FACEID]["ready"],
        )
        _assert_false(
            "resolver not verified without bridge",
            dep_canonical_only["candidates"][CANDIDATE_FACEID]["detail"]["pinned_resolver_verified"],
        )
        _pass(results, "Canonical CLIP valid but runtime discovery missing -> FaceID NOT ready")

        # B: runtime file at wrong discovery name -> NOT ready
        wrong_name = paths["comfy"] / "models" / "clip_vision" / "wrong-clip-name.safetensors"
        wrong_name.parent.mkdir(parents=True, exist_ok=True)
        wrong_name.write_bytes((paths["drive"] / "models/shared/clip_vision" / CLIP_VISION_CANONICAL_FILENAME).read_bytes())
        dep_wrong_name = assess_identity_benchmark_dependencies(
            bundle_models=verified_models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            comfyui_runtime=paths["comfy"],
            object_info_payload=_reactor_object_info(),
        )
        _assert_false("wrong clip discovery name not ready", dep_wrong_name["candidates"][CANDIDATE_FACEID]["ready"])
        wrong_name.unlink(missing_ok=True)
        _pass(results, "Runtime CLIP at wrong location/name -> NOT ready")

        # C/E/F: deterministic bridge + reset/recreate + resolver VERIFIED
        _ensure_faceid_test_bridges(paths["comfy"], paths["drive"])
        resolver_ok = assess_faceid_pinned_resolver(paths["comfy"])
        _assert_true("resolver verified with bridge", bool(resolver_ok.get("verified")))
        _pass(results, "Correct deterministic runtime bridge -> pinned resolver VERIFIED")

        clip_bridge = runtime_clip_vision_path(paths["comfy"])
        ipa_bridge = runtime_ipadapter_discovery_path(paths["comfy"])
        lora_bridge = runtime_lora_discovery_path(paths["comfy"])
        for bridge_path in (clip_bridge, ipa_bridge, lora_bridge):
            if bridge_path.is_symlink() or bridge_path.is_file():
                bridge_path.unlink(missing_ok=True)
        _assert_false("bridges removed after reset sim", clip_bridge.exists())
        bridge_recreate = ensure_faceid_runtime_bridge(
            comfyui_runtime=paths["comfy"],
            canonical_clip_vision_dir=_faceid_canonical_dirs(paths["drive"])[0],
            canonical_ipadapter_dir=_faceid_canonical_dirs(paths["drive"])[1],
            canonical_lora_dir=_faceid_canonical_dirs(paths["drive"])[2],
            dry_run=False,
        )
        _assert_true(f"bridge recreate ok ({bridge_recreate.errors})", bridge_recreate.ok)
        _pass(results, "Full Reset removes ephemeral bridge; recreate restores discovery")

        install_sh = (repo_root / "core/comfyui/install.sh").read_text(encoding="utf-8")
        faceid_pos = install_sh.find("ensure_faceid_runtime_bridge.py")
        complete_pos = install_sh.find('phase "Complete"')
        _assert_true("install.sh wires FaceID bridge", faceid_pos >= 0)
        _assert_true("FaceID bridge before Complete phase", faceid_pos < complete_pos)
        _pass(results, "Full Launch ordering: FaceID bridge before ComfyUI Complete phase")

        # D: canonical/runtime SHA mismatch after bridge -> NOT ready
        canonical_ipa = (
            paths["drive"] / "models/shared/ipadapter/ip-adapter-faceid-plusv2_sd15.bin"
        )
        canonical_ipa_good = canonical_ipa.read_bytes()
        tampered = runtime_ipadapter_discovery_path(paths["comfy"])
        if tampered.is_symlink() or tampered.is_file():
            tampered.unlink()
        tampered.write_bytes(b"tampered-ipadapter-runtime")
        dep_tampered = assess_identity_benchmark_dependencies(
            bundle_models=verified_models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            comfyui_runtime=paths["comfy"],
            object_info_payload=_reactor_object_info(),
        )
        _assert_false("tampered runtime not ready", dep_tampered["candidates"][CANDIDATE_FACEID]["ready"])
        canonical_ipa.write_bytes(canonical_ipa_good)
        bridge_repair_d = ensure_faceid_runtime_bridge(
            comfyui_runtime=paths["comfy"],
            canonical_clip_vision_dir=_faceid_canonical_dirs(paths["drive"])[0],
            canonical_ipadapter_dir=_faceid_canonical_dirs(paths["drive"])[1],
            canonical_lora_dir=_faceid_canonical_dirs(paths["drive"])[2],
            dry_run=False,
        )
        _assert_true(f"bridge repair after tamper ({bridge_repair_d.errors})", bridge_repair_d.ok)
        _pass(results, "Canonical/runtime size or SHA mismatch -> NOT ready")

        dep_all_verified = assess_identity_benchmark_dependencies(
            bundle_models=verified_models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            comfyui_runtime=paths["comfy"],
            object_info_payload=_reactor_object_info(),
        )
        _assert_true(
            "faceid ready when verified + bridge",
            dep_all_verified["candidates"][CANDIDATE_FACEID]["ready"],
        )
        _assert_true(
            "benchmark execution explicitly not tested",
            dep_all_verified["candidates"][CANDIDATE_FACEID]["detail"]["benchmark_execution_tested"] is False,
        )
        _assert_true("case c ready when all verified", dep_all_verified["ready_for_case_c"])
        _pass(results, "FaceID assets VERIFIED + runtime discovery -> candidate ready")

        one_bad_models = _faceid_integrity_models(bundle.models, paths["drive"], clip_content=None)
        dep_one_bad = assess_identity_benchmark_dependencies(
            bundle_models=one_bad_models,
            bundle_nodes=list(bundle.nodes),
            comfyui_custom_nodes=paths["comfy"] / "custom_nodes",
            comfyui_runtime=paths["comfy"],
            object_info_payload=_reactor_object_info(),
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
            comfyui_runtime=paths["comfy"],
            object_info_payload=_reactor_object_info(),
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

        # --- Identity benchmark execution capture / recovery ---
        from core.runtime.identity_benchmark_capture import (
            benchmark_idempotence_key,
            capture_identity_benchmark_execution,
            ensure_durable_benchmark_artifact,
            is_identity_benchmark_provenance,
            recover_identity_benchmarks_from_history,
        )
        from core.runtime.workflow_provenance import ExecutionProvenance, hash_ui_workflow

        # Use prep_s1 (Drive/index intact). Earlier backfill-mismatch tests deliberately
        # strip Drive/index for `prep` and leave a tampered runtime workflow.
        capture_prep = prep_s1
        prep_wf_path = Path(capture_prep.runtime_prepared_dir) / f"{capture_prep.preparation_id}.workflow.json"
        prep_wf = json.loads(prep_wf_path.read_text(encoding="utf-8"))
        ai_extra = ((prep_wf.get("extra") or {}).get("ai_studio") or {})
        _assert_equal("embedded prep id", ai_extra.get("preparation_id"), capture_prep.preparation_id)
        _assert_true("embedded benchmark_run", ai_extra.get("benchmark_run") is True)
        _assert_equal(
            "embedded kind",
            ai_extra.get("preparation_kind"),
            PREPARATION_KIND_IDENTITY_BENCHMARK,
        )
        _assert_equal(
            "embedded character_reference_path",
            ai_extra.get("character_reference_path"),
            "benchmark_source/primary_face.png",
        )
        _assert_true("embedded character_face_sha256", bool(ai_extra.get("character_face_sha256")))
        _pass(results, "Prepared identity workflow embeds durable ai_studio provenance")

        out_file = paths["comfy"] / "output" / "idbench_s1.png"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"IDBENCH-S1-OUTPUT")
        out_sha = file_sha256(out_file)
        (paths["drive"] / "outputs").mkdir(parents=True, exist_ok=True)
        evidence_path = paths["drive"] / "logs" / "autosync" / "evidence.jsonl"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        prov = ExecutionProvenance(
            preparation_id=capture_prep.preparation_id,
            preparation_kind=PREPARATION_KIND_IDENTITY_BENCHMARK,
            capability="identity_benchmark",
            workflow_identifier="reference/identity_reactor_benchmark",
            prepared_workflow_hash=str(ai_extra.get("prepared_workflow_hash") or ""),
            seed=int(capture_prep.seed),
            save_prefix="ai_studio_idbench_reactor",
        )
        _assert_true("prov is benchmark", is_identity_benchmark_provenance(prov, prep_wf))
        cap1 = capture_identity_benchmark_execution(
            drive_root=paths["drive"],
            ledger_path=ledger,
            prompt_id="prompt-idbench-1",
            output_node_id="9",
            output_path=out_file,
            output_sha256=out_sha,
            provenance=prov,
            ui_workflow=prep_wf,
            local_path=str(out_file),
            evidence_path=evidence_path,
            drive_output_dir=paths["drive"] / "outputs",
        )
        _assert_true(f"capture ok ({cap1.errors})", cap1.ok and not cap1.skipped_duplicate)
        rows2 = load_identity_benchmark_records(ledger)
        _assert_true("ledger has capture", len(rows2) >= 2)
        captured = [r for r in rows2 if r.get("prompt_id") == "prompt-idbench-1"]
        _assert_equal("one capture row", len(captured), 1)
        _assert_equal("candidate preserved", captured[0].get("candidate"), CANDIDATE_REACTOR)
        _assert_equal("scenario preserved", captured[0].get("scenario"), "S1_near_front_portrait")
        _assert_equal("character preserved", captured[0].get("character_id"), reg.character.character_id)
        _assert_equal("prep preserved", captured[0].get("preparation_id"), capture_prep.preparation_id)
        _assert_equal("executed seed", int(captured[0].get("seed")), int(capture_prep.seed))
        _assert_equal("output sha", captured[0].get("output_sha256"), out_sha)
        _assert_equal("human review pending", captured[0].get("human_review_status"), "pending")
        _assert_true("benchmark_run flag", captured[0].get("benchmark_run") is True)
        durable1 = Path(str(captured[0].get("output_path") or ""))
        _assert_true("durable path under Drive outputs", str(paths["drive"] / "outputs") in str(durable1))
        _assert_true("durable file exists", durable1.is_file())
        _assert_false("ledger path is not runtime output", str(paths["comfy"] / "output") in str(durable1))
        _pass(results, "Successful prepared benchmark execution -> one ledger record with provenance")

        cap_dup = capture_identity_benchmark_execution(
            drive_root=paths["drive"],
            ledger_path=ledger,
            prompt_id="prompt-idbench-1",
            output_node_id="9",
            output_path=out_file,
            output_sha256=out_sha,
            provenance=prov,
            ui_workflow=prep_wf,
            evidence_path=evidence_path,
            drive_output_dir=paths["drive"] / "outputs",
        )
        _assert_true("dup ok", cap_dup.ok and cap_dup.skipped_duplicate)
        _assert_equal(
            "no duplicate after re-capture",
            len([r for r in load_identity_benchmark_records(ledger) if r.get("prompt_id") == "prompt-idbench-1"]),
            1,
        )
        _pass(results, "Capture/recovery idempotent (same prompt+node+sha)")

        # Second distinct execution of same prep
        out2 = paths["comfy"] / "output" / "idbench_s1_b.png"
        out2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"IDBENCH-S1-OUTPUT-B")
        sha2 = file_sha256(out2)
        cap2 = capture_identity_benchmark_execution(
            drive_root=paths["drive"],
            ledger_path=ledger,
            prompt_id="prompt-idbench-2",
            output_node_id="9",
            output_path=out2,
            output_sha256=sha2,
            provenance=prov,
            ui_workflow=prep_wf,
            evidence_path=evidence_path,
            drive_output_dir=paths["drive"] / "outputs",
        )
        _assert_true(f"second exec ({cap2.errors})", cap2.ok and not cap2.skipped_duplicate)
        _assert_equal(
            "two distinct executions",
            len(
                [
                    r
                    for r in load_identity_benchmark_records(ledger)
                    if r.get("prompt_id") in {"prompt-idbench-1", "prompt-idbench-2"}
                ]
            ),
            2,
        )
        _pass(results, "Two real executions of same prep remain distinct")

        # History recovery (missed watcher) + durable Drive artifact
        ledger_recover = paths["drive"] / "logs" / "identity_benchmark_recover.jsonl"
        hist_entry = {
            "prompt": [
                0,
                "client",
                {
                    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ai_studio_idbench_reactor", "images": ["8", 0]}},
                    "3": {"class_type": "KSampler", "inputs": {"seed": int(capture_prep.seed), "steps": 20, "cfg": 7, "sampler_name": "euler", "scheduler": "normal", "denoise": 1}},
                },
                {"extra_pnginfo": {"workflow": prep_wf}},
                ["9"],
            ],
            "outputs": {
                "9": {"images": [{"filename": "idbench_missed.png", "subfolder": "", "type": "output"}]}
            },
            "status": {"completed": True, "status_str": "success"},
        }
        missed = paths["comfy"] / "output" / "idbench_missed.png"
        missed.write_bytes(b"\x89PNG\r\n\x1a\n" + b"MISSED-HISTORY")
        history = {"prompt-missed-1": hist_entry}
        rec1 = recover_identity_benchmarks_from_history(
            drive_root=paths["drive"],
            ledger_path=ledger_recover,
            comfy_output_dir=paths["comfy"] / "output",
            base_url="http://127.0.0.1:8188",
            history=history,
            drive_output_dir=paths["drive"] / "outputs",
            evidence_path=evidence_path,
        )
        _assert_true(f"recovery ok ({rec1.get('errors')})", rec1.get("ok") and rec1.get("captured") == 1)
        recovered_rows = load_identity_benchmark_records(ledger_recover)
        _assert_equal("one recovered row", len(recovered_rows), 1)
        recovered_out = Path(str(recovered_rows[0].get("output_path") or ""))
        _assert_true("recovery durable under Drive", str(paths["drive"] / "outputs") in str(recovered_out))
        _assert_true("recovery durable exists", recovered_out.is_file())
        _assert_equal("recovery sha", recovered_rows[0].get("output_sha256"), file_sha256(recovered_out))
        _pass(results, "Missed-history recovery creates/verifies durable Drive output")

        # Reuse existing verified Drive copy without duplication
        before_files = {p.name for p in (paths["drive"] / "outputs").glob("identity_benchmark_*")}
        rec_reuse = recover_identity_benchmarks_from_history(
            drive_root=paths["drive"],
            ledger_path=ledger_recover,
            comfy_output_dir=paths["comfy"] / "output",
            base_url="http://127.0.0.1:8188",
            history=history,
            drive_output_dir=paths["drive"] / "outputs",
            evidence_path=evidence_path,
        )
        _assert_equal("reuse captured", rec_reuse.get("captured"), 0)
        _assert_equal("reuse duplicates", rec_reuse.get("duplicates"), 1)
        after_files = {p.name for p in (paths["drive"] / "outputs").glob("identity_benchmark_*")}
        _assert_equal("no extra Drive copies on reuse", before_files, after_files)
        _pass(results, "Verified Drive copy reused without duplication; recovery idempotent")

        # H: failed benchmark execution (no outputs) must not create a success ledger row
        failed_faceid_hist = {
            "prompt-faceid-s1-failed": {
                "prompt": hist_entry["prompt"],
                "outputs": {},
                "status": {"completed": False, "status_str": "error"},
            }
        }
        ledger_failed = paths["drive"] / "logs" / "identity_benchmark_failed_faceid.jsonl"
        rec_failed = recover_identity_benchmarks_from_history(
            drive_root=paths["drive"],
            ledger_path=ledger_failed,
            comfy_output_dir=paths["comfy"] / "output",
            base_url="http://127.0.0.1:8188",
            history=failed_faceid_hist,
            drive_output_dir=paths["drive"] / "outputs",
            evidence_path=evidence_path,
        )
        _assert_equal("failed recovery captured", rec_failed.get("captured"), 0)
        _assert_equal("failed ledger empty", len(load_identity_benchmark_records(ledger_failed)), 0)
        _pass(results, "Failed benchmark execution does not become successful benchmark record")

        # I: later successful execution of SAME preparation remains capturable exactly once
        cap_after_fail = capture_identity_benchmark_execution(
            drive_root=paths["drive"],
            ledger_path=ledger,
            prompt_id="prompt-faceid-s1-success-after-fail",
            output_node_id="9",
            output_path=out_file,
            output_sha256=out_sha,
            provenance=prov,
            ui_workflow=prep_wf,
            local_path=str(out_file),
            evidence_path=evidence_path,
            drive_output_dir=paths["drive"] / "outputs",
        )
        _assert_true(f"capture after fail ok ({cap_after_fail.errors})", cap_after_fail.ok)
        _assert_false("not duplicate of prior success", cap_after_fail.skipped_duplicate)
        _pass(results, "Later successful execution of SAME prep capturable without ambiguity")

        # Source disappears after durable copy — benchmark row remains valid
        missed.unlink(missing_ok=True)
        _assert_false("runtime source gone", missed.is_file())
        _assert_true("durable still present", recovered_out.is_file())
        _assert_equal(
            "ledger still points at durable",
            load_identity_benchmark_records(ledger_recover)[0].get("output_path"),
            str(recovered_out),
        )
        _pass(results, "Source disappears after durable copy -> benchmark row remains valid")

        # Drive SHA mismatch fails closed
        from core.runtime.identity_benchmark_capture import ensure_durable_benchmark_artifact
        from core.runtime.generation_evidence_ledger import EvidenceLedger, EvidenceRecord

        bad_drive = paths["drive"] / "outputs" / "identity_benchmark_bogus.png"
        bad_drive.write_bytes(b"\x89PNG\r\n\x1a\nWRONG")
        EvidenceLedger(evidence_path).append(
            EvidenceRecord(
                prompt_id="prompt-sha-mismatch",
                output_node_id="9",
                local_path=str(out_file),
                drive_path=str(bad_drive),
                local_sha256=out_sha,
                drive_sha256=out_sha,  # lying evidence
                sync_status="verified",
                capability="txt2img",
            )
        )
        mismatch = ensure_durable_benchmark_artifact(
            drive_root=paths["drive"],
            source_path=out_file,
            prompt_id="prompt-sha-mismatch",
            output_node_id="9",
            source_sha256=out_sha,
            drive_output_dir=paths["drive"] / "outputs",
            evidence_path=evidence_path,
        )
        _assert_false("drive sha mismatch fails", mismatch.ok)
        _pass(results, "Drive verification / SHA mismatch fails closed")

        # Ambiguous: two identity preps could match same fingerprint without prep_id
        # Fail closed when preparation_id missing and hash/face ambiguous — force by stripping ai_studio
        bare_wf = json.loads(json.dumps(prep_wf))
        if isinstance(bare_wf.get("extra"), dict):
            bare_wf["extra"].pop("ai_studio", None)
        face_widget = ""
        for node in prep_wf.get("nodes") or []:
            if isinstance(node, dict) and node.get("type") == "LoadImage":
                widgets = node.get("widgets_values") or []
                if widgets:
                    face_widget = str(widgets[0] or "")
                break
        # Also plant a second conflicting index row with same face/seed
        append_preparation_record(
            preparations_log_path(paths["drive"]),
            {
                "preparation_id": "prep_ambiguous_other",
                "preparation_kind": PREPARATION_KIND_IDENTITY_BENCHMARK,
                "benchmark_run": True,
                "candidate": CANDIDATE_REACTOR,
                "scenario": "S1_near_front_portrait",
                "character_id": reg.character.character_id,
                "prepared_workflow_hash": "deadbeef",
                "parameter_summary": {
                    "seed": int(capture_prep.seed),
                    "save_prefix": "ai_studio_idbench_reactor",
                },
                "parameters": {
                    "input_image": face_widget,
                    "seed": int(capture_prep.seed),
                    "save_prefix": "ai_studio_idbench_reactor",
                },
            },
        )
        amb_prov = ExecutionProvenance(
            preparation_id="",
            preparation_kind=PREPARATION_KIND_IDENTITY_BENCHMARK,
            capability="identity_benchmark",
            seed=int(capture_prep.seed),
            save_prefix="ai_studio_idbench_reactor",
        )
        amb = capture_identity_benchmark_execution(
            drive_root=paths["drive"],
            ledger_path=ledger,
            prompt_id="prompt-amb",
            output_node_id="9",
            output_path=out_file,
            output_sha256=out_sha,
            provenance=amb_prov,
            ui_workflow=bare_wf,
            evidence_path=evidence_path,
            drive_output_dir=paths["drive"] / "outputs",
        )
        _assert_false("ambiguous fails closed", amb.ok)
        _assert_true(
            "ambiguous message",
            any("Ambiguous" in e or "multiple" in e.lower() for e in amb.errors),
        )
        _pass(results, "Ambiguous history fails closed")

        missing_out = capture_identity_benchmark_execution(
            drive_root=paths["drive"],
            ledger_path=ledger,
            prompt_id="prompt-missing-out",
            output_node_id="9",
            output_path=paths["comfy"] / "output" / "does_not_exist.png",
            output_sha256="abc",
            provenance=prov,
            ui_workflow=prep_wf,
            evidence_path=evidence_path,
            drive_output_dir=paths["drive"] / "outputs",
        )
        _assert_false("missing output fails", missing_out.ok)
        _pass(results, "Missing output fails closed")

        bad_sha = capture_identity_benchmark_execution(
            drive_root=paths["drive"],
            ledger_path=ledger,
            prompt_id="prompt-bad-sha",
            output_node_id="9",
            output_path=out_file,
            output_sha256="0" * 64,
            provenance=prov,
            ui_workflow=prep_wf,
            evidence_path=evidence_path,
            drive_output_dir=paths["drive"] / "outputs",
        )
        _assert_false("sha mismatch fails", bad_sha.ok)
        _pass(results, "Output SHA/read failure fails closed")

        non_bench = capture_identity_benchmark_execution(
            drive_root=paths["drive"],
            ledger_path=ledger,
            prompt_id="prompt-txt2img",
            output_node_id="9",
            output_path=out_file,
            output_sha256=out_sha,
            provenance=ExecutionProvenance(capability="txt2img", workflow_identifier="base/txt2img", seed=1),
            ui_workflow={"nodes": [], "extra": {"ai_studio": {"preparation_kind": "standard"}}},
        )
        _assert_true("non-benchmark skipped", non_bench.ok and non_bench.skipped_not_benchmark)
        _assert_false(
            "non-benchmark not in ledger",
            any(r.get("prompt_id") == "prompt-txt2img" for r in load_identity_benchmark_records(ledger)),
        )
        _pass(results, "Non-benchmark execution does not enter benchmark ledger")

        # Watcher path: identity benchmark skips ordinary generation snapshot
        from core.runtime.output_autosync import OutputAutoSyncService
        from core.runtime.generation_evidence_ledger import EvidenceLedger

        evidence = paths["drive"] / "logs" / "autosync" / "evidence.jsonl"
        idx = paths["drive"] / "logs" / "autosync" / "processed.json"
        status = paths["drive"] / "logs" / "autosync" / "status.json"
        gen_index = paths["drive"] / "generations" / "index.jsonl"
        svc = OutputAutoSyncService(
            drive_root=paths["drive"],
            drive_output_dir=paths["drive"] / "outputs",
            comfy_output_dir=paths["comfy"] / "output",
            evidence_path=evidence,
            index_path=idx,
            status_path=status,
            generation_index_path=gen_index,
            registered_hashes={},
        )
        (paths["drive"] / "outputs").mkdir(parents=True, exist_ok=True)
        watch_out = paths["comfy"] / "output" / "watcher_idbench.png"
        watch_out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"WATCHER-IDBENCH")
        before_gen = gen_index.read_text(encoding="utf-8") if gen_index.is_file() else ""
        rec_watch = svc.sync_local_output(
            prompt_id="prompt-watch-1",
            output_node_id="9",
            local_path=watch_out,
            provenance=prov,
            ui_workflow=prep_wf,
            capability="identity_benchmark",
        )
        _assert_true("watcher sync verified", rec_watch is not None and rec_watch.sync_status == "verified")
        _assert_equal("no generation snapshot", rec_watch.snapshot_status, "skipped_identity_benchmark")
        after_gen = gen_index.read_text(encoding="utf-8") if gen_index.is_file() else ""
        _assert_equal("generation index unchanged", after_gen, before_gen)
        _assert_true(
            "watcher ledger captured",
            any(r.get("prompt_id") == "prompt-watch-1" for r in load_identity_benchmark_records(ledger)),
        )
        # watcher + recovery no duplicate
        hist_w = {
            "prompt-watch-1": {
                "prompt": [0, "c", {}, {"extra_pnginfo": {"workflow": prep_wf}}, ["9"]],
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "watcher_idbench.png", "subfolder": "", "type": "output"}
                        ]
                    }
                },
                "status": {"completed": True},
            }
        }
        # Re-capture via direct capture with same key after watcher
        key = benchmark_idempotence_key("prompt-watch-1", "9", file_sha256(Path(rec_watch.drive_path)))
        from core.runtime.identity_benchmark_capture import ledger_has_idempotence_key

        _assert_true("idempotence key present", ledger_has_idempotence_key(ledger, key))
        _pass(results, "Watcher captures benchmark once; does not enter ordinary generation ledger")

        # Concurrent idempotence: same key from two processes → exactly one row
        import concurrent.futures

        conc_ledger = paths["drive"] / "logs" / "identity_benchmark_conc.jsonl"
        conc_key = benchmark_idempotence_key("prompt-conc-same", "9", out_sha)
        same_payload = {
            "ledger_path": str(conc_ledger),
            "idempotence_key": conc_key,
            "candidate": CANDIDATE_REACTOR,
            "scenario": "S1_near_front_portrait",
            "character_id": reg.character.character_id,
            "seed": int(capture_prep.seed),
            "preparation_id": capture_prep.preparation_id,
            "prompt_id": "prompt-conc-same",
            "output_node_id": "9",
            "output_path": str(durable1),
            "output_sha256": out_sha,
        }
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            same_results = list(pool.map(_concurrent_append_worker, [same_payload] * 8))
        _assert_true("all same-key workers ok", all(ok for ok, _ in same_results))
        _assert_equal(
            "exactly one same-key row",
            len(load_identity_benchmark_records(conc_ledger)),
            1,
        )
        _assert_true("at least one duplicate skip", any(dup for _, dup in same_results))
        _pass(results, "Concurrent same-key workers -> exactly one ledger row")

        # Different keys from concurrent workers → both preserved
        diff_payloads = []
        for n, (pid, sha_n, path_n) in enumerate(
            [
                ("prompt-conc-diff-0", out_sha, durable1),
                ("prompt-conc-diff-1", sha2, out2),
            ]
        ):
            diff_payloads.append(
                {
                    **same_payload,
                    "idempotence_key": benchmark_idempotence_key(pid, "9", sha_n),
                    "prompt_id": pid,
                    "output_path": str(path_n),
                    "output_sha256": sha_n,
                }
            )
        with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
            diff_results = list(pool.map(_concurrent_append_worker, diff_payloads))
        _assert_true("diff workers ok", all(ok and not dup for ok, dup in diff_results))
        _assert_equal(
            "same+two distinct rows",
            len(load_identity_benchmark_records(conc_ledger)),
            3,
        )
        _pass(results, "Concurrent different keys -> both rows preserved")

        # Watcher-style + recovery-style race on same execution (threads + file lock)
        race_ledger = paths["drive"] / "logs" / "identity_benchmark_race.jsonl"
        race_src = paths["comfy"] / "output" / "race_idbench.png"
        race_src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"RACE-IDBENCH")
        race_sha = file_sha256(race_src)
        # Durable artifact once (copy races are covered by autosync); race the ledger append.
        durable_race = ensure_durable_benchmark_artifact(
            drive_root=paths["drive"],
            source_path=race_src,
            prompt_id="prompt-race-1",
            output_node_id="9",
            source_sha256=race_sha,
            drive_output_dir=paths["drive"] / "outputs",
            evidence_path=evidence_path,
        )
        _assert_true(f"race durable ({durable_race.errors})", durable_race.ok and durable_race.drive_path)

        def _race_capture(_n: int):
            return capture_identity_benchmark_execution(
                drive_root=paths["drive"],
                ledger_path=race_ledger,
                prompt_id="prompt-race-1",
                output_node_id="9",
                output_path=durable_race.drive_path,
                output_sha256=race_sha,
                provenance=prov,
                ui_workflow=prep_wf,
                local_path=str(race_src),
                evidence_path=evidence_path,
                drive_output_dir=paths["drive"] / "outputs",
                ensure_durable=True,
                reclassify_ordinary=False,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            race_caps = list(pool.map(_race_capture, range(4)))
        _assert_true(
            f"race captures ok ({[c.errors for c in race_caps if not c.ok]})",
            all(c.ok for c in race_caps),
        )
        _assert_equal(
            "race one row",
            len([r for r in load_identity_benchmark_records(race_ledger) if r.get("prompt_id") == "prompt-race-1"]),
            1,
        )
        _assert_true("race had duplicates", any(c.skipped_duplicate for c in race_caps))
        _pass(results, "Watcher/recovery-style concurrent race -> one benchmark row")

        # Legacy ordinary misclassification cleanup
        from core.runtime.generation_index import GenerationIndex, GenerationIndexRecord
        from core.runtime.generation_snapshot import (
            METADATA_FILENAME,
            _atomic_write_json,
            new_generation_id,
            resolve_snapshot_root,
        )
        from core.runtime.generation_history import collapse_generations
        from core.runtime.identity_benchmark_capture import reclassify_legacy_ordinary_generation

        legacy_gid = new_generation_id()
        legacy_src = paths["comfy"] / "output" / "legacy_misclass.png"
        legacy_src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"LEGACY-MISCLASS")
        legacy_sha = file_sha256(legacy_src)
        # Simulate pre-fix ordinary autosync: Drive copy + snapshot + index
        from core.runtime.permanent_output_naming import resolve_permanent_destination
        from core.runtime.output_autosync import copy_with_verification

        legacy_dest = resolve_permanent_destination(
            paths["drive"] / "outputs", capability="txt2img", source_path=legacy_src
        )
        dest_ok, status_ok, _, err = copy_with_verification(legacy_src, legacy_dest)
        _assert_true(f"legacy drive copy ({err})", status_ok == "verified" and dest_ok is not None)
        snap_root = resolve_snapshot_root(paths["drive"], legacy_gid, project_slug="")
        snap_root.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(
            snap_root / METADATA_FILENAME,
            {
                "generation_id": legacy_gid,
                "prompt_id": "prompt-legacy-bench",
                "output_node_id": "9",
                "image_sha256": legacy_sha,
                "capability": "txt2img",
                "positive_prompt": "portrait",
                "steps": 20,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "model_files": ["sd15.safetensors"],
            },
        )
        _atomic_write_json(snap_root / "workflow.json", {"nodes": []})
        _atomic_write_json(
            snap_root / "manifest.json",
            {"snapshot_status": "complete", "image_sha256": legacy_sha, "generation_id": legacy_gid},
        )
        gen_idx_path = paths["drive"] / "logs" / "autosync" / "generation_index.jsonl"
        GenerationIndex(gen_idx_path).append(
            GenerationIndexRecord(
                generation_id=legacy_gid,
                dedupe_key=f"prompt-legacy-bench|9|{legacy_src}|{legacy_sha}",
                prompt_id="prompt-legacy-bench",
                output_node_id="9",
                capability="txt2img",
                canonical_output_path=str(legacy_dest),
                snapshot_root=str(snap_root),
                snapshot_status="snapshot_complete",
                image_sha256=legacy_sha,
                drive_filename=legacy_dest.name,
            )
        )
        EvidenceLedger(evidence_path).append(
            EvidenceRecord(
                prompt_id="prompt-legacy-bench",
                schema_version=2,
                output_node_id="9",
                local_path=str(legacy_src),
                drive_path=str(legacy_dest),
                local_sha256=legacy_sha,
                drive_sha256=legacy_sha,
                sync_status="verified",
                capability="txt2img",
                generation_id=legacy_gid,
                snapshot_status="snapshot_complete",
                snapshot_root=str(snap_root),
            )
        )
        # Unrelated ordinary generation with similar filename must stay untouched
        other_gid = new_generation_id()
        other_src = paths["comfy"] / "output" / "legacy_misclass_other.png"
        other_src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"OTHER-ORDINARY")
        other_sha = file_sha256(other_src)
        other_dest = resolve_permanent_destination(
            paths["drive"] / "outputs", capability="txt2img", source_path=other_src
        )
        copy_with_verification(other_src, other_dest)
        EvidenceLedger(evidence_path).append(
            EvidenceRecord(
                prompt_id="prompt-unrelated-ordinary",
                schema_version=2,
                output_node_id="9",
                local_path=str(other_src),
                drive_path=str(other_dest),
                local_sha256=other_sha,
                drive_sha256=other_sha,
                sync_status="verified",
                capability="txt2img",
                generation_id=other_gid,
                snapshot_status="snapshot_complete",
            )
        )

        legacy_ledger = paths["drive"] / "logs" / "identity_benchmark_legacy.jsonl"
        legacy_cap = capture_identity_benchmark_execution(
            drive_root=paths["drive"],
            ledger_path=legacy_ledger,
            prompt_id="prompt-legacy-bench",
            output_node_id="9",
            output_path=legacy_src,
            output_sha256=legacy_sha,
            provenance=prov,
            ui_workflow=prep_wf,
            evidence_path=evidence_path,
            drive_output_dir=paths["drive"] / "outputs",
            reclassify_ordinary=True,
        )
        _assert_true(f"legacy capture ({legacy_cap.errors})", legacy_cap.ok)
        _assert_true(
            "legacy reclass message",
            any("Reclassified" in m for m in legacy_cap.messages),
        )
        _assert_true("legacy image preserved", Path(legacy_dest).is_file())
        meta_after = json.loads((snap_root / METADATA_FILENAME).read_text(encoding="utf-8"))
        _assert_true("metadata benchmark_run", meta_after.get("benchmark_run") is True)
        elig_legacy = assess_derivation_eligibility(
            metadata=meta_after, manifest={"image_sha256": legacy_sha}
        )
        _assert_false("legacy no longer ordinary parent", elig_legacy.eligible)
        listed = collapse_generations(evidence_path, verified_only=True, sync_status="verified")
        _assert_false(
            "ordinary list hides reclassified",
            any(str(r.get("generation_id") or "") == legacy_gid for r in listed),
        )
        _assert_true(
            "unrelated ordinary still listed",
            any(str(r.get("generation_id") or "") == other_gid for r in listed),
        )
        _pass(results, "Legacy ordinary misclassification reclassified; image preserved; unrelated untouched")

        # Already-clean benchmark recovery is a no-op for ordinary ledger
        clean = reclassify_legacy_ordinary_generation(
            drive_root=paths["drive"],
            prompt_id="prompt-watch-1",
            output_node_id="9",
            output_sha256=file_sha256(Path(rec_watch.drive_path)),
            preparation_id=capture_prep.preparation_id,
            evidence_path=evidence_path,
            generation_index_path=gen_idx_path,
        )
        _assert_true("clean reclass ok", clean.ok)
        _assert_false("clean reclass no-op", clean.changed)
        _pass(results, "Already-clean benchmark recovery is a no-op for ordinary ledger")

        # Ambiguous SHA/prompt reclass fails closed
        EvidenceLedger(evidence_path).append(
            EvidenceRecord(
                prompt_id="prompt-legacy-bench",
                schema_version=2,
                output_node_id="9",
                local_path=str(legacy_src),
                drive_path=str(legacy_dest),
                local_sha256=legacy_sha,
                drive_sha256=legacy_sha,
                sync_status="verified",
                capability="txt2img",
                generation_id=new_generation_id(),
                snapshot_status="snapshot_complete",
            )
        )
        # Note: reclass skips capability=identity_benchmark and reclassified status;
        # the original was reclassified. Ambiguity test: two txt2img rows same proof.
        # Reset by planting two fresh ordinary rows for a new prompt.
        amb_gid_a = new_generation_id()
        amb_gid_b = new_generation_id()
        amb_src = paths["comfy"] / "output" / "amb_reclass.png"
        amb_src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"AMB-RECLASS")
        amb_sha = file_sha256(amb_src)
        for gid in (amb_gid_a, amb_gid_b):
            EvidenceLedger(evidence_path).append(
                EvidenceRecord(
                    prompt_id="prompt-amb-reclass",
                    schema_version=2,
                    output_node_id="9",
                    local_path=str(amb_src),
                    drive_path=str(legacy_dest),
                    local_sha256=amb_sha,
                    drive_sha256=amb_sha,
                    sync_status="verified",
                    capability="txt2img",
                    generation_id=gid,
                    snapshot_status="snapshot_complete",
                )
            )
        amb_reclass = reclassify_legacy_ordinary_generation(
            drive_root=paths["drive"],
            prompt_id="prompt-amb-reclass",
            output_node_id="9",
            output_sha256=amb_sha,
            preparation_id=capture_prep.preparation_id,
            evidence_path=evidence_path,
            generation_index_path=gen_idx_path,
        )
        _assert_false("ambiguous reclass fails", amb_reclass.ok)
        _pass(results, "SHA/prompt ambiguity on reclassification fails closed")

        # Report recovery failure visibly surfaced
        from core.scripts.report_identity_benchmark import _format_recovery_section

        fail_section, fail_status = _format_recovery_section(
            {"ok": False, "examined": 1, "captured": 0, "duplicates": 0, "failed": 1, "errors": ["ERROR: boom"]}
        )
        _assert_equal("recovery fail status", fail_status, "FAIL")
        _assert_true("recovery STOP wording", "STOP:" in fail_section)
        ok_section, ok_status = _format_recovery_section(
            {"ok": True, "examined": 1, "captured": 1, "duplicates": 0, "failed": 0, "errors": []}
        )
        _assert_equal("recovery ok status", ok_status, "OK")
        _pass(results, "Report clearly surfaces recovery failure vs success")

        report_txt = format_identity_benchmark_report(load_identity_benchmark_records(ledger))
        _assert_true("report shows records", "Records:" in report_txt and "Records: 0" not in report_txt)
        _assert_true("report human pending", "human_review=pending" in report_txt)
        _pass(results, "Report shows captured execution with human review pending")

        # --- Shared JSONL lock coverage (EvidenceLedger / GenerationIndex / audit) ---
        import concurrent.futures
        import time

        conc_evidence = paths["drive"] / "logs" / "autosync" / "evidence_conc.jsonl"
        conc_evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence_workers = [
            {
                "path": str(conc_evidence),
                "prompt_id": f"prompt-evidence-{i}",
                "sha": f"sha-evidence-{i:02d}",
            }
            for i in range(12)
        ]
        with concurrent.futures.ProcessPoolExecutor(max_workers=6) as pool:
            evidence_ids = list(pool.map(_concurrent_evidence_worker, evidence_workers))
        evidence_rows = _valid_jsonl_lines(conc_evidence)
        _assert_equal("evidence concurrent count", len(evidence_rows), 12)
        _assert_equal(
            "evidence all prompt ids present",
            sorted(evidence_ids),
            sorted(f"prompt-evidence-{i}" for i in range(12)),
        )
        _pass(results, "EvidenceLedger concurrent distinct rows -> all survive, valid JSON")

        conc_index = paths["drive"] / "logs" / "autosync" / "generation_index_conc.jsonl"
        index_workers = [
            {
                "path": str(conc_index),
                "generation_id": f"gen_conc_{i:02d}",
                "dedupe_key": f"key-{i}",
                "prompt_id": f"prompt-index-{i}",
                "image_sha256": f"sha-index-{i:02d}",
            }
            for i in range(12)
        ]
        with concurrent.futures.ProcessPoolExecutor(max_workers=6) as pool:
            index_ids = list(pool.map(_concurrent_index_worker, index_workers))
        index_rows = _valid_jsonl_lines(conc_index)
        _assert_equal("index concurrent count", len(index_rows), 12)
        _assert_equal("index all generation ids present", sorted(index_ids), sorted(w["generation_id"] for w in index_workers))
        _pass(results, "GenerationIndex concurrent distinct rows -> all survive, valid JSON")

        race_evidence = paths["drive"] / "logs" / "autosync" / "evidence_race.jsonl"
        watcher_payload = {
            "path": str(race_evidence),
            "prompt_id": "prompt-watcher-ordinary",
            "sha": "sha-watcher-ordinary",
            "capability": "txt2img",
            "snapshot_status": "snapshot_complete",
            "generation_id": "gen_watcher_ordinary",
        }
        recovery_payload = {
            "path": str(race_evidence),
            "prompt_id": "prompt-recovery-benchmark",
            "sha": "sha-recovery-benchmark",
            "capability": "identity_benchmark",
            "snapshot_status": "skipped_identity_benchmark",
            "generation_id": "",
        }
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            race_ev = list(pool.map(_concurrent_evidence_worker, [watcher_payload, recovery_payload]))
        race_ev_rows = _valid_jsonl_lines(race_evidence)
        _assert_equal("evidence race row count", len(race_ev_rows), 2)
        _assert_true(
            "watcher evidence survived",
            any(r.get("prompt_id") == "prompt-watcher-ordinary" for r in race_ev_rows),
        )
        _assert_true(
            "recovery evidence survived",
            any(r.get("prompt_id") == "prompt-recovery-benchmark" for r in race_ev_rows),
        )
        _pass(results, "Watcher/recovery concurrent evidence appends -> both survive")

        race_index = paths["drive"] / "logs" / "autosync" / "generation_index_race.jsonl"
        normal_idx = {
            "path": str(race_index),
            "generation_id": "gen_normal_listed",
            "dedupe_key": "normal-key",
            "prompt_id": "prompt-normal",
            "capability": "txt2img",
            "snapshot_status": "snapshot_complete",
            "image_sha256": "sha-normal",
        }
        quarantine_idx = {
            "path": str(race_index),
            "generation_id": "gen_reclassified_bench",
            "dedupe_key": "bench-key",
            "prompt_id": "prompt-bench-reclass",
            "capability": "identity_benchmark",
            "snapshot_status": "reclassified_identity_benchmark",
            "image_sha256": "sha-bench",
        }
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            race_idx = list(pool.map(_concurrent_index_worker, [normal_idx, quarantine_idx]))
        race_idx_rows = _valid_jsonl_lines(race_index)
        _assert_equal("index race row count", len(race_idx_rows), 2)
        _assert_equal("index race ids", sorted(race_idx), sorted(["gen_normal_listed", "gen_reclassified_bench"]))
        _pass(results, "Watcher/reclassification concurrent index appends -> both survive")

        # Concurrent different benchmark executions + supporting evidence
        bench_ledger_race = paths["drive"] / "logs" / "identity_benchmark_ev_race.jsonl"
        bench_evidence = paths["drive"] / "logs" / "autosync" / "evidence_bench_race.jsonl"
        bench_payloads = []
        for i, pid in enumerate(("prompt-bench-ev-a", "prompt-bench-ev-b")):
            sha_b = file_sha256(out_file) if i == 0 else sha2
            bench_payloads.append(
                {
                    **same_payload,
                    "ledger_path": str(bench_ledger_race),
                    "idempotence_key": benchmark_idempotence_key(pid, "9", sha_b),
                    "prompt_id": pid,
                    "output_sha256": sha_b,
                    "output_path": str(durable1 if i == 0 else out2),
                }
            )
        with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
            pool.map(_concurrent_append_worker, bench_payloads)
        for i, pid in enumerate(("prompt-bench-ev-a", "prompt-bench-ev-b")):
            sha_b = file_sha256(out_file) if i == 0 else sha2
            _concurrent_evidence_worker(
                {
                    "path": str(bench_evidence),
                    "prompt_id": pid,
                    "sha": sha_b,
                    "capability": "identity_benchmark",
                    "snapshot_status": "skipped_identity_benchmark",
                }
            )
        bench_rows = [r for r in load_identity_benchmark_records(bench_ledger_race) if r.get("prompt_id", "").startswith("prompt-bench-ev-")]
        bench_ev_rows = _valid_jsonl_lines(bench_evidence)
        _assert_equal("two benchmark ledger rows", len(bench_rows), 2)
        _assert_equal("two benchmark evidence rows", len(bench_ev_rows), 2)
        _pass(results, "Concurrent benchmark executions -> ledger + evidence both retained")

        audit_path = paths["drive"] / "logs" / "identity_benchmark_reclassifications_conc.jsonl"
        audit_workers = [
            {"path": str(audit_path), "action": f"audit-{i}", "seq": i} for i in range(10)
        ]
        with concurrent.futures.ProcessPoolExecutor(max_workers=5) as pool:
            audit_actions = list(pool.map(_concurrent_audit_worker, audit_workers))
        audit_rows = _valid_jsonl_lines(audit_path)
        _assert_equal("audit concurrent count", len(audit_rows), 10)
        _assert_equal("audit actions", sorted(audit_actions), sorted(f"audit-{i}" for i in range(10)))
        _pass(results, "Reclassification audit JSONL locked append -> all rows survive")

        # Lock wait: concurrent append waits rather than corrupting
        lock_wait_path = paths["drive"] / "logs" / "jsonl_lock_wait.jsonl"
        import threading
        from core.runtime.jsonl_file_lock import append_jsonl_line, exclusive_jsonl_lock

        started = threading.Event()
        released = threading.Event()

        def _hold_lock() -> None:
            with exclusive_jsonl_lock(lock_wait_path):
                started.set()
                released.wait(timeout=2.0)

        holder = threading.Thread(target=_hold_lock)
        holder.start()
        started.wait(timeout=2.0)
        t0 = time.monotonic()
        append_jsonl_line(lock_wait_path, json.dumps({"waiter": True}))
        elapsed = time.monotonic() - t0
        released.set()
        holder.join(timeout=2.0)
        wait_rows = _valid_jsonl_lines(lock_wait_path)
        _assert_equal("lock wait one row", len(wait_rows), 1)
        _assert_true("lock wait blocked", elapsed >= 0.05)
        _pass(results, "JSONL lock serializes concurrent append (no silent overwrite)")

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
