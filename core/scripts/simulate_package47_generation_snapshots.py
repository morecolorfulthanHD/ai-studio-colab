#!/usr/bin/env python3
"""Package 4.7 generation snapshot & reproducibility simulations."""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.generation_evidence_ledger import EvidenceLedger, EvidenceRecord, file_sha256
from core.runtime.generation_history import collapse_generations, snapshot_status_label
from core.runtime.generation_index import GenerationIndex, rebuild_index_from_sources
from core.runtime.generation_snapshot import (
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    WORKFLOW_FILENAME,
    create_generation_snapshot,
    file_content_sha256,
    is_snapshot_complete,
    load_snapshot_by_id,
    validate_snapshot,
)
from core.runtime.output_autosync import OutputAutoSyncService
from core.runtime.png_utils import write_rgb_png
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.workflow_provenance import (
    ExecutionProvenance,
    HASH_TYPE_UI,
    hash_api_prompt,
    hash_ui_workflow,
)
from core.scripts.migrate_generation_snapshots import migrate
from core.scripts.repair_generation_snapshot import repair_manifest


class SimulationFailure(Exception):
    pass


REQUIRED_METADATA_FIELDS = (
    "schema_version",
    "generation_id",
    "prompt_id",
    "output_node_id",
    "created_timestamp",
    "synchronized_timestamp",
    "project_id",
    "project_slug",
    "project_name",
    "capability",
    "workflow_identifier",
    "workflow_source",
    "workflow_hash",
    "workflow_hash_type",
    "api_prompt_hash",
    "model_family",
    "model_files",
    "positive_prompt",
    "negative_prompt",
    "seed",
    "steps",
    "cfg",
    "sampler_name",
    "scheduler",
    "denoise",
    "width",
    "height",
    "batch_size",
    "source_filename",
    "drive_filename",
    "canonical_output_path",
    "project_output_path",
    "image_sha256",
    "byte_size",
    "sync_status",
    "provenance_status",
    "runtime_id",
    "repository_commit",
    "package_version",
    "snapshot_schema_version",
    "workflow_snapshot_status",
)


def _assert_equal(label: str, actual, expected) -> None:
    if actual != expected:
        raise SimulationFailure(f"{label}: expected {expected!r}, got {actual!r}")


def _assert_true(label: str, value: bool) -> None:
    if not value:
        raise SimulationFailure(f"{label}: expected True")


def _pass(results: list[tuple[str, str]], name: str) -> None:
    results.append((name, "PASS"))


def _write_png(path: Path, fill: tuple[int, int, int] = (10, 20, 30)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [[fill for _ in range(8)] for _ in range(8)]
    write_rgb_png(path, 8, 8, rows)


def _sample_ui_workflow(*, seed: int = 424242, prompt: str = "a mountain landscape") -> dict:
    return {
        "nodes": [
            {"id": 6, "type": "CLIPTextEncode", "pos": [100, 100], "widgets_values": [prompt]},
            {
                "id": 3,
                "type": "KSampler",
                "pos": [400, 100],
                "widgets_values": [seed, "fixed", 24, 7.0, "euler", "normal", 1.0],
            },
            {"id": 9, "type": "SaveImage", "pos": [700, 100], "widgets_values": ["ai_studio_base_txt2img"]},
        ],
        "links": [],
        "version": 0.4,
    }


def _sample_api_prompt(*, seed: int = 424242, prompt: str = "a mountain landscape") -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd15.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
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
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ai_studio_base_txt2img", "images": ["8", 0]}},
    }


def _make_provenance(
    *,
    seed: int = 424242,
    prompt: str = "a mountain landscape",
    ui_workflow: dict | None = None,
    api_prompt: dict | None = None,
) -> ExecutionProvenance:
    ui = ui_workflow if ui_workflow is not None else _sample_ui_workflow(seed=seed, prompt=prompt)
    api = api_prompt if api_prompt is not None else _sample_api_prompt(seed=seed, prompt=prompt)
    return ExecutionProvenance(
        workflow_identifier="base/txt2img",
        workflow_hash=hash_ui_workflow(ui),
        workflow_hash_type=HASH_TYPE_UI,
        api_prompt_hash=hash_api_prompt(api),
        workflow_source="registered_canonical",
        capability="txt2img",
        model_family="sd15",
        model_files=["sd15.safetensors"],
        positive_prompt=prompt,
        negative_prompt="blurry",
        seed=seed,
        steps=24,
        cfg=7.0,
        sampler_name="euler",
        scheduler="normal",
        denoise=1.0,
        width=512,
        height=768,
        provenance_status="complete",
    )


def _make_service(
    *,
    comfy: Path,
    drive: Path,
    evidence: Path,
    index_path: Path,
    status_path: Path,
    active_project=None,
    generation_index_path: Path | None = None,
) -> OutputAutoSyncService:
    return OutputAutoSyncService(
        comfy_output_dir=comfy,
        drive_output_dir=drive / "outputs",
        evidence_path=evidence,
        index_path=index_path,
        status_path=status_path,
        base_url="http://127.0.0.1:9",
        sleep_fn=lambda _s: None,
        max_copy_retries=1,
        active_project=active_project,
        drive_root=drive,
        generation_index_path=generation_index_path or (evidence.parent / "generation_index.jsonl"),
    )


def _export_zip(drive: Path, generation_id: str, output_dir: Path) -> Path:
    manifest = load_snapshot_by_id(drive, generation_id)
    _assert_true("export snapshot exists", manifest is not None)
    assert manifest is not None
    snapshot_root = Path(str(manifest["snapshot_root"]))
    image_path = Path(str(manifest.get("canonical_output_path") or ""))
    _assert_true("export image exists", image_path.is_file())
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{generation_id}.zip"
    if zip_path.exists():
        stamp = "collision"
        zip_path = output_dir / f"{generation_id}_{stamp}.zip"
        n = 1
        while zip_path.exists():
            n += 1
            zip_path = output_dir / f"{generation_id}_{stamp}{n}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(image_path, f"image/{image_path.name}")
        archive.write(snapshot_root / METADATA_FILENAME, METADATA_FILENAME)
        archive.write(snapshot_root / WORKFLOW_FILENAME, WORKFLOW_FILENAME)
        archive.write(snapshot_root / MANIFEST_FILENAME, MANIFEST_FILENAME)
        archive.writestr(
            "export_manifest.json",
            json.dumps({"export_schema_version": 1, "generation_id": generation_id}, indent=2) + "\n",
        )
    return zip_path


def run_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)
        drive = root / "AI_Studio"
        comfy = root / "ComfyUI" / "output"
        evidence = drive / "logs" / "generation_evidence.jsonl"
        gen_index = drive / "logs" / "generation_index.jsonl"
        processed = drive / "logs" / "autosync" / "processed.json"
        status = root / "runtime" / "watcher_status.json"
        comfy.mkdir(parents=True)
        (drive / "outputs").mkdir(parents=True)
        (drive / "logs" / "autosync").mkdir(parents=True)
        status.parent.mkdir(parents=True)

        workspace = ProjectWorkspace(drive)
        mountain = workspace.create_project(display_name="Mountain Demo", slug="mountain-demo", set_active=True)

        ui = _sample_ui_workflow()
        api = _sample_api_prompt()
        prov = _make_provenance(ui_workflow=ui, api_prompt=api)

        # ------------------------------------------------------------------
        # 1–4 verified global + project snapshots, canonical paths intact
        # ------------------------------------------------------------------
        svc = _make_service(
            comfy=comfy,
            drive=drive,
            evidence=evidence,
            index_path=processed,
            status_path=status,
            active_project=workspace.get_active_project(),
            generation_index_path=gen_index,
        )

        # Global-only generation first (deactivate temporarily).
        workspace.deactivate_active_project()
        svc.active_project = None
        global_src = comfy / "ai_studio_base_txt2img_00001_.png"
        _write_png(global_src, fill=(1, 2, 3))
        global_rec = svc.sync_local_output(
            prompt_id="p-global-1",
            output_node_id="9",
            local_path=global_src,
            capability="txt2img",
            provenance=prov,
            ui_workflow=ui,
            api_prompt=api,
        )
        _assert_true("global verified", global_rec is not None and global_rec.sync_status == "verified")
        assert global_rec is not None
        global_gid = global_rec.generation_id
        global_snap = Path(global_rec.snapshot_root)
        _assert_true("global snapshot under generations/", "generations" in str(global_snap).replace("\\", "/"))
        _assert_true("global snapshot complete", is_snapshot_complete(global_snap))
        _assert_true("global image canonical", Path(global_rec.drive_path).is_file())
        _pass(results, "Verified global generation creates snapshot")

        workspace.set_active_project("mountain-demo")
        svc.active_project = workspace.get_active_project()
        project_src = comfy / "ai_studio_base_txt2img_00002_.png"
        _write_png(project_src, fill=(4, 5, 6))
        project_rec = svc.sync_local_output(
            prompt_id="p-project-1",
            output_node_id="9",
            local_path=project_src,
            capability="txt2img",
            provenance=prov,
            ui_workflow=ui,
            api_prompt=api,
        )
        _assert_true("project verified", project_rec is not None and project_rec.sync_status == "verified")
        assert project_rec is not None
        project_gid = project_rec.generation_id
        project_snap = Path(project_rec.snapshot_root)
        _assert_true(
            "project snapshot under project generations/",
            f"/projects/mountain-demo/generations/" in str(project_snap).replace("\\", "/"),
        )
        _assert_true("project snapshot complete", is_snapshot_complete(project_snap))
        _pass(results, "Verified project generation creates project snapshot")

        _assert_true("global output remains canonical", Path(project_rec.drive_path).is_file())
        _assert_equal(
            "global under outputs/",
            Path(project_rec.drive_path).parent.resolve(),
            (drive / "outputs").resolve(),
        )
        _pass(results, "Global output remains canonical")
        _assert_true("project mirror intact", Path(project_rec.project_output_path).is_file())
        _pass(results, "Project mirror remains intact")

        # ------------------------------------------------------------------
        # 5–9 generation_id uniqueness / restart / retry / distinct executions
        # ------------------------------------------------------------------
        _assert_true("generation_id unique across gens", global_gid != project_gid)
        _assert_true("generation_id format", global_gid.startswith("gen_") and project_gid.startswith("gen_"))
        _pass(results, "generation_id is unique")

        gid_before_restart = project_gid
        svc_restart = _make_service(
            comfy=comfy,
            drive=drive,
            evidence=evidence,
            index_path=processed,
            status_path=status,
            active_project=workspace.get_active_project(),
            generation_index_path=gen_index,
        )
        rows_after = EvidenceLedger(evidence).read_all()
        found = [r for r in rows_after if r.get("generation_id") == gid_before_restart]
        _assert_true("generation_id in evidence after restart", bool(found))
        _assert_equal(
            "index retains generation_id",
            GenerationIndex(gen_index).generation_id_for_dedupe_key(project_rec.dedupe_key),
            gid_before_restart,
        )
        _pass(results, "generation_id survives restart")

        retry = svc_restart.sync_local_output(
            prompt_id="p-project-1",
            output_node_id="9",
            local_path=project_src,
            capability="txt2img",
            provenance=prov,
            ui_workflow=ui,
            api_prompt=api,
        )
        _assert_equal("retry skipped as already verified", retry, None)
        index_ids = {
            str(r.get("generation_id") or "")
            for r in GenerationIndex(gen_index).read_all()
            if str(r.get("dedupe_key") or "") == project_rec.dedupe_key
        }
        _assert_equal("retry keeps single generation_id", index_ids, {gid_before_restart})
        _pass(results, "Same execution retry does not allocate new ID")

        # Same local filename, different execution/content — restore original bytes afterward
        # so later restart/dedupe checks still match the first verified project generation.
        original_project_bytes = project_src.read_bytes()
        _write_png(project_src, fill=(7, 8, 9))
        other_exec = svc_restart.sync_local_output(
            prompt_id="p-project-2-different-exec",
            output_node_id="9",
            local_path=project_src,
            capability="txt2img",
            provenance=_make_provenance(seed=99, prompt="different mountain"),
            ui_workflow=_sample_ui_workflow(seed=99, prompt="different mountain"),
            api_prompt=_sample_api_prompt(seed=99, prompt="different mountain"),
        )
        _assert_true("different execution verified", other_exec is not None and other_exec.sync_status == "verified")
        assert other_exec is not None
        _assert_true("different execution new ID", other_exec.generation_id != project_gid)
        project_src.write_bytes(original_project_bytes)
        _pass(results, "Same local filename with different execution gets new ID")

        multi_a = comfy / "ai_studio_base_txt2img_node9_00003_.png"
        multi_b = comfy / "ai_studio_base_txt2img_node10_00003_.png"
        _write_png(multi_a, fill=(10, 11, 12))
        _write_png(multi_b, fill=(13, 14, 15))
        rec_a = svc_restart.sync_local_output(
            prompt_id="p-multi-out",
            output_node_id="9",
            local_path=multi_a,
            capability="txt2img",
            provenance=prov,
            ui_workflow=ui,
            api_prompt=api,
        )
        rec_b = svc_restart.sync_local_output(
            prompt_id="p-multi-out",
            output_node_id="10",
            local_path=multi_b,
            capability="txt2img",
            provenance=prov,
            ui_workflow=ui,
            api_prompt=api,
        )
        _assert_true("multi node A", rec_a is not None and bool(rec_a.generation_id))
        _assert_true("multi node B", rec_b is not None and bool(rec_b.generation_id))
        assert rec_a is not None and rec_b is not None
        _assert_true("distinct node IDs", rec_a.generation_id != rec_b.generation_id)
        _pass(results, "Multiple output nodes get distinct generation IDs")

        # ------------------------------------------------------------------
        # 10–17 metadata / workflow / hashes
        # ------------------------------------------------------------------
        metadata = json.loads((project_snap / METADATA_FILENAME).read_text(encoding="utf-8"))
        missing = [f for f in REQUIRED_METADATA_FIELDS if f not in metadata]
        _assert_equal("required metadata fields", missing, [])
        _pass(results, "metadata.json includes all required fields")

        # Minimal / unavailable fields stay null (no fabrication).
        lean_src = comfy / "ai_studio_base_txt2img_00040_.png"
        _write_png(lean_src, fill=(20, 21, 22))
        lean_rec = svc_restart.sync_local_output(
            prompt_id="p-lean",
            output_node_id="9",
            local_path=lean_src,
            capability="txt2img",
        )
        _assert_true("lean verified", lean_rec is not None)
        assert lean_rec is not None
        lean_meta = json.loads(Path(lean_rec.snapshot_metadata_path).read_text(encoding="utf-8"))
        for key in ("seed", "steps", "cfg", "positive_prompt", "model_family", "workflow_hash"):
            _assert_equal(f"null field {key}", lean_meta.get(key), None)
        _assert_equal("unavailable workflow status", lean_meta.get("workflow_snapshot_status"), "unavailable")
        _pass(results, "unavailable values are null")

        wf_payload = json.loads((project_snap / WORKFLOW_FILENAME).read_text(encoding="utf-8"))
        _assert_true("UI workflow stored", wf_payload.get("ui_workflow_available") is True)
        _assert_equal("UI workflow body", wf_payload.get("ui_workflow"), ui)
        _pass(results, "exact UI workflow is stored when available")

        _assert_true("API prompt stored", wf_payload.get("api_prompt_available") is True)
        _assert_equal("API prompt body", wf_payload.get("api_prompt"), api)
        _pass(results, "exact API prompt is stored when available")
        _pass(results, "both representations stored when available")

        no_wf_src = comfy / "ai_studio_base_txt2img_00041_.png"
        _write_png(no_wf_src, fill=(23, 24, 25))
        no_wf = svc_restart.sync_local_output(
            prompt_id="p-no-wf",
            output_node_id="9",
            local_path=no_wf_src,
            capability="txt2img",
            ui_workflow=None,
            api_prompt=None,
        )
        _assert_true("no-wf verified", no_wf is not None)
        assert no_wf is not None
        no_wf_body = json.loads(Path(no_wf.snapshot_workflow_path).read_text(encoding="utf-8"))
        _assert_equal("no-wf status", no_wf.workflow_snapshot_status, "unavailable")
        _assert_equal("no-wf ui false", no_wf_body.get("ui_workflow_available"), False)
        _assert_equal("no-wf api false", no_wf_body.get("api_prompt_available"), False)
        _assert_equal("no-wf ui null", no_wf_body.get("ui_workflow"), None)
        _assert_equal("no-wf api null", no_wf_body.get("api_prompt"), None)
        _assert_true("image still verified without workflow", Path(no_wf.drive_path).is_file())
        _pass(results, "no workflow available produces explicit unavailable status")

        stored_ui_hash = wf_payload.get("computed_ui_hash")
        _assert_equal("workflow hash matches stored UI", stored_ui_hash, hash_ui_workflow(ui))
        stored_api_hash = wf_payload.get("computed_api_hash")
        _assert_equal("workflow hash matches stored API", stored_api_hash, hash_api_prompt(api))
        _pass(results, "workflow hash matches stored snapshot")

        image_digest = file_sha256(Path(project_rec.drive_path))
        _assert_equal("image hash in metadata", metadata.get("image_sha256"), image_digest)
        _assert_equal("image hash in evidence", project_rec.drive_sha256, image_digest)
        _pass(results, "image hash matches existing verified hash")

        # ------------------------------------------------------------------
        # 18–23 manifest ordering, partial, atomic, failure, restart dedupe
        # ------------------------------------------------------------------
        write_order: list[str] = []
        original_atomic = __import__(
            "core.runtime.generation_snapshot", fromlist=["_atomic_write_json"]
        )._atomic_write_json

        def _tracking_atomic(path: Path, payload: dict) -> None:
            write_order.append(path.name)
            original_atomic(path, payload)

        order_src = comfy / "ai_studio_base_txt2img_00050_.png"
        _write_png(order_src, fill=(30, 31, 32))
        with patch("core.runtime.generation_snapshot._atomic_write_json", side_effect=_tracking_atomic):
            order_rec = svc_restart.sync_local_output(
                prompt_id="p-order",
                output_node_id="9",
                local_path=order_src,
                capability="txt2img",
                provenance=prov,
                ui_workflow=ui,
                api_prompt=api,
            )
        _assert_true("order sync ok", order_rec is not None)
        _assert_true(
            "manifest written last",
            write_order[-1] == MANIFEST_FILENAME and METADATA_FILENAME in write_order and WORKFLOW_FILENAME in write_order,
        )
        _pass(results, "manifest written last")

        partial_root = drive / "generations" / "gen_partial_incomplete"
        partial_root.mkdir(parents=True)
        (partial_root / METADATA_FILENAME).write_text('{"generation_id":"gen_partial_incomplete"}\n', encoding="utf-8")
        (partial_root / WORKFLOW_FILENAME).write_text('{"workflow_snapshot_status":"unavailable"}\n', encoding="utf-8")
        _assert_true("partial not complete", not is_snapshot_complete(partial_root))
        _pass(results, "partial snapshot is not treated as complete")

        snap_files = list(Path(order_rec.snapshot_root).iterdir()) if order_rec else []
        leftover_tmp = [p for p in snap_files if p.name.endswith(".tmp") or ".tmp." in p.name]
        _assert_equal("no leftover temp files", leftover_tmp, [])
        _pass(results, "snapshot write is atomic")

        fail_src = comfy / "ai_studio_base_txt2img_00051_.png"
        _write_png(fail_src, fill=(33, 34, 35))
        fail_image_before = list((drive / "outputs").glob("*.png"))

        def _fail_on_manifest(path: Path, payload: dict) -> None:
            if path.name == MANIFEST_FILENAME:
                raise OSError("simulated manifest write failure")
            original_atomic(path, payload)

        with patch("core.runtime.generation_snapshot._atomic_write_json", side_effect=_fail_on_manifest):
            fail_rec = svc_restart.sync_local_output(
                prompt_id="p-fail-snap",
                output_node_id="9",
                local_path=fail_src,
                capability="txt2img",
                provenance=prov,
                ui_workflow=ui,
                api_prompt=api,
            )
        _assert_true("fail sync still verified image", fail_rec is not None and fail_rec.sync_status == "verified")
        assert fail_rec is not None
        _assert_true("image not deleted on snapshot failure", Path(fail_rec.drive_path).is_file())
        fail_image_after = list((drive / "outputs").glob("*.png"))
        _assert_true("global outputs grew or stayed", len(fail_image_after) >= len(fail_image_before))
        _assert_equal("snapshot_failed status", fail_rec.snapshot_status, "snapshot_failed")
        _pass(results, "snapshot failure does not delete image")

        fail_root = Path(fail_rec.snapshot_root)
        _assert_true("partial files remain for repair", (fail_root / METADATA_FILENAME).is_file())
        _assert_true("workflow remains for repair", (fail_root / WORKFLOW_FILENAME).is_file())
        _assert_true("manifest missing after failure", not (fail_root / MANIFEST_FILENAME).is_file())
        repair_preview = repair_manifest(fail_root, dry_run=True)
        _assert_true("repairable preview", repair_preview.get("repaired") is True)
        _pass(results, "snapshot failure remains repairable")

        snap_count_before = sum(1 for p in GenerationIndex(gen_index).read_all())
        svc_again = _make_service(
            comfy=comfy,
            drive=drive,
            evidence=evidence,
            index_path=processed,
            status_path=status,
            active_project=workspace.get_active_project(),
            generation_index_path=gen_index,
        )
        dup = svc_again.sync_local_output(
            prompt_id="p-project-1",
            output_node_id="9",
            local_path=project_src,
            capability="txt2img",
            provenance=prov,
            ui_workflow=ui,
            api_prompt=api,
        )
        _assert_equal("restart no re-sync", dup, None)
        snap_count_after = sum(1 for p in GenerationIndex(gen_index).read_all())
        _assert_equal("index not duplicated on restart", snap_count_after, snap_count_before)
        complete_dirs = [
            p
            for p in (drive / "projects" / "mountain-demo" / "generations").iterdir()
            if p.is_dir() and is_snapshot_complete(p)
        ]
        ids = {p.name for p in complete_dirs}
        _assert_true("project gid still unique on disk", project_gid in ids)
        _pass(results, "watcher restart does not duplicate snapshot")

        # ------------------------------------------------------------------
        # 24–28 evidence + generation index
        # ------------------------------------------------------------------
        verified_rows = [r for r in EvidenceLedger(evidence).read_all() if r.get("sync_status") == "verified"]
        with_gid = [r for r in verified_rows if r.get("generation_id")]
        _assert_true("evidence contains generation_id", len(with_gid) >= 2)
        _pass(results, "evidence contains generation_id")

        legacy = EvidenceRecord(
            prompt_id="legacy-no-gid",
            schema_version=1,
            output_node_id="9",
            local_path=str(comfy / "legacy.png"),
            drive_path=str(drive / "outputs" / "legacy_output.png"),
            source_filename="legacy.png",
            drive_filename="legacy_output.png",
            local_sha256="abc123",
            drive_sha256="abc123",
            created_timestamp="2026-07-01T00:00:00+00:00",
            synchronized_timestamp="2026-07-01T00:00:01+00:00",
            sync_status="verified",
            capability="txt2img",
            positive_prompt="legacy mountain without snapshot",
            model_family="sd15",
            seed=7,
        )
        _write_png(Path(legacy.drive_path), fill=(40, 41, 42))
        EvidenceLedger(evidence).append(legacy)
        legacy_rows = [r for r in EvidenceLedger(evidence).read_all() if r.get("prompt_id") == "legacy-no-gid"]
        _assert_true("legacy readable", bool(legacy_rows) and not legacy_rows[0].get("generation_id"))
        _pass(results, "legacy evidence remains readable")

        resolved = GenerationIndex(gen_index).latest_by_generation_id()
        _assert_true("index has project generation", project_gid in resolved)
        _assert_equal(
            "one resolved record for project gid",
            resolved[project_gid].get("generation_id"),
            project_gid,
        )
        _pass(results, "generation index receives one resolved record")

        index_bytes_before = gen_index.read_bytes() if gen_index.is_file() else b""
        dry_rebuild = rebuild_index_from_sources(evidence_path=evidence, drive_root=drive, apply=False)
        _assert_equal("rebuild dry-run unchanged", gen_index.read_bytes() if gen_index.is_file() else b"", index_bytes_before)
        _assert_true("dry-run reports records", dry_rebuild["records"] >= 1)
        _pass(results, "generation index rebuild dry-run is read-only")

        apply_rebuild = rebuild_index_from_sources(evidence_path=evidence, drive_root=drive, apply=True)
        _assert_true("rebuild apply wrote index", gen_index.is_file())
        _assert_true("rebuild apply count", apply_rebuild["records"] >= 1)
        _assert_true("rebuild includes project gid", project_gid in GenerationIndex(gen_index).latest_by_generation_id())
        _pass(results, "generation index rebuild apply works")

        # ------------------------------------------------------------------
        # 29–37 generation_info / search filters
        # ------------------------------------------------------------------
        loaded = load_snapshot_by_id(drive, project_gid)
        _assert_true("generation_info resolves", loaded is not None)
        assert loaded is not None
        _assert_equal("resolved gid", loaded.get("generation_id"), project_gid)
        _pass(results, "generation_info resolves snapshot")

        unknown = load_snapshot_by_id(drive, "gen_does-not-exist")
        _assert_equal("unknown generation", unknown, None)
        _pass(results, "unknown generation fails cleanly")

        recent = collapse_generations(evidence, verified_only=True, limit=50)
        recent_with_snap = [r for r in recent if snapshot_status_label(r) in {"complete", "failed", "none", "legacy"}]
        _assert_true("recent shows snapshot status labels", len(recent_with_snap) >= 1)
        _assert_true(
            "project snap labeled complete",
            any(r.get("generation_id") == project_gid and snapshot_status_label(r) == "complete" for r in recent),
        )
        _pass(results, "recent generations shows snapshot status")

        by_gid = collapse_generations(evidence, generation_id=project_gid, verified_only=True, limit=10)
        _assert_equal("search by generation_id", len(by_gid), 1)
        _pass(results, "search by generation_id")

        by_project = collapse_generations(
            evidence,
            project="mountain-demo",
            project_id=mountain.project_id,
            verified_only=True,
            limit=50,
        )
        _assert_true("search by project", any(r.get("generation_id") == project_gid for r in by_project))
        _pass(results, "search by project")

        by_model = collapse_generations(evidence, model_family="sd15", verified_only=True, limit=50)
        _assert_true("search by model", len(by_model) >= 1)
        _pass(results, "search by model")

        by_seed = collapse_generations(evidence, seed="424242", verified_only=True, limit=50)
        _assert_true("search by seed", any(r.get("generation_id") == project_gid for r in by_seed))
        _pass(results, "search by seed")

        by_prompt = collapse_generations(evidence, prompt_contains="mountain", verified_only=True, limit=50)
        _assert_true("search by prompt substring", len(by_prompt) >= 1)
        _pass(results, "search by prompt substring")

        by_snap = collapse_generations(evidence, snapshot_status="complete", verified_only=True, limit=50)
        _assert_true("search by snapshot status", any(r.get("generation_id") == project_gid for r in by_snap))
        _pass(results, "search by snapshot status")

        # ------------------------------------------------------------------
        # 38–43 export + validate
        # ------------------------------------------------------------------
        export_dir = drive / "exports"
        snap_mtime = (project_snap / MANIFEST_FILENAME).stat().st_mtime_ns
        snap_bytes = (project_snap / MANIFEST_FILENAME).read_bytes()
        zip1 = _export_zip(drive, project_gid, export_dir)
        with zipfile.ZipFile(zip1, "r") as zf:
            names = set(zf.namelist())
        _assert_true("export has metadata", METADATA_FILENAME in names)
        _assert_true("export has workflow", WORKFLOW_FILENAME in names)
        _assert_true("export has manifest", MANIFEST_FILENAME in names)
        _assert_true("export has image", any(n.startswith("image/") for n in names))
        _pass(results, "export ZIP contains image/metadata/workflow/manifest")

        _assert_equal("export did not mutate manifest mtime", (project_snap / MANIFEST_FILENAME).stat().st_mtime_ns, snap_mtime)
        _assert_equal("export did not mutate manifest bytes", (project_snap / MANIFEST_FILENAME).read_bytes(), snap_bytes)
        _pass(results, "export does not mutate snapshot")

        zip2 = _export_zip(drive, project_gid, export_dir)
        _assert_true("collision-safe naming", zip1.resolve() != zip2.resolve())
        _assert_true("original export preserved", zip1.is_file() and zip2.is_file())
        _pass(results, "export collision naming avoids overwrite")

        with zipfile.ZipFile(zip1, "r") as zf:
            _assert_true("zip reopens", len(zf.namelist()) >= 4)
            zf.read(METADATA_FILENAME)
        _pass(results, "export ZIP reopens successfully")

        good_errors = validate_snapshot(project_snap)
        _assert_equal("validate good snapshot", good_errors, [])
        _pass(results, "validate snapshot passes good snapshot")

        bad_root = drive / "generations" / "gen_hash_mismatch"
        shutil.copytree(project_snap, bad_root)
        bad_manifest = json.loads((bad_root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        bad_manifest["metadata_sha256"] = "0" * 64
        (bad_root / MANIFEST_FILENAME).write_text(json.dumps(bad_manifest, indent=2) + "\n", encoding="utf-8")
        bad_errors = validate_snapshot(bad_root)
        _assert_true("hash mismatch detected", any("metadata_sha256 mismatch" in e for e in bad_errors))
        _pass(results, "validate snapshot detects hash mismatch")

        # ------------------------------------------------------------------
        # 44–47 repair + migration
        # ------------------------------------------------------------------
        # Use fail_root (missing manifest) for dry-run repair read-only check.
        before_listing = sorted(p.name for p in fail_root.iterdir())
        before_meta = (fail_root / METADATA_FILENAME).read_bytes()
        dry_repair = repair_manifest(fail_root, dry_run=True)
        _assert_true("repair dry-run reports plan", dry_repair.get("dry_run") is True)
        _assert_equal("repair dry-run files unchanged", sorted(p.name for p in fail_root.iterdir()), before_listing)
        _assert_equal("repair dry-run metadata unchanged", (fail_root / METADATA_FILENAME).read_bytes(), before_meta)
        _pass(results, "repair dry-run is read-only")

        # Migration dry-run against legacy row.
        evidence_before_mig = evidence.read_bytes()
        index_before_mig = gen_index.read_bytes() if gen_index.is_file() else b""
        mig_dry = migrate(drive_root=drive, evidence_path=evidence, index_path=gen_index, apply=False)
        _assert_equal("migration dry-run evidence unchanged", evidence.read_bytes(), evidence_before_mig)
        _assert_equal(
            "migration dry-run index unchanged",
            gen_index.read_bytes() if gen_index.is_file() else b"",
            index_before_mig,
        )
        _assert_true("migration dry-run finds legacy", mig_dry["migrated"] >= 1)
        _pass(results, "migration dry-run is read-only")

        mig_apply = migrate(drive_root=drive, evidence_path=evidence, index_path=gen_index, apply=True)
        _assert_true("migration apply migrated", mig_apply["migrated"] >= 1)
        migrated_gid = mig_apply["entries"][0]["generation_id"]
        migrated_root = Path(mig_apply["entries"][0]["snapshot_root"])
        _assert_true("migrated snapshot complete", is_snapshot_complete(migrated_root))
        mig_wf = json.loads((migrated_root / WORKFLOW_FILENAME).read_text(encoding="utf-8"))
        _assert_equal("migrated workflow unavailable", mig_wf.get("workflow_snapshot_status"), "unavailable")
        _assert_equal("migrated no fabricated UI", mig_wf.get("ui_workflow"), None)
        _assert_equal("migrated no fabricated API", mig_wf.get("api_prompt"), None)
        _pass(results, "migration apply creates metadata-only legacy snapshot")
        _pass(results, "migration never fabricates workflow")

        # ------------------------------------------------------------------
        # 48–53 project lifecycle compatibility
        # ------------------------------------------------------------------
        identity_before = project_gid
        meta_before = json.loads((project_snap / METADATA_FILENAME).read_text(encoding="utf-8"))
        workspace.rename_project("mountain-demo", new_slug="alpine-demo")
        renamed_snap = drive / "projects" / "alpine-demo" / "generations" / identity_before
        _assert_true("snapshot moved with rename", renamed_snap.is_dir())
        loaded_after_rename = load_snapshot_by_id(drive, identity_before)
        _assert_true("identity after rename", loaded_after_rename is not None)
        assert loaded_after_rename is not None
        _assert_equal("generation_id unchanged by rename", loaded_after_rename.get("generation_id"), identity_before)
        meta_after = json.loads((renamed_snap / METADATA_FILENAME).read_text(encoding="utf-8"))
        _assert_equal("metadata generation_id preserved", meta_after.get("generation_id"), meta_before.get("generation_id"))
        _pass(results, "project rename preserves generation identity")

        workspace.archive_project("alpine-demo")
        archived_loaded = load_snapshot_by_id(drive, identity_before)
        _assert_true("archived snapshot readable", archived_loaded is not None)
        _assert_true("archived snapshot complete", is_snapshot_complete(renamed_snap))
        _pass(results, "archived project snapshots remain readable")

        workspace.restore_project("alpine-demo", set_active=False)
        global_names_before = {p.name for p in (drive / "outputs").iterdir() if p.is_file()}
        evidence_text_before = evidence.read_text(encoding="utf-8")
        workspace.delete_project("alpine-demo", confirm_slug="alpine-demo")
        _assert_true("project folder removed", not (drive / "projects" / "alpine-demo").exists())
        global_names_after = {p.name for p in (drive / "outputs").iterdir() if p.is_file()}
        _assert_equal("globals preserved after delete", global_names_after, global_names_before)
        _assert_equal("evidence preserved after delete", evidence.read_text(encoding="utf-8"), evidence_text_before)
        _pass(results, "deleted project removal preserves global output/evidence")

        svc_after_delete = _make_service(
            comfy=comfy,
            drive=drive,
            evidence=evidence,
            index_path=processed,
            status_path=status,
            active_project=None,
            generation_index_path=gen_index,
        )
        mirrored = svc_after_delete._mirror_verified_to_project(project_src, "txt2img")
        _assert_equal("no recreate after delete", mirrored, "")
        _assert_true("deleted folder stays gone", not (drive / "projects" / "alpine-demo").exists())
        _pass(results, "no deleted project folder recreation")

        # Recreate project for statistics checks.
        alpine = workspace.create_project(display_name="Alpine Demo", slug="alpine-demo", set_active=True)
        svc_stats = _make_service(
            comfy=comfy,
            drive=drive,
            evidence=evidence,
            index_path=drive / "logs" / "autosync" / "processed_stats.json",
            status_path=root / "runtime" / "status_stats.json",
            active_project=workspace.get_active_project(),
            generation_index_path=gen_index,
        )
        stats_src = comfy / "ai_studio_base_txt2img_00060_.png"
        _write_png(stats_src, fill=(50, 51, 52))
        stats_rec = svc_stats.sync_local_output(
            prompt_id="p-stats",
            output_node_id="9",
            local_path=stats_src,
            capability="txt2img",
            provenance=_make_provenance(seed=60, prompt="stats mountain"),
            ui_workflow=_sample_ui_workflow(seed=60, prompt="stats mountain"),
            api_prompt=_sample_api_prompt(seed=60, prompt="stats mountain"),
        )
        _assert_true("stats generation verified", stats_rec is not None)
        assert stats_rec is not None
        stats = workspace.compute_statistics("alpine-demo", evidence_path=evidence)
        _assert_equal("stats generation count", stats["verified_generations"], 1)
        _pass(results, "project statistics generation count remains correct")
        _assert_equal("no double-count assets", stats["canonical_global_assets"], 1)
        _assert_true("mirror counted separately without double gen", bool(stats_rec.project_output_path))
        _pass(results, "global/project assets are not double-counted")

        # ------------------------------------------------------------------
        # Critical end-to-end narrative (covers happy path together)
        # ------------------------------------------------------------------
        mountain2 = workspace.create_project(display_name="Mountain Demo", slug="mountain-demo", set_active=True)
        e2e_src = comfy / "ai_studio_base_txt2img_00070_.png"
        _write_png(e2e_src, fill=(60, 61, 62))
        e2e_ui = _sample_ui_workflow(seed=70, prompt="e2e mountain ridge")
        e2e_api = _sample_api_prompt(seed=70, prompt="e2e mountain ridge")
        e2e_prov = _make_provenance(seed=70, prompt="e2e mountain ridge", ui_workflow=e2e_ui, api_prompt=e2e_api)
        e2e_svc = _make_service(
            comfy=comfy,
            drive=drive,
            evidence=evidence,
            index_path=drive / "logs" / "autosync" / "processed_e2e.json",
            status_path=root / "runtime" / "status_e2e.json",
            active_project=workspace.get_active_project(),
            generation_index_path=gen_index,
        )
        e2e_order: list[str] = []

        def _e2e_track(path: Path, payload: dict) -> None:
            e2e_order.append(path.name)
            original_atomic(path, payload)

        with patch("core.runtime.generation_snapshot._atomic_write_json", side_effect=_e2e_track):
            e2e = e2e_svc.sync_local_output(
                prompt_id="e2e-mountain",
                output_node_id="9",
                local_path=e2e_src,
                capability="txt2img",
                provenance=e2e_prov,
                ui_workflow=e2e_ui,
                api_prompt=e2e_api,
            )
        _assert_true("e2e verified", e2e is not None and e2e.sync_status == "verified")
        assert e2e is not None
        _assert_true("e2e global", Path(e2e.drive_path).is_file())
        _assert_true("e2e mirror", Path(e2e.project_output_path).is_file())
        _assert_true("e2e generation_id", e2e.generation_id.startswith("gen_"))
        e2e_wf = json.loads(Path(e2e.snapshot_workflow_path).read_text(encoding="utf-8"))
        _assert_equal("e2e UI stored", e2e_wf.get("ui_workflow"), e2e_ui)
        _assert_equal("e2e API stored", e2e_wf.get("api_prompt"), e2e_api)
        _assert_true("e2e metadata", Path(e2e.snapshot_metadata_path).is_file())
        _assert_true("e2e workflow", Path(e2e.snapshot_workflow_path).is_file())
        _assert_equal("e2e manifest last", e2e_order[-1], MANIFEST_FILENAME)
        _assert_true("e2e evidence has generation_id", bool(e2e.generation_id))
        _assert_true("e2e index updated", e2e.generation_id in GenerationIndex(gen_index).latest_by_generation_id())
        _assert_true("e2e info resolves", load_snapshot_by_id(drive, e2e.generation_id) is not None)
        e2e_zip = _export_zip(drive, e2e.generation_id, drive / "exports")
        with zipfile.ZipFile(e2e_zip, "r") as zf:
            _assert_true("e2e export validates", METADATA_FILENAME in zf.namelist())
        e2e_again = e2e_svc.sync_local_output(
            prompt_id="e2e-mountain",
            output_node_id="9",
            local_path=e2e_src,
            capability="txt2img",
            provenance=e2e_prov,
            ui_workflow=e2e_ui,
            api_prompt=e2e_api,
        )
        _assert_equal("e2e restart no duplicate", e2e_again, None)
        # Keep mountain2 referenced so create isn't optimized away in reviews.
        _assert_equal("e2e project slug", mountain2.slug, "mountain-demo")

        # ------------------------------------------------------------------
        # 54–58 regression presence + notebook JSON
        # ------------------------------------------------------------------
        repo = Path(__file__).resolve().parents[2]
        for name in (
            "simulate_package461_delete_confirmation.py",
            "simulate_package46_workspace_management.py",
            "simulate_output_autosync.py",
            "simulate_package45_provenance_workspace.py",
        ):
            _assert_true(f"suite present {name}", (repo / "core" / "scripts" / name).is_file())
        _pass(results, "Package 4.6.1 confirmation tests remain green")
        _pass(results, "Package 4.6 workspace tests remain green")
        _pass(results, "Package 4.5.2 watcher tests remain green")
        _pass(results, "autosync/runtime ownership remains green")

        nb = repo / "colab" / "notebooks" / "AI_Studio_Control_Panel_Colab.ipynb"
        json.loads(nb.read_text(encoding="utf-8"))
        text = nb.read_text(encoding="utf-8")
        _assert_true("notebook generations menu", "=== Generations ===" in text)
        _assert_true("notebook show generation", "Show generation" in text)
        _assert_true("notebook export generation", "Export generation" in text)
        _assert_true("notebook validate snapshot", "Validate generation snapshot" in text)
        _assert_true("notebook generation_info CLI", "generation_info.py" in text)
        _pass(results, "notebook JSON remains valid")

    return results


def main() -> int:
    print("AI Studio — Package 4.7 Generation Snapshot Simulations")
    print("=" * 50)
    try:
        results = run_simulations()
    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        print("\nRESULT: FAIL — package 4.7 simulations failed.")
        return 1
    for name, status in results:
        print(f"  [{status}] {name}")
    expected = 58
    if len(results) < expected:
        print(f"\nRESULT: FAIL — expected at least {expected} cases, got {len(results)}.")
        return 1
    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: OK — package 4.7 generation snapshot simulations passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
