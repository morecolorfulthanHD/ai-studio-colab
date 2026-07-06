# Node Manifest

Custom ComfyUI node repositories required by platform workflows.

## Planned Format (Phase 1)

```yaml
# Example structure (not yet implemented)
- name: comfyui_controlnet_aux
  repo: https://github.com/Fannovel16/comfyui_controlnet_aux
  commit: <pinned_sha>
  phase: 2
  workflows:
    - workflows/extraction/*
    - workflows/controlnet/*
```

## Node Packs by Phase

| Pack | Phase |
|------|-------|
| ControlNet Aux | 2 |
| ComfyUI Impact Pack | 2 |
| WAS Node Suite | 2 |
| IPAdapter | 3 |
| ReActor | 5 |
| AnimateDiff | 6 |

Install order matters for some packs. The manifest will define a topological install sequence.
