# Path Configuration

Centralized path mappings for all environments.

## Planned Format (Phase 1)

```yaml
# Example structure (not yet implemented)
environments:
  colab:
    repo_root: /content/ai-studio-colab
    drive_root: /content/drive/MyDrive/ai-studio-colab
    comfyui: /content/ai-studio-colab/core/comfyui/ComfyUI
  local:
    repo_root: <user-defined>
    comfyui: <user-defined>/core/comfyui/ComfyUI

assets:
  checkpoints: ${repo_root}/assets/checkpoints
  controlnets: ${repo_root}/assets/controlnets
  # ...
```

All scripts, notebooks, and workflows resolve paths through this config. No hardcoded `/content/` paths elsewhere in the repository.
