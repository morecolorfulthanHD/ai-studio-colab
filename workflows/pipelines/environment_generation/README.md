# Environment Generation Pipeline

**Status:** Not yet implemented (Phase 4)

## Purpose

Generate coherent environment scenes with depth/normal structural guidance and optional style reference locking.

## Sub-Workflow Chain (planned)

```
reference/reference_lock/  → optional style/environment reference
extraction/depth_map/      → optional depth from layout reference
controlnet/depth/            → depth-guided composition
base/txt2img/                → scene generation
base/hires_fix/              → upscale
```

## Inputs

- Environment description prompts
- Optional layout reference image
- Optional style reference image
- Preset keys

## Outputs

- Environment scene PNG → `output/`
