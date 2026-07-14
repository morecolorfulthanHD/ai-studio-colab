# FLUX.1 Fill [dev] Reference Workflow

**Status:** Benchmark reference only (Package 4.4) — **not** a production default

## Provenance

Extracted from the official ComfyUI workflow PNG metadata:

- Docs: https://docs.comfy.org/tutorials/flux/flux-1-fill-dev
- Source image: `Comfy-Org/example_workflows` → `flux/inpaint/flux_fill_inpaint.png`
- Retrieval date: 2026-07-14
- Details: [`provenance.json`](./provenance.json)

## Mask architecture

One `LoadImage` node supplies IMAGE and MASK (embedded alpha), feeding `InpaintModelConditioning`.

## Required models (gated — no auto-download)

Agree to the FLUX.1 [dev] Non-Commercial License on Hugging Face before downloading.

| File | Typical ComfyUI location |
|------|--------------------------|
| `flux1-fill-dev.safetensors` | `models/diffusion_models/` |
| `clip_l.safetensors` | `models/text_encoders/` |
| `t5xxl_fp16.safetensors` (or fp8) | `models/text_encoders/` |
| `ae.safetensors` | `models/vae/` |

**License:** FLUX.1-dev Non-Commercial License. Model weights are **not** a commercial production default. Generated outputs may have broader use rights under the license text — read the official license before relying on that.

## Prepare (diagnostic)

```bash
python core/scripts/prepare_flux_fill.py \
  --input /path/to/rgba_or_rgb.png \
  --mask /path/to/mask.png \
  --positive-prompt "a wooden bench" \
  --summary
```
