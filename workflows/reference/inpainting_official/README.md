# Official ComfyUI Inpainting Reference Workflow

**Status:** Reference only (Package 4.3 correction) — **not** a production capability

## Purpose

Provide a provenance-backed official ComfyUI inpainting graph for **honest** comparison against AI Studio’s canonical workflow.

Canonical AI Studio uses a separate `LoadImageMask` (red channel). The official ComfyUI tutorial uses one `LoadImage` whose **MASK** output comes from an embedded alpha transparency channel.

## Provenance

| Field | Value |
|-------|-------|
| Status | **Extracted from official workflow PNG metadata** (not hand-authored) |
| Source page | https://github.com/comfyanonymous/ComfyUI_examples/tree/master/inpaint |
| Docs tutorial | https://docs.comfy.org/tutorials/basic/inpaint |
| Source image URL | https://raw.githubusercontent.com/comfyanonymous/ComfyUI_examples/master/inpaint/inpain_model_cat.png |
| Source image SHA-256 | `2194fe1be03106091dbe6cc9b8b1cb6018b2938b6576c3a68bfa01b488106d70` |
| Extraction method | PNG `tEXt` chunk key `workflow` |
| Retrieval date | 2026-07-13 |
| Committed workflow SHA-256 | see `provenance.json` |

Machine-readable details: [`provenance.json`](./provenance.json).

The source PNG is **not** committed (large asset). Only the extracted workflow JSON and provenance metadata are in this repo.

## Official mask architecture

1. Input is an RGBA PNG with an embedded alpha transparency mask (region erased to alpha).
2. One `LoadImage` node provides:
   - `IMAGE` → `VAEEncodeForInpaint.pixels`
   - `MASK` → `VAEEncodeForInpaint.mask`
3. There is **no** separate `LoadImageMask` node.

### ComfyUI `LoadImage` MASK convention

ComfyUI derives MASK from alpha as approximately `1 - alpha/255`:

- **Transparent** pixels (`alpha = 0`) → mask value high → **inpainted / regenerated**
- **Opaque** pixels (`alpha = 255`) → mask value low → **preserved**

## Graph contents (extracted)

- `LoadImage` (IMAGE + MASK)
- `CheckpointLoaderSimple` → `512-inpainting-ema.safetensors`
- Dual `CLIPTextEncode`
- `VAEEncodeForInpaint`
- `KSampler` (denoise `1.0`; historical sampler `uni_pc_bh2`, steps `20`, CFG `8`)
- `VAEDecode`
- `SaveImage`

**Note:** The historical workflow image does not serialize `grow_mask_by`. Modern ComfyUI’s default for this node is `6`. Architecture comparison focuses on mask source topology, not that serialization gap.

## Compare

```bash
python core/scripts/compare_inpainting_workflows.py --summary
```

Expected: **materially_different** — separate red-channel `LoadImageMask` vs embedded alpha from `LoadImage`.

## Prepare reference runtime copy (diagnostic only)

```bash
python core/scripts/prepare_inpainting_reference.py \
  --input /path/to/rgba_with_alpha.png \
  --match-canonical-sampler
```
