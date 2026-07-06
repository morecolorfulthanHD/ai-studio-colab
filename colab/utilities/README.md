# Colab Utilities

Helper modules and scripts specific to the Google Colab runtime.

## Planned Utilities (Phase 1+)

| Utility | Purpose |
|---------|---------|
| `gpu_check.py` | Verify GPU availability and VRAM |
| `drive_paths.py` | Resolve Drive mount paths from `configs/paths/` |
| `session_keepalive.py` | Prevent Colab session timeout during long runs |
| `output_sync.py` | Copy generated artifacts to Drive or `output/` |

These utilities are imported by notebooks in `colab/notebooks/` and launch scripts in `colab/launch/`.
