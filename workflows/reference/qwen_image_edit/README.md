# Qwen-Image-Edit-2511 Reference Workflow

**Status:** Benchmark reference only (Package 4.4) — **not** a production default

## Provenance

Copied from the official Comfy-Org workflow template (not reconstructed):

- Docs: https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit-2511
- Template: `Comfy-Org/workflow_templates` → `image_qwen_image_edit_2511.json`
- Retrieval date: 2026-07-14
- Details: [`provenance.json`](./provenance.json)

## Mask / edit architecture

Instruction-driven multi-image edit via official subgraph. Primary and optional reference images load through top-level `LoadImage` nodes. The edit instruction lives in `TextEncodeQwenImageEditPlus` inside the subgraph.

## Required models (manual download — no auto-download)

Store under Drive shared paths (see model compatibility doc):

| File | Typical ComfyUI location |
|------|--------------------------|
| `qwen_image_edit_2511_fp8mixed.safetensors` | `models/diffusion_models/` |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors` | `models/text_encoders/` |
| `qwen_image_vae.safetensors` | `models/vae/` |
| `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` (optional) | `models/loras/` |

**License:** Apache-2.0 (per official Qwen-Image-Edit-2511 model card). Commercial use allowed under Apache-2.0 terms.

## Prepare (diagnostic)

```bash
python core/scripts/prepare_qwen_image_edit.py \
  --input /path/to/source.png \
  --positive-prompt "remove the bicycle and reconstruct the brick wall" \
  --summary
```
