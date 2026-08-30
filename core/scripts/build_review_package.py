#!/usr/bin/env python3
"""Build a self-contained review_package.zip for Package 4+ validation.

Includes repository review contents plus optional generated handoff notes from
``review_handoff/`` (gitignored), packed as ``_handoff/`` inside the ZIP so
ChatGPT review can rely on a single upload without chat copy/paste.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HANDOFF_SOURCE_DIR = REPO_ROOT / "review_handoff"
HANDOFF_ZIP_PREFIX = "_handoff"
REQUIRED_HANDOFF_FILES = (
    "REVIEW_HANDOFF.md",
    "STATUS.md",
    "CHANGED_FILES.md",
    "VALIDATION.md",
    "NEXT_ACTION.md",
    "LIVE_EVIDENCE.md",
)


def collect_files() -> list[Path]:
    paths: list[Path] = []

    def add(rel: str) -> None:
        path = REPO_ROOT / rel
        if path.is_file():
            paths.append(path)

    for runtime_file in sorted((REPO_ROOT / "core/runtime").glob("*.py")):
        paths.append(runtime_file)

    add("core/comfyui/install.sh")
    add("core/comfyui/install_nodes.py")
    add("core/comfyui/README.md")

    for script_name in (
        "cli_activate.py",
        "repo_bootstrap.py",
        "build_review_package.py",
        "simulate_package3_hardening.py",
        "simulate_package4_editing.py",
        "validate_manifests.py",
        "prepare_workflow.py",
        "list_inputs.py",
        "inspect_mask.py",
        "compare_inpainting_workflows.py",
        "create_inpainting_diagnostic_fixture.py",
        "prepare_inpainting_reference.py",
        "prepare_qwen_image_edit.py",
        "prepare_flux_fill.py",
        "run_output_watcher.py",
        "run_editing_benchmark.py",
        "report_editing_benchmark.py",
        "simulate_output_autosync.py",
        "simulate_modern_editing_benchmark.py",
        "simulate_package45_provenance_workspace.py",
        "simulate_package46_workspace_management.py",
        "simulate_package461_delete_confirmation.py",
        "simulate_package47_generation_snapshots.py",
        "simulate_package471_generations_ux.py",
        "generation_info.py",
        "export_generation.py",
        "validate_generation_snapshot.py",
        "repair_generation_snapshot.py",
        "rebuild_generation_index.py",
        "migrate_generation_snapshots.py",
        "list_generations.py",
        "show_generation.py",
        "report_generation_history.py",
        "list_project_assets.py",
        "create_project.py",
        "list_projects.py",
        "show_project.py",
        "set_active_project.py",
        "deactivate_project.py",
        "rename_project.py",
        "archive_project.py",
        "restore_project.py",
        "delete_project.py",
        "project_statistics.py",
        "migrate_projects.py",
        "workflow_catalog.py",
        "workflow_info.py",
        "check_workflow_readiness.py",
        "list_prepared_workflows.py",
        "prepared_workflow_info.py",
        "validate_prepared_workflow.py",
        "open_prepared_workflow.py",
        "diagnose_prepared_workflow_loading.py",
        "diagnose_live_comfyui_workflow_open.py",
        "apply_comfyui_userdata_route_compat.py",
        "diagnose_prepared_execution_autosync.py",
        "reprepare_workflow.py",
        "prepare_from_generation.py",
        "prepare_variation_from_generation.py",
        "compare_generation_reproduction.py",
        "compare_generation_derivation.py",
        "simulate_package48_workflow_library.py",
        "simulate_package481_prepared_workflow_hotfix.py",
        "simulate_package482_prepared_workflow_integration.py",
        "simulate_package483_live_workflow_open_diagnostics.py",
        "simulate_package484_colab_userdata_route_compat.py",
        "simulate_package485_prepared_execution_autosync.py",
        "simulate_package49_prepared_execution_controls.py",
        "simulate_package491_project_mirror_canonical_naming.py",
        "simulate_package410_generation_reproduction.py",
        "simulate_package4101_custom_node_clone_resilience.py",
        "simulate_package4102_generation_reproduction_lookup.py",
        "simulate_package411_generation_derivation.py",
        "simulate_package4111_seed_precision.py",
        "simulate_package412_character_identity.py",
        "register_character.py",
        "list_characters.py",
        "show_character.py",
        "ensure_reactor_insightface_bridge.py",
        "ensure_faceid_runtime_bridge.py",
        "recover_identity_benchmark_history.py",
        "prepare_identity_benchmark.py",
        "backfill_identity_benchmark_preparation.py",
        "check_identity_benchmark_deps.py",
        "run_identity_benchmark.py",
        "report_identity_benchmark.py",
        "runtime_report.py",
        "verify_models.py",
        "verify_generation.py",
        "sync_outputs.py",
        "check_nodes.py",
        "dogfood_core_runtime.py",
    ):
        add(f"core/scripts/{script_name}")

    for config_file in sorted((REPO_ROOT / "configs").rglob("*.json")):
        paths.append(config_file)

    workflow_dirs = (
        "workflows/base/txt2img",
        "workflows/base/img2img",
        "workflows/base/inpainting",
        "workflows/base/outpainting",
        "workflows/diagnostics/inpainting_mask_preview",
        "workflows/reference/inpainting_official",
        "workflows/reference/qwen_image_edit",
        "workflows/reference/flux_fill",
        "workflows/reference/identity_reactor_benchmark",
        "workflows/reference/identity_faceid_benchmark",
    )
    for workflow_dir in workflow_dirs:
        for workflow_file in sorted((REPO_ROOT / workflow_dir).rglob("*")):
            if workflow_file.is_file():
                paths.append(workflow_file)

    package4_docs = [
        "README.md",
        "docs/architecture.md",
        "docs/colab-control-panel.md",
        "docs/installation.md",
        "docs/runtime-platform.md",
        "docs/troubleshooting.md",
        "docs/workflow-guide.md",
        "docs/workflow-library.md",
        "docs/model-compatibility-modern-editing.md",
        "docs/decisions/modern-editing-selection-gate.md",
        "docs/decisions/sd15-inpainting-quality-gate.md",
        "docs/decisions/identity-method-selection-gate.md",
        "docs/dogfooding/identity-method-benchmark-checklist.md",
        "docs/dogfooding/img2img-checklist.md",
        "docs/dogfooding/inpainting-checklist.md",
        "docs/dogfooding/inpainting-diagnostic-checklist.md",
        "docs/dogfooding/outpainting-checklist.md",
        "docs/dogfooding/output-autosync-checklist.md",
        "docs/dogfooding/modern-editing-benchmark-checklist.md",
        "docs/dogfooding/package45-runtime-truthfulness-provenance.md",
        "docs/dogfooding/workspace-foundation-checklist.md",
        "inputs/README.md",
        "inputs/images/README.md",
        "inputs/masks/README.md",
        "core/scripts/README.md",
        "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb",
    ]
    for rel in package4_docs:
        add(rel)

    unique: dict[str, Path] = {}
    for path in paths:
        rel = path.relative_to(REPO_ROOT).as_posix()
        unique[rel] = path
    return [unique[key] for key in sorted(unique)]


def collect_handoff_files() -> list[tuple[Path, str]]:
    """Return (source_path, zip_arcname) pairs for ``_handoff/`` entries."""
    if not HANDOFF_SOURCE_DIR.is_dir():
        raise FileNotFoundError(
            f"Missing handoff staging directory: {HANDOFF_SOURCE_DIR.as_posix()}\n"
            "Write review notes under review_handoff/ before building the ZIP."
        )
    entries: list[tuple[Path, str]] = []
    for path in sorted(HANDOFF_SOURCE_DIR.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(HANDOFF_SOURCE_DIR).as_posix()
        entries.append((path, f"{HANDOFF_ZIP_PREFIX}/{rel}"))
    missing = [name for name in REQUIRED_HANDOFF_FILES if not (HANDOFF_SOURCE_DIR / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing required handoff files under review_handoff/: " + ", ".join(missing)
        )
    if not entries:
        raise FileNotFoundError("review_handoff/ exists but contains no files")
    return entries


def main() -> int:
    files = collect_files()
    handoff = collect_handoff_files()
    zip_path = REPO_ROOT / "review_package.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            rel = path.relative_to(REPO_ROOT).as_posix()
            archive.write(path, rel)
        for source, arcname in handoff:
            archive.write(source, arcname)
    total = len(files) + len(handoff)
    print(f"Created {zip_path} with {total} files ({len(files)} repo + {len(handoff)} handoff)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
