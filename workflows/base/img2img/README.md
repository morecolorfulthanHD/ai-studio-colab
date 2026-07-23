# img2img

**Status:** Implemented — Package 4.8 Workflow Library (`base/img2img`)

## Purpose

Refine a source image with denoise control using SD 1.5.

## Library

- Manifest: `manifest.json`
- Prepare: `--workflow base/img2img --param input_image=... --param positive_prompt=...`
- Production status: **partial** (use with caution)

See [docs/workflow-library.md](../../../docs/workflow-library.md).

## Required Models

| Model | File |
|-------|------|
| SD 1.5 checkpoint | `sd15.safetensors` |

## Inputs

Source image from Drive/project inputs or ComfyUI input staging (path-validated).
