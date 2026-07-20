# Core Scripts

Cross-engine utility scripts for bootstrap, validation, and batch processing.

**All scripts use standard library Python only.** Safe to run in Colab without additional dependencies.

## Bootstrap & Validation (Phase 1)

| Script | Purpose | Installs? |
|--------|---------|-----------|
| `bootstrap_repo.py` | Validate repo structure; document git sync hook | No |
| `validate_environment.py` | Python, Colab, Drive, GPU checks | No |
| `validate_paths.py` | Validate Colab/Drive/repo paths from manifest | No |
| `validate_manifests.py` | Validate JSON schemas under `configs/` | No |
| `list_workflows.py` | List workflow JSON files by category | No |
| `sync_outputs.py` | **Maintenance/diagnostic:** manual copy of newest ComfyUI output to Drive (`--dry-run`, collision-safe rename) — not required after Package 4.4 autosync | No |
| `dogfood_core_runtime.py` | Sprint 1 dogfooding checks (PASS/WARN/FAIL summary) | No |
| `verify_generation.py` | **Maintenance/diagnostic:** read-only local/Drive generation evidence — superseded by automatic ledger for normal workflow | No |
| `list_inputs.py` | List eligible Drive input images and masks (read-only) | No |
| `prepare_workflow.py` | Prepare ephemeral runtime workflow JSON with selected inputs (`--dry-run`, `--json`, `--inspect`) | No |
| `inspect_mask.py` | Read-only mask diagnostics for inpainting (`--channel`, `--summary`, `--json`; use `--channel alpha` for embedded ComfyUI MASK) | No |
| `compare_inpainting_workflows.py` | Compare canonical and official reference inpainting workflows (`--summary`, `--json`) | No |
| `create_inpainting_diagnostic_fixture.py` | Generate synthetic RGB/mask/RGBA inpainting fixtures in a runtime directory | No |
| `prepare_inpainting_reference.py` | Prepare temporary official-reference workflow from one RGBA PNG (configured Colab paths; `--match-canonical-sampler`; `--positive-prompt` / `--negative-prompt`; `--dry-run`) | No |
| `prepare_qwen_image_edit.py` | Prepare temporary Qwen-Image-Edit-2511 benchmark workflow (`--allow-missing-models`, `--dry-run`) | No |
| `prepare_flux_fill.py` | Prepare temporary FLUX.1 Fill [dev] benchmark workflow (non-commercial license warning) | No |
| `run_output_watcher.py` | Runtime-aware event-driven autosync watcher (`--status`, read-only `--diagnose`, `--once`, `--no-websocket`) | No |
| `run_editing_benchmark.py` | Append editing benchmark ledger records | No |
| `report_editing_benchmark.py` | Report editing benchmark ledger | No |
| `simulate_output_autosync.py` | Package 4.5.2 autosync, runtime-ownership, stale-lock, and recovery simulations | No |
| `simulate_modern_editing_benchmark.py` | Package 4.4 modern editing benchmark simulations | No |
| `simulate_package45_provenance_workspace.py` | Package 4.5 provenance, truthfulness, workspace simulations | No |
| `simulate_package46_workspace_management.py` | Package 4.6 project lifecycle, stats, filters, watcher refresh simulations | No |
| `simulate_package461_delete_confirmation.py` | Package 4.6.1 notebook-safe delete/archive confirmation simulations | No |
| `simulate_package47_generation_snapshots.py` | Package 4.7 generation snapshot and reproducibility simulations | No |
| `generation_info.py` | Show generation snapshot details (`--generation-id`, `--json`) | No |
| `export_generation.py` | Export generation snapshot to ZIP (`--generation-id`) | No |
| `validate_generation_snapshot.py` | Validate snapshot integrity (`--generation-id`, `--all`) | No |
| `repair_generation_snapshot.py` | Repair missing manifest from metadata/workflow (`--dry-run`) | No |
| `rebuild_generation_index.py` | Rebuild generation index from evidence/snapshots | No |
| `migrate_generation_snapshots.py` | Migrate legacy verified rows to metadata snapshots | No |
| `list_generations.py` | Search generation evidence (`--generation-id`, filters, `--json`) | No |
| `list_project_assets.py` | List project assets with canonical + mirror paths | No |
| `show_generation.py` | Show evidence for one prompt ID (`--json`) | No |
| `report_generation_history.py` | Generation ledger summary and recent verified rows | No |
| `create_project.py` | Create project (`--name`, `--slug`, `--description`, `--tag`, `--set-active`) | No |
| `list_projects.py` | List projects (`--include-archived`, `--summary`, `--json`) | No |
| `show_project.py` | Show one project (`--project` / `--slug`) | No |
| `set_active_project.py` | Switch or clear active project (`--slug`, `--clear`) | No |
| `deactivate_project.py` | Clear active project; return to global-only mode | No |
| `rename_project.py` | Rename display name and/or project slug/folder | No |
| `archive_project.py` | Archive project (hides from default list; deactivates if active) | No |
| `restore_project.py` | Restore archived project (`--set-active` optional) | No |
| `delete_project.py` | Delete managed project folder (`--confirm-slug`, `--dry-run`); preserves global outputs/evidence | No |
| `project_statistics.py` | Authoritative project statistics from files + evidence | No |
| `migrate_projects.py` | Preview/apply Package 4.6 metadata migration (`--dry-run`, `--apply`) | No |
| `workflow_catalog.py` | User-facing workflow catalog with runtime/quality/production status | No |

## Runtime Verification (Phase 1b)

| Script | Purpose | Installs? |
|--------|---------|-----------|
| `check_nodes.py` | Compare `custom_nodes/` vs. `configs/nodes/node_registry.json` | No |
| `verify_models.py` | Check model files vs. `configs/models/model_registry.json` | No |

## Runtime Platform (Epic 2)

| Script | Purpose | Installs? |
|--------|---------|-----------|
| `runtime_report.py` | Unified health report (human, `--summary`, `--json`) | No |
| `validate_assets.py` | Asset registry validation (`--workflow`, `--type`, `--json`) | No |
| `validate_capabilities.py` | Capability readiness validation (`--capability`, `--json`) | No |

See [core/runtime/README.md](../runtime/README.md) and [docs/runtime-platform.md](../../docs/runtime-platform.md).

### Usage

```bash
# From repository root
python core/scripts/bootstrap_repo.py
python core/scripts/validate_environment.py
python core/scripts/validate_paths.py
python core/scripts/validate_manifests.py
python core/scripts/list_workflows.py
python core/scripts/runtime_report.py
python core/scripts/runtime_report.py --json
python core/scripts/validate_assets.py --summary
python core/scripts/validate_capabilities.py --summary
python core/scripts/check_nodes.py
python core/scripts/verify_models.py
python core/scripts/verify_models.py --require-inpainting
python core/scripts/sync_outputs.py --dry-run
python core/scripts/dogfood_core_runtime.py
python core/scripts/verify_generation.py --summary
python core/scripts/verify_generation.py --workflow img2img --summary
python core/scripts/list_inputs.py
python core/scripts/prepare_workflow.py --workflow img2img --input /path/to/image.png --dry-run
python core/scripts/simulate_package4_editing.py
```

`prepare_workflow.py` stages persistent Drive inputs into ComfyUI `input/` using SHA-256 content comparison before reuse. `--dry-run` is fully read-only (no directory creation, copies, or workflow writes). Inpainting preparation requires `512-inpainting-ema.safetensors`; use `verify_models.py --require-inpainting` before preparing inpainting workflows.

`verify_generation.py` filters evidence by workflow prefix. `validate_capabilities.py` reports `execution_input_status` separately from implementation readiness. Workflow validators require connected execution graphs — see `simulate_package4_editing.py`.

All user-facing scripts under `core/scripts/` resolve the repository root from the invoked script path (via `cli_activate.py` / `core/runtime/repo_paths.py`), so absolute-path invocation works from any working directory:

```bash
python /content/ai-studio-colab/core/scripts/sync_outputs.py --dry-run
python /content/ai-studio-colab/core/scripts/sync_outputs.py
python /content/ai-studio-colab/core/scripts/runtime_report.py --summary
python /content/ai-studio-colab/core/scripts/verify_generation.py --summary
```

`sync_outputs.py` selects only the newest eligible generated image/video file and ignores zero-byte placeholders such as `_output_images_will_be_put_here`. When the Drive destination filename already exists, the script writes a collision-safe UTC-timestamped name instead of overwriting.

See [docs/dogfooding/core-runtime-txt2img-checklist.md](../../docs/dogfooding/core-runtime-txt2img-checklist.md) for Colab validation steps.

### Notebook integration

- **Cell 3b** — Repository bootstrap validation (after Drive mount)
- **Cell 3c** — Runtime platform health (`runtime_report.py` + asset/capability summaries)

Post-install: `check_nodes.py`, `verify_models.py`. See [docs/colab-control-panel.md](../../docs/colab-control-panel.md).

## Planned Scripts (future)

| Script | Phase | Purpose |
|--------|-------|---------|
| `install_all.sh` | 1c | Orchestrate ComfyUI install + node install |
| `batch_runner.py` | 7 | Execute workflow chains over input datasets |

Colab-specific logic stays in `colab/utilities/`. Generic validation stays here.
