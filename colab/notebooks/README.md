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

```python
!python core/scripts/bootstrap_repo.py
!python core/scripts/validate_environment.py
!python core/scripts/validate_paths.py
!python core/scripts/validate_manifests.py
```
