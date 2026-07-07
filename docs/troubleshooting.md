# Troubleshooting

Common issues and diagnostics for AI Studio Colab.

## Bootstrap Scripts

Run these in order to diagnose setup issues:

```bash
python core/scripts/bootstrap_repo.py
python core/scripts/validate_environment.py
python core/scripts/validate_paths.py
python core/scripts/validate_manifests.py
python core/scripts/check_nodes.py
python core/scripts/verify_models.py
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

## Installation Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| ComfyUI fails to start | Missing dependencies | Re-run notebook install cells |
| Custom node import errors | Version mismatch | Check `configs/nodes/node_registry.json` |
| Model not found | Path misconfiguration | Verify `configs/paths/colab_paths.json` and Drive mount |
| Out of disk space | Large model downloads | Use Drive mount; prune runtime cache |
| `bootstrap_repo.py` fails | Repo not cloned fully | Re-clone; ensure all top-level dirs present |
| `validate_paths.py` warns on Colab paths | First run before install | Normal — install ComfyUI via notebook first |

## Control Panel / Notebook Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| Drive not mounted | Skipped mount cell | Run Drive mount cell in control panel |
| GPU not detected | CPU runtime selected | Runtime → Change runtime type → GPU |
| Wrong notebook | Duplicate launcher used | Use only `colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb` |
| Scripts not found | Wrong working directory | `cd` to repository root before running scripts |

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

Copy only the latest ComfyUI output to Drive:

```bash
# Preview without copying
python core/scripts/sync_outputs.py --dry-run

# Copy latest file
python core/scripts/sync_outputs.py
```

Source: `/content/ComfyUI/output` → Destination: `/content/drive/MyDrive/AI_Studio/outputs`

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
