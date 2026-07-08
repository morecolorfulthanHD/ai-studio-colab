# Colab Notebooks

Canonical Google Colab notebooks for launching and controlling AI Studio Colab.

## Source of Truth

The canonical notebook lives **in this GitHub repository** — not on Google Drive.

| Location | Role |
|----------|------|
| **GitHub** | Canonical notebook, scripts, configs, workflows |
| **Google Drive** | Persistent models, outputs, datasets, references, checkpoints |
| **Colab runtime** | Disposable clone at `/content/ai-studio-colab` (via Repository Sync) |

## Canonical Control Panel

| Notebook | Purpose | Status |
|----------|---------|--------|
| [`AI_Studio_Control_Panel_Colab.ipynb`](AI_Studio_Control_Panel_Colab.ipynb) | Main control panel — install, launch, workflow selection | Active |

**Open in Colab from GitHub:**

**https://colab.research.google.com/github/morecolorfulthanHD/ai-studio-colab/blob/main/colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb**

This is the only control panel notebook. Do not duplicate it.

### Old Drive Copy

If you have a notebook saved on Drive, it is a convenience copy only. **Repository Sync** pulls the latest repo code from GitHub, but the cells you run come from whichever file you opened. Switch to the GitHub Colab link above to use the current canonical notebook.

## Documentation

See [docs/colab-control-panel.md](../../docs/colab-control-panel.md) for:

- GitHub-canonical architecture
- Repository Sync (clone/pull from GitHub)
- Bootstrap scripts callable from notebook cells
- Planned orchestration capabilities

## Cell Order

1. **Cell 1** — Environment checks
2. **Cell 2** — Mount Google Drive (persistent storage)
3. **Cell 3** — Define paths and settings
4. **Repository Sync** — Clone/pull repo from GitHub into `/content/ai-studio-colab`
5. **Cell 3b** — Repository bootstrap and validation
6. **Cell 3c** — Runtime platform health

## Bootstrap Validation (Cell 3b)

Run **Cell 3b** after Repository Sync:

```python
# Cell 3b runs automatically:
# bootstrap_repo.py, validate_environment.py, validate_paths.py,
# validate_manifests.py, list_workflows.py
```

## Runtime Platform Health (Cell 3c)

After Cell 3b, run **Cell 3c** for unified platform health:

```python
# Cell 3c runs runtime_report.py automatically
```

Or manually from the cloned repo:

```bash
python core/scripts/runtime_report.py
python core/scripts/runtime_report.py --summary
```

## Post-Install Validation

After ComfyUI install:

```python
!python {REPO_ROOT}/core/scripts/check_nodes.py
!python {REPO_ROOT}/core/scripts/verify_models.py
```
