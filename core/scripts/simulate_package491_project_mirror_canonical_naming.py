#!/usr/bin/env python3
"""Package 4.9.1 — project mirror must reuse canonical global Drive basenames."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime import output_autosync
from core.runtime.comfyui_workflow_loading import build_comfyui_load_workflow
from core.runtime.generation_evidence_ledger import EvidenceLedger, file_sha256
from core.runtime.output_autosync import AUTOSYNC_TEMP_PREFIX, OutputAutoSyncService
from core.runtime.png_utils import write_rgb_png
from core.runtime.project_workspace import ProjectWorkspace
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_provenance import hash_ui_workflow, load_registered_workflow_hashes
from core.scripts.diagnose_prepared_execution_autosync import diagnose

PREP_ID = "prep_bccdc15d-c8b9-4de3-bdc9-529180a7959f"
SAVE_PREFIX = "ai_studio_package49_fixed"
SEED = 135791357


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


def _write_png(path: Path, fill: tuple[int, int, int] = (10, 20, 30)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [[fill for _ in range(8)] for _ in range(8)]
    write_rgb_png(path, 8, 8, rows)


def _drive_finals(drive_out: Path) -> list[Path]:
    if not drive_out.is_dir():
        return []
    return sorted(
        path
        for path in drive_out.iterdir()
        if path.is_file() and not path.name.startswith(AUTOSYNC_TEMP_PREFIX)
    )


def _txt2img_api(*, seed: int = SEED) -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd15.safetensors"}},
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "package 491 fixed cache repeat", "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "blurry, low quality", "clip": ["4", 1]},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 768, "batch_size": 1},
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
                "latent_image": ["5", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": SAVE_PREFIX, "images": ["8", 0]},
        },
    }


def _prepared_ui(repo_root: Path) -> dict:
    canonical = json.loads(
        (repo_root / "workflows/base/txt2img/workflow.json").read_text(encoding="utf-8")
    )
    prepared = copy.deepcopy(canonical)
    extra = prepared.setdefault("extra", {})
    if not isinstance(extra, dict):
        prepared["extra"] = {}
        extra = prepared["extra"]
    extra["ai_studio"] = {
        "workflow_identifier": "base/txt2img",
        "workflow_source": "registered_canonical",
        "preparation_id": PREP_ID,
        "prepared_workflow_hash": "",
        "canonical_workflow_hash": hash_ui_workflow(canonical),
        "seed": SEED,
        "seed_mode": "fixed",
        "control_after_generate": "fixed",
        "package_version": "4.9",
    }
    prepared_hash = hash_ui_workflow(prepared)
    extra["ai_studio"]["prepared_workflow_hash"] = prepared_hash
    return build_comfyui_load_workflow(prepared)


def _history_entry(api_prompt: dict, ui_workflow: dict | None, outputs: dict, prompt_id: str) -> dict:
    extra_data: dict = {}
    if ui_workflow is not None:
        extra_data = {"extra_pnginfo": {"workflow": ui_workflow}}
    return {
        "prompt": [0, prompt_id, api_prompt, extra_data, list(outputs.keys()) or ["9"]],
        "outputs": outputs,
        "status": {
            "status_str": "success",
            "completed": True,
            "messages": [["execution_cached", {"nodes": ["3", "4", "5", "6", "7", "8", "9"]}]],
        },
    }


def _flat_output(filename: str) -> dict:
    return {"9": {"images": [{"filename": filename, "subfolder": "", "type": "output"}]}}


def _service(tmp: Path, *, registered: dict, active_project=None, repo_root: Path | None = None):
    comfy = tmp / "ComfyUI" / "output"
    drive_root = tmp / "AI_Studio"
    drive_out = drive_root / "outputs"
    comfy.mkdir(parents=True)
    drive_out.mkdir(parents=True)
    svc = OutputAutoSyncService(
        comfy_output_dir=comfy,
        drive_output_dir=drive_out,
        evidence_path=drive_root / "logs" / "generation_evidence.jsonl",
        index_path=drive_root / "logs" / "autosync" / "output_watcher_processed.json",
        status_path=tmp / "watcher_status.json",
        base_url="http://127.0.0.1:9",
        sleep_fn=lambda _s: None,
        max_copy_retries=1,
        registered_hashes=registered,
        active_project=active_project,
        drive_root=drive_root,
        repo_root=repo_root,
    )
    return svc, comfy, drive_root, drive_out


def _handle(svc: OutputAutoSyncService, history: dict, prompt_id: str):
    original = output_autosync.fetch_history
    output_autosync.fetch_history = lambda base_url, prompt_id=None, **_kwargs: (
        history if prompt_id is None else {prompt_id: history[prompt_id]}
    )
    try:
        return svc.handle_prompt_id(prompt_id)
    finally:
        output_autosync.fetch_history = original


def main() -> int:
    results: list[tuple[str, str]] = []
    repo_root = find_repo_root(script_file=Path(__file__))
    print("Package 4.9.1 project mirror canonical naming simulations")
    print("=" * 60)

    try:
        bundle = RegistryLoader(repo_root).load_all()
        registered = load_registered_workflow_hashes(repo_root, bundle.workflows)
        prepared_ui = _prepared_ui(repo_root)

        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            workspace = ProjectWorkspace(tmp / "AI_Studio")
            (tmp / "AI_Studio" / "outputs").mkdir(parents=True)
            (tmp / "AI_Studio" / "logs").mkdir(parents=True)
            mountain = workspace.create_project(
                display_name="Mountain Demo", slug="mountain-demo", set_active=True
            )

            # ------------------------------------------------------------------
            # Cached fixed-seed repeats: identical SHA, same Comfy filename,
            # four distinct global + four matching project basenames.
            # ------------------------------------------------------------------
            svc, comfy, drive_root, drive_out = _service(
                tmp / "cached-repeats",
                registered=registered,
                active_project=mountain,
                repo_root=repo_root,
            )
            # Simulate ComfyUI cache reuse: same local filename bytes each time.
            local_name = f"{SAVE_PREFIX}_00001_.png"
            local_path = comfy / local_name
            _write_png(local_path, fill=(19, 82, 45))
            identical_sha = file_sha256(local_path)

            prompt_ids = [
                "9c4702f9-0cf6-46cd-bb6e-1997eaa698ba",
                "dd8c94ca-f716-417f-883f-b4a09a0bee73",
                "4e290a5e-ffa7-4eb8-a4c4-91d28d3739a5",
                "e1d2244d-dbf1-46d6-b648-1d4695fc8de8",
            ]
            history: dict = {}
            verified_records = []
            for prompt_id in prompt_ids:
                history[prompt_id] = _history_entry(
                    _txt2img_api(seed=SEED),
                    prepared_ui,
                    _flat_output(local_name),
                    prompt_id,
                )
                recs, resolved = _handle(svc, history, prompt_id)
                _assert_true(f"{prompt_id} resolved", resolved and recs)
                _assert_equal(f"{prompt_id} verified", recs[0].sync_status, "verified")
                _assert_equal(f"{prompt_id} seed", recs[0].seed, SEED)
                _assert_equal(f"{prompt_id} prep", recs[0].preparation_id, PREP_ID)
                _assert_equal(f"{prompt_id} sha", recs[0].drive_sha256, identical_sha)
                verified_records.append(recs[0])

            globals_out = _drive_finals(drive_out)
            project_out = Path(mountain.outputs_dir)
            project_files = _drive_finals(project_out)
            _assert_equal("four global outputs", len(globals_out), 4)
            _assert_equal("four project mirrors", len(project_files), 4)
            global_names = [p.name for p in globals_out]
            project_names = [p.name for p in project_files]
            # Sequences are day-relative; assert contiguous 000001..000004 for capability.
            for index, name in enumerate(global_names, start=1):
                _assert_true(
                    f"global seq {index}",
                    name.startswith("txt2img_") and name.endswith(f"_{index:06d}.png"),
                )
            _assert_equal("project names match global basenames", project_names, global_names)
            for rec, global_path in zip(verified_records, globals_out):
                _assert_equal("evidence global path", Path(rec.drive_path).name, global_path.name)
                _assert_equal(
                    "evidence project basename matches global",
                    Path(rec.project_output_path).name,
                    global_path.name,
                )
                _assert_true("generation id present", bool(rec.generation_id))
                snap_meta = Path(rec.snapshot_metadata_path)
                _assert_true("snapshot metadata exists", snap_meta.is_file())
                meta = json.loads(snap_meta.read_text(encoding="utf-8"))
                _assert_equal("snapshot prep", meta.get("preparation_id"), PREP_ID)
                _assert_equal("snapshot seed", meta.get("seed"), SEED)
            generation_ids = {rec.generation_id for rec in verified_records}
            _assert_equal("four generation ids", len(generation_ids), 4)
            prompt_set = {rec.prompt_id for rec in verified_records}
            _assert_equal("four prompt ids", len(prompt_set), 4)
            _pass(results, "cached identical-SHA repeats allocate four global sequences")
            _pass(results, "project mirrors reuse exact canonical global basenames")
            _pass(results, "four distinct generation IDs and snapshots preserved")
            _pass(results, "fixed-mode cache repeats do not content-collapse project mirrors")

            # Idempotent remirror of same canonical basename + same bytes.
            again = svc._mirror_verified_to_project(
                globals_out[0],
                "txt2img",
                canonical_destination=globals_out[0],
            )
            _assert_equal("idempotent mirror path", again, str(project_out / globals_out[0].name))
            _assert_equal("still four project files", len(_drive_finals(project_out)), 4)
            _pass(results, "existing same-execution project mirror is idempotent")

            # Unrelated bytes at intended project path -> fail closed.
            collision_tmp = tmp / "collision"
            svc_c, comfy_c, drive_c, out_c = _service(
                collision_tmp, registered=registered, active_project=mountain, repo_root=repo_root
            )
            # Reuse mountain project dir intentionally.
            svc_c.active_project = mountain
            occupied_name = "txt2img_20990101_000777.png"
            occupied = project_out / occupied_name
            _write_png(occupied, fill=(1, 1, 1))
            unrelated_source = comfy_c / "unrelated_src.png"
            _write_png(unrelated_source, fill=(9, 9, 9))
            before_hash = file_sha256(occupied)
            refused = svc_c._mirror_verified_to_project(
                unrelated_source,
                "txt2img",
                canonical_destination=Path(occupied_name),
            )
            _assert_equal("collision refused", refused, "")
            _assert_equal("occupied bytes unchanged", file_sha256(occupied), before_hash)
            _pass(results, "unrelated project-path collision fails closed without overwrite")

            # Global verified even if project mirror collides.
            collide_prompt = "prompt-collide-global-ok"
            local_collide = comfy_c / f"{SAVE_PREFIX}_collide.png"
            _write_png(local_collide, fill=(2, 3, 4))
            # Force next global name, then pre-create matching project basename with other bytes.
            # Simpler path: sync normally, then manually create collision scenario via direct API.
            # Use a dedicated project for isolation.
            collide_project = workspace.create_project(
                display_name="Collision Demo", slug="collision-demo", set_active=False
            )
            svc_c.active_project = collide_project
            Path(collide_project.outputs_dir).mkdir(parents=True, exist_ok=True)
            # Pre-occupy the first allocated permanent name's project counterpart after sync by
            # syncing once to learn the name, then... instead pre-seed max sequence.
            preseed = Path(collide_project.outputs_dir) / "txt2img_20991231_000001.png"
            # Allocate under today's stamp by syncing one output first without preseed, then
            # for the second execution pre-create the next expected name with wrong bytes.
            hist1 = {
                "p-ok": _history_entry(
                    _txt2img_api(seed=1), prepared_ui, _flat_output(local_collide.name), "p-ok"
                )
            }
            recs_ok, resolved_ok = _handle(svc_c, hist1, "p-ok")
            _assert_true("first collide sync ok", resolved_ok and recs_ok and recs_ok[0].sync_status == "verified")
            first_global = Path(recs_ok[0].drive_path)
            # Pre-create next sequence basename in project with unrelated bytes.
            # Parse sequence from first_global and +1.
            stem_parts = first_global.stem.split("_")
            next_seq = int(stem_parts[-1]) + 1
            next_name = f"{stem_parts[0]}_{stem_parts[1]}_{next_seq:06d}.png"
            poison = Path(collide_project.outputs_dir) / next_name
            _write_png(poison, fill=(8, 8, 8))
            poison_hash = file_sha256(poison)
            local2 = comfy_c / f"{SAVE_PREFIX}_collide2.png"
            _write_png(local2, fill=(5, 5, 5))
            hist2 = {
                "p-ok": hist1["p-ok"],
                "p-collide": _history_entry(
                    _txt2img_api(seed=2), prepared_ui, _flat_output(local2.name), "p-collide"
                ),
            }
            recs_bad, resolved_bad = _handle(svc_c, hist2, "p-collide")
            _assert_true(
                "global still verified despite mirror collision",
                resolved_bad and recs_bad and recs_bad[0].sync_status == "verified",
            )
            _assert_true("global file exists", Path(recs_bad[0].drive_path).is_file())
            _assert_equal("canonical basename expected", Path(recs_bad[0].drive_path).name, next_name)
            _assert_equal("project path empty on collision", recs_bad[0].project_output_path, "")
            _assert_true(
                "collision message recorded",
                "project_mirror_unavailable_or_collision" in (recs_bad[0].messages or []),
            )
            _assert_equal("poisoned project file untouched", file_sha256(poison), poison_hash)
            _pass(results, "project mirror failure does not corrupt verified global output")

            # Global mode: no project mirror.
            svc_g, comfy_g, drive_g, out_g = _service(
                tmp / "global-only", registered=registered, active_project=None, repo_root=repo_root
            )
            local_g = comfy_g / f"{SAVE_PREFIX}_global.png"
            _write_png(local_g, fill=(7, 7, 7))
            hist_g = {
                "p-global": _history_entry(
                    _txt2img_api(seed=7), prepared_ui, _flat_output(local_g.name), "p-global"
                )
            }
            recs_g, resolved_g = _handle(svc_g, hist_g, "p-global")
            _assert_true("global mode verified", resolved_g and recs_g and recs_g[0].sync_status == "verified")
            _assert_equal("global mode no project path", recs_g[0].project_output_path, "")
            _pass(results, "global mode still produces no project mirror")

            # Non-cached normal executions with distinct local filenames remain 1:1.
            svc_n, comfy_n, drive_n, out_n = _service(
                tmp / "normal",
                registered=registered,
                active_project=mountain,
                repo_root=repo_root,
            )
            # Use a fresh project to avoid colliding with earlier mountain files? mountain already
            # has files; new global sequences continue. Create dedicated project.
            normal_project = workspace.create_project(
                display_name="Normal Demo", slug="normal-demo", set_active=False
            )
            svc_n.active_project = normal_project
            Path(normal_project.outputs_dir).mkdir(parents=True, exist_ok=True)
            names = [f"{SAVE_PREFIX}_n1.png", f"{SAVE_PREFIX}_n2.png"]
            fills = [(11, 0, 0), (0, 11, 0)]
            hist_n: dict = {}
            normal_recs = []
            for idx, (name, fill) in enumerate(zip(names, fills), start=1):
                _write_png(comfy_n / name, fill=fill)
                pid = f"prompt-normal-{idx}"
                hist_n[pid] = _history_entry(
                    _txt2img_api(seed=SEED + idx), prepared_ui, _flat_output(name), pid
                )
                recs_n, resolved_n = _handle(svc_n, hist_n, pid)
                _assert_true(f"normal {idx}", resolved_n and recs_n and recs_n[0].sync_status == "verified")
                normal_recs.append(recs_n[0])
            for rec in normal_recs:
                _assert_equal(
                    "normal basename match",
                    Path(rec.drive_path).name,
                    Path(rec.project_output_path).name,
                )
            _assert_equal("normal two globals", len(_drive_finals(out_n)), 2)
            _assert_equal("normal two projects", len(_drive_finals(Path(normal_project.outputs_dir))), 2)
            _pass(results, "non-cached normal executions unchanged with one-for-one mirrors")

            # Batch outputs inherit corresponding canonical filenames one-for-one.
            svc_b, comfy_b, drive_b, out_b = _service(
                tmp / "batch",
                registered=registered,
                active_project=None,
                repo_root=repo_root,
            )
            batch_project = workspace.create_project(
                display_name="Batch Demo", slug="batch-demo", set_active=False
            )
            svc_b.active_project = batch_project
            Path(batch_project.outputs_dir).mkdir(parents=True, exist_ok=True)
            batch_a = f"{SAVE_PREFIX}_batch_00001_.png"
            batch_b = f"{SAVE_PREFIX}_batch_00002_.png"
            _write_png(comfy_b / batch_a, fill=(1, 2, 3))
            _write_png(comfy_b / batch_b, fill=(4, 5, 6))
            batch_outputs = {
                "9": {
                    "images": [
                        {"filename": batch_a, "subfolder": "", "type": "output"},
                        {"filename": batch_b, "subfolder": "", "type": "output"},
                    ]
                }
            }
            hist_b = {
                "prompt-batch": _history_entry(
                    _txt2img_api(seed=42), prepared_ui, batch_outputs, "prompt-batch"
                )
            }
            recs_b, resolved_b = _handle(svc_b, hist_b, "prompt-batch")
            _assert_true("batch resolved", resolved_b)
            _assert_equal("batch two records", len(recs_b), 2)
            _assert_true("batch all verified", all(r.sync_status == "verified" for r in recs_b))
            _assert_equal("batch same prompt", recs_b[0].prompt_id, recs_b[1].prompt_id)
            _assert_true("batch distinct gens", recs_b[0].generation_id != recs_b[1].generation_id)
            for rec in recs_b:
                _assert_equal(
                    "batch basename match",
                    Path(rec.drive_path).name,
                    Path(rec.project_output_path).name,
                )
            _assert_equal("batch two project files", len(_drive_finals(Path(batch_project.outputs_dir))), 2)
            _pass(results, "batch outputs inherit corresponding canonical filenames one-for-one")

            # Diagnostic wording: exact history outputs must not report recovery insufficiency.
            # Build a tiny Drive layout the diagnose helper can read via a temp repo paths override
            # is heavy; instead unit-call analyze + diagnostic related-item logic through service.
            svc_d, comfy_d, drive_d, out_d = _service(
                tmp / "diag", registered=registered, active_project=None, repo_root=repo_root
            )
            local_d = comfy_d / f"{SAVE_PREFIX}_diag.png"
            _write_png(local_d, fill=(3, 3, 3))
            hist_d = {
                "prompt-diag": _history_entry(
                    _txt2img_api(seed=SEED), prepared_ui, _flat_output(local_d.name), "prompt-diag"
                )
            }
            recs_d, resolved_d = _handle(svc_d, hist_d, "prompt-diag")
            _assert_true("diag sync", resolved_d and recs_d)
            # After verified, recovery analysis for the same exact history should not claim insufficiency.
            analysis_after = svc_d.analyze_saveimage_prefix_recovery(
                hist_d["prompt-diag"], prompt_id="prompt-diag"
            )
            _assert_equal(
                "already verified exact history reason",
                analysis_after["attribution_reason"],
                "exact_history_filename_already_verified",
            )
            _assert_equal("exact history count", analysis_after["exact_history_file_count"], 1)
            _assert_true(
                "not insufficient",
                analysis_after["attribution_reason"] != "insufficient_attribution_evidence",
            )
            _pass(results, "diagnostic exact-history wording no longer reports insufficiency")

            # Source-level confirmation diagnostic prefers exact_history_outputs when extractable.
            diag_src = (
                repo_root / "core/scripts/diagnose_prepared_execution_autosync.py"
            ).read_text(encoding="utf-8")
            _assert_true("diag exact_history_outputs", 'attribution_reason = "exact_history_outputs"' in diag_src)
            _assert_true(
                "diag keeps recovery reason separately",
                "prefix_recovery_attribution_reason" in diag_src,
            )
            _pass(results, "read-only diagnostic reports exact history resolution truthfully")

        # Source contracts / no automation expansion.
        autosync_src = (repo_root / "core/runtime/output_autosync.py").read_text(encoding="utf-8")
        _assert_true("inherits canonical basename", "canonical_destination" in autosync_src)
        _assert_true("no content-collapse scan", "for existing in project_outputs.iterdir()" not in autosync_src)
        _assert_true("autosync no /prompt", "/prompt" not in autosync_src)
        compat = (repo_root / "core/runtime/comfyui_userdata_route_compat.py").read_text(encoding="utf-8")
        _assert_true("4.8.4 untouched marker", "ai_studio_userdata_route_compat_4_8_4" in compat)
        _pass(results, "no independent project sequencing")
        _pass(results, "4.8.4 userdata compatibility preserved")
        _pass(results, "no /prompt automation expansion")

        build_text = (repo_root / "core/scripts/build_review_package.py").read_text(encoding="utf-8")
        _assert_true(
            "review package lists 4.9.1",
            "simulate_package491_project_mirror_canonical_naming.py" in build_text,
        )
        _pass(results, "Package 4.9.1 project mirror canonical naming simulations complete")

    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        print("\nRESULT: FAIL — package 4.9.1 simulations failed.")
        return 1

    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: PASS — package 4.9.1 project mirror canonical naming green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
