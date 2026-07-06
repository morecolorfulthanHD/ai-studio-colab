# Colab Notebooks

Canonical Google Colab notebooks for launching and controlling AI Studio Colab.

## Canonical Control Panel

| Notebook | Purpose | Status |
|----------|---------|--------|
| [`AI_Studio_Control_Panel_Colab.ipynb`](AI_Studio_Control_Panel_Colab.ipynb) | Main control panel — install, launch, workflow selection | Active |

**This is the only control panel notebook.** Do not duplicate it. Future improvements should enhance this notebook rather than replace it.

## Documentation

See [docs/colab-control-panel.md](../../docs/colab-control-panel.md) for:

- How the notebook fits into the repository architecture
- Planned orchestration capabilities (Drive mount, GPU verify, path validate, repo sync, ComfyUI/A1111 launch, workflow menus, output sync)
- Bootstrap scripts callable from notebook cells

## Bootstrap Validation (from notebook)

Run **Cell 3b** after Drive mount and path setup (Cells 2–3):

```python
# Cell 3b runs automatically:
# bootstrap_repo.py, validate_environment.py, validate_paths.py,
# validate_manifests.py, list_workflows.py
```

After ComfyUI install, run manually:

```python
!python {REPO_ROOT}/core/scripts/check_nodes.py
!python {REPO_ROOT}/core/scripts/verify_models.py
```
