# Multi-Angle Generation Pipeline

**Status:** Not yet implemented (Phase 4)

## Purpose

Generate new camera angles of a subject or environment while maintaining object, lighting, and identity consistency.

## Sub-Workflow Chain (planned)

```
environment_reconstruction/  → unified scene reference (if environment)
reference/multi_reference/   → subject identity lock
extraction/pose_map/         → target angle pose (if character)
controlnet/openpose/         → pose-guided generation
base/txt2img/                → angle-specific generation
```

## Inputs

- Reference image set (subject and/or environment)
- Target camera angle parameters (yaw, pitch, distance)
- Prompts
- Preset keys

## Outputs

- New-angle PNG → `output/`

## Dependencies

- `pipelines/environment_reconstruction/` (for environment angles)
- `reference/multi_reference/` (for subject consistency)
