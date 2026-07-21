#!/usr/bin/env python3
"""Package 4.7.1 — Generations UX cleanup & identifier normalization simulations."""

from __future__ import annotations

import json
import os
import shutil
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

from core.runtime.generation_evidence_ledger import EvidenceLedger, EvidenceRecord, file_sha256
from core.runtime.generation_history import collapse_generations
from core.runtime.generation_identity import (
    InvalidGenerationIdError,
    format_generation_id_help,
    normalize_generation_id,
)
from core.runtime.generation_index import GenerationIndex, GenerationIndexRecord
from core.runtime.generation_snapshot import (
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    SNAPSHOT_SCHEMA_VERSION,
    WORKFLOW_FILENAME,
    file_content_sha256,
    global_generations_root,
    is_snapshot_complete,
    load_snapshot_by_id,
)
from core.runtime.png_utils import write_rgb_png
from core.runtime.workflow_provenance import hash_api_prompt, hash_ui_workflow


CANONICAL_ID = "gen_ed3c6ad8-644c-447e-969d-2ea48aa3e454"
BARE_UUID = "ed3c6ad8-644c-447e-969d-2ea48aa3e454"
UNKNOWN_UUID = "ed3c6ad8-644c-447e-969d-2ea48aa3e999"
UNKNOWN_CANONICAL = "gen_ed3c6ad8-644c-447e-969d-2ea48aa3e999"


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


def _assert_raises_invalid(label: str, value: str) -> None:
    try:
        normalize_generation_id(value)
    except InvalidGenerationIdError as exc:
        text = str(exc)
        _assert_true(f"{label} message", "Invalid generation ID" in text)
        return
    raise SimulationFailure(f"{label}: expected InvalidGenerationIdError")


def _write_png(path: Path, fill: tuple[int, int, int] = (10, 20, 30)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [[fill for _ in range(8)] for _ in range(8)]
    write_rgb_png(path, 8, 8, rows)


def _sample_ui() -> dict:
    return {
        "nodes": [
            {"id": 6, "type": "CLIPTextEncode", "widgets_values": ["a mountain landscape"]},
            {"id": 3, "type": "KSampler", "widgets_values": [424242, "fixed", 24, 7.0, "euler", "normal", 1.0]},
        ],
        "links": [],
        "version": 0.4,
    }


def _sample_api() -> dict:
    return {
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a mountain landscape"}},
        "3": {
            "class_type": "KSampler",
            "inputs": {"seed": 424242, "steps": 24, "cfg": 7.0, "sampler_name": "euler"},
        },
    }


def _make_temp_repo(real_repo: Path, drive_root: Path) -> Path:
    temp_repo = Path(tempfile.mkdtemp(prefix="ai-studio-pkg471-"))
    shutil.copytree(real_repo / "configs", temp_repo / "configs")
    paths_file = temp_repo / "configs" / "paths" / "colab_paths.json"
    data = json.loads(paths_file.read_text(encoding="utf-8"))
    root = str(drive_root).replace("\\", "/")
    path_map = data.setdefault("paths", {})
    path_map["drive_root"] = root
    path_map["drive_outputs"] = f"{root}/outputs"
    path_map["drive_logs"] = f"{root}/logs"
    path_map["drive_inputs"] = f"{root}/inputs"
    path_map["drive_masks"] = f"{root}/masks"
    path_map["drive_workflows"] = f"{root}/workflows"
    path_map["drive_models"] = f"{root}/models"
    paths_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return temp_repo


def _run_cli(real_repo: Path, temp_repo: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(real_repo / "core" / "scripts" / script),
        *args,
        "--repo-root",
        str(temp_repo),
    ]
    return subprocess.run(
        cmd,
        cwd=str(real_repo),
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def _create_fixture_snapshot(drive: Path, generation_id: str = CANONICAL_ID) -> Path:
    """Create a complete on-disk snapshot + evidence + index for live-pattern tests."""
    ui = _sample_ui()
    api = _sample_api()
    image = drive / "outputs" / "ai_studio_base_txt2img_00001_.png"
    _write_png(image, fill=(11, 22, 33))
    image_hash = file_sha256(image)

    snap_root = global_generations_root(drive) / generation_id
    snap_root.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema_version": 1,
        "generation_id": generation_id,
        "prompt_id": "p-live-1",
        "output_node_id": "9",
        "created_timestamp": "2026-07-20T12:00:00+00:00",
        "synchronized_timestamp": "2026-07-20T12:00:01+00:00",
        "project_id": "",
        "project_slug": "",
        "project_name": "",
        "capability": "txt2img",
        "workflow_identifier": "base/txt2img",
        "workflow_source": "registered_canonical",
        "workflow_hash": hash_ui_workflow(ui),
        "workflow_hash_type": "ui",
        "api_prompt_hash": hash_api_prompt(api),
        "model_family": "sd15",
        "model_files": ["sd15.safetensors"],
        "positive_prompt": "a mountain landscape",
        "negative_prompt": "blurry",
        "seed": 424242,
        "steps": 24,
        "cfg": 7.0,
        "sampler_name": "euler",
        "scheduler": "normal",
        "denoise": 1.0,
        "width": 512,
        "height": 768,
        "batch_size": 1,
        "source_filename": image.name,
        "drive_filename": image.name,
        "canonical_output_path": str(image),
        "project_output_path": "",
        "image_sha256": image_hash,
        "byte_size": image.stat().st_size,
        "sync_status": "verified",
        "provenance_status": "complete",
        "runtime_id": "sim-471",
        "repository_commit": "deadbeef",
        "package_version": "4.7.1",
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "workflow_snapshot_status": "complete",
    }
    workflow_payload = {"ui_workflow": ui, "api_prompt": api}
    (snap_root / METADATA_FILENAME).write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (snap_root / WORKFLOW_FILENAME).write_text(json.dumps(workflow_payload, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generation_id": generation_id,
        "created_timestamp": "2026-07-20T12:00:02+00:00",
        "snapshot_status": "complete",
        "metadata_file": METADATA_FILENAME,
        "workflow_file": WORKFLOW_FILENAME,
        "canonical_output_path": str(image),
        "project_output_path": "",
        "image_sha256": image_hash,
        "workflow_sha256": file_content_sha256(snap_root / WORKFLOW_FILENAME),
        "metadata_sha256": file_content_sha256(snap_root / METADATA_FILENAME),
    }
    (snap_root / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _assert_true("fixture snapshot complete", is_snapshot_complete(snap_root))

    evidence_path = drive / "logs" / "generation_evidence.jsonl"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    EvidenceLedger(evidence_path).append(
        EvidenceRecord(
            prompt_id="p-live-1",
            output_node_id="9",
            local_path=str(image),
            drive_path=str(image),
            drive_filename=image.name,
            local_sha256=image_hash,
            drive_sha256=image_hash,
            byte_size=image.stat().st_size,
            sync_status="verified",
            capability="txt2img",
            generation_id=generation_id,
            snapshot_root=str(snap_root),
            snapshot_status="complete",
            workflow_identifier="base/txt2img",
            positive_prompt="a mountain landscape",
            seed=424242,
            model_family="sd15",
            provenance_status="complete",
            synchronized_timestamp="2026-07-20T12:00:01+00:00",
            created_timestamp="2026-07-20T12:00:00+00:00",
        )
    )

    index_path = drive / "logs" / "generation_index.jsonl"
    GenerationIndex(index_path).append(
        GenerationIndexRecord(
            generation_id=generation_id,
            dedupe_key="p-live-1:9",
            prompt_id="p-live-1",
            output_node_id="9",
            capability="txt2img",
            created_timestamp="2026-07-20T12:00:00+00:00",
            canonical_output_path=str(image),
            snapshot_root=str(snap_root),
            snapshot_status="complete",
            image_sha256=image_hash,
            drive_filename=image.name,
        )
    )
    return snap_root


def run_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    repo = Path(__file__).resolve().parents[2]
    notebook = repo / "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb"
    nb_text = notebook.read_text(encoding="utf-8")
    nb_data = json.loads(nb_text)
    _assert_true("notebook JSON parses", isinstance(nb_data, dict))
    _pass(results, "Notebook JSON remains valid")

    # --- Normalization unit cases (1–10) ---
    _assert_equal("canonical unchanged", normalize_generation_id(CANONICAL_ID), CANONICAL_ID)
    _pass(results, "Canonical generation ID normalizes unchanged")

    _assert_equal("bare UUID", normalize_generation_id(BARE_UUID), CANONICAL_ID)
    _pass(results, "Bare UUID receives gen_ prefix")

    _assert_equal(
        "whitespace",
        normalize_generation_id(f"  {BARE_UUID}  "),
        CANONICAL_ID,
    )
    _pass(results, "Leading/trailing whitespace is removed")

    _assert_equal(
        "uppercase",
        normalize_generation_id("ED3C6AD8-644C-447E-969D-2EA48AA3E454"),
        CANONICAL_ID,
    )
    _assert_equal(
        "GEN_ uppercase",
        normalize_generation_id("GEN_ED3C6AD8-644C-447E-969D-2EA48AA3E454"),
        CANONICAL_ID,
    )
    _pass(results, "Uppercase UUID hex normalizes consistently")

    _assert_raises_invalid("malformed UUID", "ed3c6ad8-644c-447e-969d-2ea48aa3e45")
    _pass(results, "Malformed UUID is rejected")

    _assert_raises_invalid("arbitrary text", "not-a-generation-id")
    _pass(results, "Arbitrary text is rejected")

    _assert_raises_invalid("empty", "")
    _pass(results, "Empty string is rejected")

    _assert_raises_invalid("prefix only", "gen_")
    _pass(results, "`gen_` without UUID is rejected")

    _assert_raises_invalid("double prefix", f"gen_{CANONICAL_ID}")
    _pass(results, "Double prefix `gen_gen_...` is rejected")

    _assert_raises_invalid("filename", "ai_studio_base_txt2img_00001_.png")
    _assert_raises_invalid("path", f"outputs/{BARE_UUID}.png")
    _pass(results, "Filename input is rejected")

    help_text = format_generation_id_help()
    _assert_true("help mentions gen_", "gen_<UUID>" in help_text)
    _assert_true("help mentions bare", "<UUID>" in help_text)

    # --- CLI / lookup cases with fixture ---
    with tempfile.TemporaryDirectory() as tmp_name:
        drive = Path(tmp_name) / "AI_Studio"
        (drive / "outputs").mkdir(parents=True)
        (drive / "logs").mkdir(parents=True)
        snap_root = _create_fixture_snapshot(drive)
        temp_repo = _make_temp_repo(repo, drive)
        try:
            index_before = (drive / "logs" / "generation_index.jsonl").read_text(encoding="utf-8")
            evidence_before = (drive / "logs" / "generation_evidence.jsonl").read_text(encoding="utf-8")
            manifest_mtime = (snap_root / MANIFEST_FILENAME).stat().st_mtime_ns

            info_canon = _run_cli(
                repo, temp_repo, "generation_info.py", "--generation-id", CANONICAL_ID, "--json"
            )
            _assert_equal("info canonical exit", info_canon.returncode, 0)
            payload = json.loads(info_canon.stdout)
            _assert_equal("info canonical id", payload.get("generation_id"), CANONICAL_ID)
            _pass(results, "generation_info accepts canonical ID")

            info_bare = _run_cli(
                repo, temp_repo, "generation_info.py", "--generation-id", BARE_UUID, "--json"
            )
            _assert_equal("info bare exit", info_bare.returncode, 0)
            bare_payload = json.loads(info_bare.stdout)
            _assert_equal("info bare reports canonical", bare_payload.get("generation_id"), CANONICAL_ID)
            _pass(results, "generation_info accepts bare UUID")

            export_dir = drive / "exports"
            export_canon = _run_cli(
                repo,
                temp_repo,
                "export_generation.py",
                "--generation-id",
                CANONICAL_ID,
                "--output-dir",
                str(export_dir),
                "--json",
            )
            _assert_equal("export canonical exit", export_canon.returncode, 0)
            export_canon_payload = json.loads(export_canon.stdout)
            _assert_equal("export canonical id", export_canon_payload.get("generation_id"), CANONICAL_ID)
            _pass(results, "export_generation accepts canonical ID")

            export_bare = _run_cli(
                repo,
                temp_repo,
                "export_generation.py",
                "--generation-id",
                BARE_UUID,
                "--output-dir",
                str(export_dir),
                "--json",
            )
            _assert_equal("export bare exit", export_bare.returncode, 0)
            export_bare_payload = json.loads(export_bare.stdout)
            _assert_equal("export bare reports canonical", export_bare_payload.get("generation_id"), CANONICAL_ID)
            _assert_true("export zip exists", Path(str(export_bare_payload.get("export_path") or "")).is_file())
            _pass(results, "export_generation accepts bare UUID")

            val_canon = _run_cli(
                repo, temp_repo, "validate_generation_snapshot.py", "--generation-id", CANONICAL_ID, "--summary"
            )
            _assert_equal("validate canonical exit", val_canon.returncode, 0)
            _pass(results, "validate snapshot accepts canonical ID")

            val_bare = _run_cli(
                repo, temp_repo, "validate_generation_snapshot.py", "--generation-id", BARE_UUID, "--summary"
            )
            _assert_equal("validate bare exit", val_bare.returncode, 0)
            _pass(results, "validate snapshot accepts bare UUID")

            repair_canon = _run_cli(
                repo,
                temp_repo,
                "repair_generation_snapshot.py",
                "--generation-id",
                CANONICAL_ID,
                "--dry-run",
                "--json",
            )
            _assert_equal("repair canonical exit", repair_canon.returncode, 0)
            repair_canon_payload = json.loads(repair_canon.stdout)
            _assert_equal("repair canonical id", repair_canon_payload.get("generation_id"), CANONICAL_ID)
            _pass(results, "repair snapshot accepts canonical ID")

            repair_bare = _run_cli(
                repo,
                temp_repo,
                "repair_generation_snapshot.py",
                "--generation-id",
                BARE_UUID,
                "--dry-run",
                "--json",
            )
            _assert_equal("repair bare exit", repair_bare.returncode, 0)
            repair_bare_payload = json.loads(repair_bare.stdout)
            _assert_equal("repair bare reports canonical", repair_bare_payload.get("generation_id"), CANONICAL_ID)
            _pass(results, "repair snapshot accepts bare UUID")

            list_bare = _run_cli(
                repo, temp_repo, "list_generations.py", "--generation-id", BARE_UUID, "--json"
            )
            _assert_equal("list bare exit", list_bare.returncode, 0)
            list_rows = json.loads(list_bare.stdout)
            _assert_true("list matched one", len(list_rows) == 1)
            _assert_equal("list row id", list_rows[0].get("generation_id"), CANONICAL_ID)
            _pass(results, "list/search generation filter accepts bare UUID")

            index = GenerationIndex(drive / "logs" / "generation_index.jsonl")
            indexed = index.lookup_by_generation_id(BARE_UUID)
            _assert_true("index lookup found", indexed is not None)
            assert indexed is not None
            _assert_equal("index lookup id", indexed.get("generation_id"), CANONICAL_ID)
            _pass(results, "generation index lookup accepts bare UUID")

            # Notebook UX: helper + menu text
            _assert_true(
                "notebook Show normalizes",
                "normalize_notebook_generation_id" in nb_text
                and "Generation ID (gen_<uuid> or UUID):" in nb_text
                and "generation_info.py" in nb_text,
            )
            _pass(results, "notebook Show normalizes bare UUID")

            _assert_true(
                "notebook Export normalizes",
                "export_generation.py" in nb_text
                and "Generation ID (gen_<uuid> or UUID) to export:" in nb_text,
            )
            _pass(results, "notebook Export normalizes bare UUID")

            _assert_true(
                "notebook Validate normalizes",
                "validate_generation_snapshot.py" in nb_text
                and "Generation ID (gen_<uuid> or UUID) to validate" in nb_text,
            )
            _pass(results, "notebook Validate normalizes bare UUID")

            # Direct helper check with bare UUID (notebook code path)
            sys.path.insert(0, str(repo))
            from core.runtime.generation_identity import normalize_generation_id as nb_norm

            _assert_equal("notebook helper path", nb_norm(BARE_UUID), CANONICAL_ID)

            unknown = _run_cli(
                repo, temp_repo, "generation_info.py", "--generation-id", UNKNOWN_UUID, "--json"
            )
            _assert_equal("unknown exit", unknown.returncode, 1)
            unknown_text = (unknown.stdout or "") + (unknown.stderr or "")
            _assert_true("unknown message", "Generation not found" in unknown_text)
            _assert_true("unknown shows canonical", UNKNOWN_CANONICAL in unknown_text)
            _assert_true("unknown no traceback", "Traceback" not in unknown_text)
            _pass(results, "unknown valid UUID reports not found without traceback")

            malformed = _run_cli(
                repo, temp_repo, "generation_info.py", "--generation-id", "not-valid", "--json"
            )
            _assert_equal("malformed exit", malformed.returncode, 1)
            malformed_text = (malformed.stdout or "") + (malformed.stderr or "")
            _assert_true("malformed message", "Invalid generation ID" in malformed_text)
            _assert_true("malformed no traceback", "Traceback" not in malformed_text)
            _pass(results, "malformed input reports invalid without traceback")

            # Lookup must not mutate snapshot/index/evidence
            _assert_equal(
                "index unchanged after lookups",
                (drive / "logs" / "generation_index.jsonl").read_text(encoding="utf-8"),
                index_before,
            )
            _assert_equal(
                "evidence unchanged after lookups",
                (drive / "logs" / "generation_evidence.jsonl").read_text(encoding="utf-8"),
                evidence_before,
            )
            _assert_equal(
                "manifest mtime unchanged",
                (snap_root / MANIFEST_FILENAME).stat().st_mtime_ns,
                manifest_mtime,
            )
            snap_dirs = list((drive / "generations").iterdir()) if (drive / "generations").is_dir() else []
            _assert_equal("single snapshot dir", len([p for p in snap_dirs if p.is_dir()]), 1)
            loaded = load_snapshot_by_id(drive, BARE_UUID)
            _assert_true("load by bare", loaded is not None)
            assert loaded is not None
            _assert_equal("loaded id canonical", loaded.get("generation_id"), CANONICAL_ID)

            filtered = collapse_generations(
                drive / "logs" / "generation_evidence.jsonl",
                generation_id=BARE_UUID,
                verified_only=True,
                limit=10,
            )
            _assert_equal("collapse filter count", len(filtered), 1)
            _assert_equal("collapse filter id", filtered[0].get("generation_id"), CANONICAL_ID)

        finally:
            shutil.rmtree(temp_repo, ignore_errors=True)

    # --- Menu structure (26–29) ---
    _assert_true("workspace has Generations entry", '"12. Generations"' in nb_text or "12. Generations" in nb_text)
    workspace_block_start = nb_text.find("=== Workspace / Projects ===")
    gens_menu_start = nb_text.find("=== Generations ===")
    _assert_true("workspace block found", workspace_block_start >= 0)
    _assert_true("generations submenu found", gens_menu_start >= 0)
    workspace_slice = nb_text[workspace_block_start:gens_menu_start]
    _assert_true(
        "only one Generations entry in workspace",
        workspace_slice.count("12. Generations") == 1,
    )
    _assert_true(
        "workspace no direct Recent",
        "12. Recent generations" not in workspace_slice and "Recent generations" not in workspace_slice,
    )
    _assert_true(
        "workspace no direct Search",
        "13. Search generations" not in workspace_slice and "Search generations" not in workspace_slice,
    )
    _pass(results, "Workspace menu contains only one Generations entry")
    _pass(results, "Workspace menu no longer directly lists Recent generations")
    _pass(results, "Workspace menu no longer directly lists Search generations")

    gens_slice = nb_text[gens_menu_start : gens_menu_start + 2500]
    _assert_true("submenu Recent", "1. Recent generations" in gens_slice)
    _assert_true("submenu Search", "2. Search generations" in gens_slice)
    _assert_true("submenu Show", "3. Show generation" in gens_slice)
    _pass(results, "Generations submenu still includes Recent and Search")

    # --- Prior package sims remain green (31–34) ---
    prior_scripts = [
        ("simulate_package47_generation_snapshots.py", "Package 4.7 snapshot tests remain green"),
        ("simulate_package461_delete_confirmation.py", "Package 4.6.1 confirmation tests remain green"),
        ("simulate_package46_workspace_management.py", "Package 4.6 workspace tests remain green"),
        ("simulate_output_autosync.py", "Autosync/runtime ownership remains green"),
    ]
    for script_name, label in prior_scripts:
        proc = subprocess.run(
            [sys.executable, str(repo / "core" / "scripts" / script_name)],
            cwd=str(repo),
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        if proc.returncode != 0:
            detail = (proc.stdout or "")[-500:] + (proc.stderr or "")[-500:]
            raise SimulationFailure(f"{label}: exit {proc.returncode}\n{detail}")
        _pass(results, label)

    _pass(results, "Package 4.7.1 generations UX simulations complete")
    return results


def main() -> int:
    print("AI Studio — Package 4.7.1 Generations UX Simulations")
    print("=" * 50)
    try:
        results = run_simulations()
    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        print("\nRESULT: FAIL — package 4.7.1 simulations failed.")
        return 1
    except Exception as exc:  # noqa: BLE001 — surface unexpected failures cleanly
        print(f"  [FAIL] unexpected: {exc}")
        print("\nRESULT: FAIL — package 4.7.1 simulations failed.")
        return 1
    for name, status in results:
        print(f"  [{status}] {name}")
    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: PASS — package 4.7.1 generations UX simulations green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
