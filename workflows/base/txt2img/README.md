# txt2img

**Status:** Implemented — Package 4.8 Workflow Library (`base/txt2img`)

## Purpose

Generate an image from a text prompt using an SD 1.5 checkpoint.

## Library

- Manifest: `manifest.json` (parameter schema, statuses, workflow hash)
- Prepare: `python core/scripts/prepare_workflow.py --workflow base/txt2img --param positive_prompt="..." --param seed_mode=fixed`
- `seed_mode=fixed` (default) keeps KSampler `control_after_generate=fixed` for reproducible repeats
- `seed_mode=randomize` uses ComfyUI's native `control_after_generate=randomize`
- Production status: **ready** / quality **accepted**

See [docs/workflow-library.md](../../../docs/workflow-library.md).

## Required Models

| Model | File |
|-------|------|
| SD 1.5 checkpoint | `sd15.safetensors` |

## Required Nodes

Stock ComfyUI: CheckpointLoaderSimple, CLIPTextEncode, EmptyLatentImage, KSampler, VAEDecode, SaveImage

## Outputs

SaveImage prefix `ai_studio_base_txt2img` (permanent Drive naming remains autosync-controlled).
