# Troubleshooting

Common issues and diagnostics for AI Studio Colab.

## Dogfooding Support

For Sprint 1 Colab validation, run the read-only dogfooding script:

```bash
python core/scripts/dogfood_core_runtime.py
```

See [dogfooding/core-runtime-txt2img-checklist.md](dogfooding/core-runtime-txt2img-checklist.md) for the full pass/fail checklist.

`WARN` results are expected locally (no Colab GPU, ComfyUI, or SD1.5). `FAIL` indicates repository/schema problems.

## Bootstrap Scripts

Run these in order to diagnose setup issues:

```bash
python core/scripts/bootstrap_repo.py
python core/scripts/validate_environment.py
python core/scripts/validate_paths.py
python core/scripts/validate_manifests.py
python core/scripts/check_nodes.py
python core/scripts/verify_models.py
python core/comfyui/install_nodes.py --dry-run
python core/comfyui/install_models.py --dry-run
```

| Script | Exit code 1 means |
|--------|-------------------|
| `bootstrap_repo.py` | Missing top-level directories or config manifests |
| `validate_environment.py` | Rare — usually exits 0 with warnings |
| `validate_paths.py` | Missing required repo paths |
| `validate_manifests.py` | Invalid or incomplete JSON under `configs/` |
| `check_nodes.py` | One or more registered custom nodes missing from `custom_nodes/` |
| `verify_models.py` | Only when `--require-active-only` and an `active` model is missing |
| `runtime_report.py` | Exit 1 when overall health status is `fail` |
| `install_models.py --execute` | Required base model validation failed |

## Installation Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| ComfyUI fails to start | Missing dependencies | Re-run notebook install cells |
| Custom node import errors | Version mismatch | Check `configs/nodes/node_registry.json` |
| Model not found | Path misconfiguration | Verify `configs/paths/colab_paths.json` and Drive mount |
| Out of disk space | Large model downloads | Use Drive mount; prune runtime cache |
| `bootstrap_repo.py` fails | Repo not cloned fully | Re-clone; ensure all top-level dirs present |
| `validate_paths.py` warns on Colab paths | First run before install | Normal — install ComfyUI via notebook first |
| `install_nodes.py` reports clone failure | Repo unavailable or network issue | Re-run with `--execute`; optional node failures are reported |
| `verify_models.py` reports required missing model | SD 1.5 not found at expected path | Place `sd15.safetensors` in Drive shared checkpoint path |

## Launch Flow Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| Launch fails at ComfyUI install | Drive not mounted | Run Cell 2 (Drive mount) before Launch |
| `install.sh` fails with exit 1 | Drive path missing or extra_model_paths conflict | Read full stdout/stderr in notebook output; look for `[comfyui-install] ERROR` / `FATAL` lines |
| `install.sh` reports Drive not mounted | Skipped Cell 2 | Mount Drive; confirm `/content/drive/MyDrive` exists |
| `install.sh` reports invalid ComfyUI path | Leftover non-git `/content/ComfyUI` directory | Partial installs recover automatically; unknown directories require manual cleanup or `--force-reinstall --execute` |
| `install.sh` extra_model_paths user-managed conflict | Existing `extra_model_paths.yaml` without AI Studio markers | Merge the `ai_studio_drive` block manually; installer will not overwrite unrelated user config |
| `install.sh` requirements.txt missing | ComfyUI clone incomplete | Re-run with `--force-reinstall --execute` after reviewing install log |
| SD1.5 missing after launch | Checkpoint not on Drive | Place `sd15.safetensors` at expected path (no auto-download) |
| txt2img capability `partial` | SD1.5 or runtime prerequisite missing | Expected until SD1.5 present and generation succeeds |
| Full mode node install fails | Required node clone error | Check network; re-run `install_nodes.py --execute` |
| ComfyUI URL not shown | Port timeout | Check `/content/drive/MyDrive/AI_Studio/logs/comfyui.log` |

## ComfyUI Model Paths

AI Studio preserves ComfyUI's native local models directory:

```text
/content/ComfyUI/models
```

Persistent Google Drive models are exposed through ComfyUI's supported configuration file:

```text
/content/ComfyUI/extra_model_paths.yaml
```

The installer creates or updates only a clearly delimited **AI Studio-managed block**:

```text
# BEGIN AI_STUDIO_MANAGED
# END AI_STUDIO_MANAGED
```

Inspect after launch:

```bash
cat /content/ComfyUI/extra_model_paths.yaml
```

Expected Drive model root:

```text
/content/drive/MyDrive/AI_Studio/models/shared
```

Mapped subdirectories include: `checkpoints`, `controlnet`, `loras`, `vae`, `embeddings`, `upscale_models`, `clip`, `ipadapter`.

The installer does **not** replace or delete `/content/ComfyUI/models`. A fresh ComfyUI clone with a native `models/` directory is expected and supported.

## ComfyUI Runtime Directory Recovery

The installer classifies `/content/ComfyUI` before making changes:

| Classification | Meaning | Automatic action |
|----------------|---------|------------------|
| `missing` | Runtime path does not exist | Clone fresh |
| `valid_git_repo` | Valid ComfyUI git checkout with recognized origin | Pull latest changes |
| `empty_directory` | Directory exists but is empty | Remove empty dir, clone fresh |
| `partial_comfyui_install` | Strong ComfyUI-like evidence without `.git` | Archive, then clone fresh |
| `unknown_non_git_directory` | Unrelated or ambiguous contents | Stop safely with inventory |

Partial-install recovery requires strong evidence such as `main.py`, `requirements.txt`, `comfy/`, `nodes.py`, `folder_paths.py`, and related runtime folders. A directory is not treated as partial merely because it is named `ComfyUI`.

An **orphan `custom_nodes` runtime** — only `custom_nodes/` present, no `.git`, no `main.py`, no `requirements.txt`, and no other significant top-level entries — is recovered automatically as `partial_comfyui_install`. The installer archives it to `ComfyUI.broken.<UTC timestamp>`, clones fresh, and prints where `custom_nodes` was preserved in the archive. Custom nodes are **not** restored automatically.

Git repositories are treated as valid only when the `origin` remote matches `COMFYUI_REPO` or `Comfy-Org/ComfyUI` and distinctive ComfyUI paths are present. Unrecognized git repositories, including unrelated repos that happen to contain `main.py` and `requirements.txt`, are refused and never pulled automatically.

When recovery archives a runtime, it is renamed — never permanently deleted:

```text
/content/ComfyUI.broken.<UTC timestamp>
/content/ComfyUI.archived.<UTC timestamp>
```

Inspect archives:

```bash
ls -ld /content/ComfyUI.broken.* /content/ComfyUI.archived.*
```

Remove an old archive manually only after confirming it is no longer needed:

```bash
rm -rf /content/ComfyUI.broken.20260710T161500Z
```

For unrelated or user-managed runtime directories, the installer prints a concise inventory and refuses automatic deletion. Use `--force-reinstall --execute` only when you intentionally want the existing runtime archived and replaced.

Recovery never deletes Drive model content.

## Notebook Source of Truth

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| Stale notebook cells | Opened old Drive copy instead of GitHub | Use the [GitHub Colab link](https://colab.research.google.com/github/morecolorfulthanHD/ai-studio-colab/blob/main/colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb) |
| Repo code outdated | Skipped Repository Sync | Run Repository Sync before Cell 3b |
| Scripts not found after sync | Sync failed silently | Check Repository Sync output; confirm `/content/ai-studio-colab` exists |

## Control Panel / Notebook Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| Drive not mounted | Skipped mount cell | Run Drive mount cell in control panel |
| GPU not detected | CPU runtime selected | Runtime → Change runtime type → GPU |
| Wrong notebook | Duplicate launcher or stale Drive copy | Open canonical notebook from GitHub (see [colab-control-panel.md](colab-control-panel.md)) |
| Scripts not found | Repository Sync not run | Run Repository Sync cell; confirm `/content/ai-studio-colab` |
| Workflow not loading | Missing workflow JSON | Confirm `workflows/base/txt2img/workflow.json` exists in cloned repo |

## Generation Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| Black output image | VAE mismatch | Confirm VAE matches checkpoint in model registry |
| ControlNet has no effect | Wrong preprocessor / map | Re-run matching extraction workflow |
| Identity drift | Weak IPAdapter weight | Increase reference strength in preset |
| OOM (out of memory) | Resolution too high | Reduce resolution preset; enable model offloading |

## Colab-Specific Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| Session disconnected | Colab timeout | Save outputs to Drive via `sync_outputs.py` |
| Drive mount fails | Auth expired | Re-authenticate Google Drive in notebook |
| Slow generation | CPU-only runtime | Switch to GPU runtime in Colab settings |
| Outputs lost after session | Runtime wiped | Copy to Drive: `python core/scripts/sync_outputs.py` |

## Output Sync

`sync_outputs.py` copies **only the single newest eligible generated file** from ComfyUI output — not a bulk folder sync. Safe to run after generation.

The script resolves the repository root from its own location, so it works regardless of the caller's current working directory.

```bash
# Preview without copying (absolute path works from any cwd)
python /content/ai-studio-colab/core/scripts/sync_outputs.py --dry-run

# Copy latest eligible file only
python /content/ai-studio-colab/core/scripts/sync_outputs.py
```

Eligible outputs include common image/video extensions (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.mp4`, `.webm`). Zero-byte placeholders such as `_output_images_will_be_put_here` are ignored. If no eligible output exists, the script exits with a clear error.

Source: `/content/ComfyUI/output` → Destination: `/content/drive/MyDrive/AI_Studio/outputs`

## txt2img Readiness and Evidence

Base txt2img uses only native ComfyUI nodes. Optional custom-node packs such as **ComfyUI-ReActor** do not block readiness.

| Signal | Meaning |
|--------|---------|
| `txt2img` readiness `READY` | ComfyUI runtime, SD1.5, and base workflow dependencies are satisfied |
| evidence `NOT YET VERIFIED` | No eligible generated output detected yet |
| evidence `VERIFIED` / `verified_local` | Real generated output detected locally and/or on Drive |

```bash
python core/scripts/validate_capabilities.py --capability txt2img
python core/scripts/verify_generation.py --summary
```

## Reproducibility Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| Different output same seed | Node or model version drift | Pin versions in node/model registries |
| Workflow JSON won't load | ComfyUI version mismatch | Update ComfyUI or use compatible export |

## Reporting Issues

When reporting a problem, include:

1. Output of `validate_environment.py` and `validate_manifests.py`
2. Workflow ID from `configs/workflows/workflow_registry.json` (if applicable)
3. ComfyUI and custom node versions
4. Model checkpoint used
5. Preset name from `configs/presets/default_generation_presets.json`
6. Full error log from ComfyUI console
