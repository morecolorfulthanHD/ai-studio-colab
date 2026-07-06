# Presets

Named parameter sets referenced by workflows for reproducible generation settings.

## Planned Format (Phase 1)

```yaml
# Example structure (not yet implemented)
sd15_portrait:
  model: sd15_base          # key from configs/models/
  sampler: euler_ancestral
  steps: 28
  cfg: 7.0
  width: 512
  height: 768
  scheduler: normal
```

## Preset Categories (planned)

| Category | Examples |
|----------|----------|
| Base generation | `sd15_standard`, `sd15_portrait`, `sd15_landscape` |
| Hires fix | `sd15_hires_1.5x`, `sd15_hires_2x` |
| ControlNet | `cn_depth_balanced`, `cn_openpose_strong` |
| Reference | `ipadapter_face_high`, `ipadapter_style_medium` |
| Animation | `animatediff_short`, `svd_default` |

Workflows reference preset keys in their README and workflow metadata, not raw numeric values.
