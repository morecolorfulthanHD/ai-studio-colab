# Model Registry

Version-controlled registry of all model weights used by platform workflows.

## Planned Format (Phase 1)

Each model entry will document:

```yaml
# Example structure (not yet implemented)
name: sd15_base
family: sd15
filename: v1-5-pruned-emaonly.safetensors
location: assets/checkpoints/
source: runwayml/stable-diffusion-v1-5
sha256: <hash>
workflows:
  - workflows/base/txt2img/
```

## Model Families

| Family | Phase | Directory |
|--------|-------|-----------|
| SD 1.5 | 1 | `assets/checkpoints/` |
| SDXL | Future | `assets/checkpoints/` |
| Flux | Future | `assets/checkpoints/` |
| ControlNet | 2 | `assets/controlnets/` |
| LoRA | 2+ | `assets/loras/` |
| VAE | 1 | `assets/vaes/` |
| IPAdapter | 3 | `assets/ipadapter/` |
| InsightFace | 5 | `assets/insightface/` |
| SVD | 6 | `assets/checkpoints/` |

Binary weights are not committed to Git. Only registry metadata lives here.
