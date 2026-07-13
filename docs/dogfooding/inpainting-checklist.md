# Dogfooding Checklist — Base Inpainting

Validate Production Package 4 inpainting in Google Colab.

## Quick Path

1. Launch ComfyUI (`control_panel()` → 1 → `minimal`)
2. Place source image in `AI_Studio/inputs/images/` and mask in `AI_Studio/inputs/masks/`
3. `control_panel()` → **7. Image Editing** → **2. Inpainting**
4. Confirm dedicated inpainting checkpoint is present
5. Prepare workflow with `--input` and `--mask`
5. Generate, sync, verify evidence

---

## 1. Fresh Colab Startup

| Step | Pass Criteria |
|------|---------------|
| GPU runtime | GPU available |
| Repo sync | Scripts discoverable |

---

## 2. Input Placement

| Asset | Location |
|-------|----------|
| Source image | `AI_Studio/inputs/images/` |
| Mask (white=inpaint) | `AI_Studio/inputs/masks/` |

```bash
python core/scripts/list_inputs.py
```

**Capture:** listed image and mask paths.

---

## 3. Workflow Preparation

```bash
python core/scripts/verify_models.py --require-inpainting
python core/scripts/prepare_workflow.py --workflow inpainting --input /path/to/source.png --mask /path/to/mask.png
```

| Check | Pass | Fail |
|-------|------|------|
| Dedicated checkpoint present | `verify_models.py --require-inpainting` exits 0 | Missing-checkpoint error |
| Both paths valid | Source and mask staged in ComfyUI/input + prepared JSON | Error |
| Missing `--mask` | Preparation error | — |
| Invalid mask extension | Preparation error | — |

**Capture:** prepared workflow path.

---

## 4. Capability Readiness

```bash
python core/scripts/validate_capabilities.py --capability inpainting
```

| Field | Expected |
|-------|----------|
| `computed_status` | `ready` (when ComfyUI + dedicated inpainting checkpoint + workflow valid) |
| `execution_input_status` | `not_selected`, `mask_not_selected`, or `available` |

Missing inputs must **not** downgrade installed capability to `PARTIAL`.

---

## 5. ComfyUI Graph

Expected nodes (9):

- LoadImage, LoadImageMask, CheckpointLoaderSimple
- CLIPTextEncode (×2), VAEEncodeForInpaint, KSampler (**denoise 1.0**), VAEDecode, SaveImage

Output prefix: `ai_studio_base_inpainting`

**Capture:** graph screenshot showing mask path.

---

## 6. Generation and Evidence

```bash
python core/scripts/sync_outputs.py
python core/scripts/verify_generation.py --workflow inpainting --summary
```

**Capture:** output filename and verification state.

---

## Pass / Fail

**PASS:** inpainting `READY`, valid preparation with mask, output generated, evidence verified after sync.

**FAIL:** mask node missing from workflow, canonical JSON modified, capability blocked by missing optional nodes.

---

## Troubleshooting

| Issue | Action |
|-------|--------|
| Inpainting menu stops before preparation | Place `512-inpainting-ema.safetensors` at `/content/drive/MyDrive/AI_Studio/models/shared/checkpoints/` |
| Seam at mask edge | Confirm denoise is 1.0 for true-inpainting path; refine mask feathering |
| Wrong region inpainted | Confirm mask: white = regenerate |
| `mask_not_selected` only | Add mask to Drive `inputs/masks/`; does not block `READY` |
