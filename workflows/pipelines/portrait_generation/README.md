# Portrait Generation Pipeline

**Status:** Not yet implemented (Phase 3)

## Purpose

Generate consistent character portraits with identity locking, optional pose control, and hires fix refinement.

## Sub-Workflow Chain (planned)

```
reference/ipadapter/     → identity lock from face reference
extraction/pose_map/     → optional pose extraction
controlnet/openpose/     → optional pose guidance
base/txt2img/            → initial generation
base/hires_fix/          → upscale and refine
```

## Inputs

- Face reference image
- Prompts
- Optional pose reference image
- Preset keys

## Outputs

- High-resolution portrait PNG → `output/`

## Validation

Tested against `use_cases/zara_morrison/` reference set in Phase 7.
