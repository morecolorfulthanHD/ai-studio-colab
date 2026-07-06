# Environment Reconstruction Pipeline

**Status:** Not yet implemented (Phase 4)

## Purpose

Reconstruct a consistent environment from multiple reference viewpoints, producing a unified scene representation.

## Sub-Workflow Chain (planned)

```
multi_reference/             → combine viewpoint references
extraction/depth_map/        → per-view depth maps
extraction/normal_map/       → per-view normal maps
controlnet/depth/ + normal/  → structural fusion
base/txt2img/                → reconstructed scene
```

## Inputs

- 3+ reference images from different angles of the same environment
- Scene description prompts
- Preset keys

## Outputs

- Reconstructed environment PNG → `output/`
- Reusable environment reference set → caller-specified path

## Known Limitations

- Quality depends on reference overlap and viewpoint similarity.
