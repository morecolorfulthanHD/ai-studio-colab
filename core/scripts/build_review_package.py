#!/usr/bin/env python3
"""Build a self-contained review_package.zip for Package 4 validation."""

from __future__ import annotations

import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def collect_files() -> list[Path]:
    paths: list[Path] = []

    def add(rel: str) -> None:
        path = REPO_ROOT / rel
        if path.is_file():
            paths.append(path)

    for runtime_file in sorted((REPO_ROOT / "core/runtime").glob("*.py")):
        paths.append(runtime_file)

    for script_name in (
        "cli_activate.py",
        "repo_bootstrap.py",
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
        "docs/model-compatibility-modern-editing.md",
        "docs/decisions/modern-editing-selection-gate.md",
        "docs/decisions/sd15-inpainting-quality-gate.md",
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


def main() -> int:
    files = collect_files()
    zip_path = REPO_ROOT / "review_package.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            rel = path.relative_to(REPO_ROOT).as_posix()
            archive.write(path, rel)
    print(f"Created {zip_path} with {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
