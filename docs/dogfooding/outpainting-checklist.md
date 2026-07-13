# Dogfooding Checklist — Base Outpainting

Validate Production Package 4 outpainting in Google Colab.

## Quick Path

1. Launch ComfyUI (`minimal` mode)
2. Place source image in `AI_Studio/inputs/images/`
3. `control_panel()` → **7. Image Editing** → **3. Outpainting**
4. Prepare with expansion pixels (`--left`, `--right`, `--top`, `--bottom`)
5. Generate, sync, verify

---

## 1. Input and Launch

| Step | Pass Criteria |
|------|---------------|
| SD1.5 on Drive | `verify_models.py` OK |
| Source image listed | `list_inputs.py` shows path |

---

## 2. Workflow Preparation

```bash
python core/scripts/prepare_workflow.py --workflow outpainting --input /path/to/source.png --left 256 --right 256
python core/scripts/prepare_workflow.py --workflow outpainting --input /path/to/source.png --left -10
```

| Check | Pass | Fail |
|-------|------|------|
| Valid expansion (≥0, not all zero) | Staged source + prepared JSON | — |
| All-zero expansion | Validation error | Silent success |

**Capture:** expansion values in preparation output.

---

## 3. Capability Readiness

```bash
python core/scripts/validate_capabilities.py --capability outpainting
```

Expected: `computed_status=ready` when runtime deps satisfied; `execution_input_status` separate from readiness.

---

## 4. ComfyUI Graph

Expected nodes (9):

- LoadImage, **ImagePadForOutpaint**, VAEEncodeForInpaint, KSampler (**denoise 1.0**), VAEDecode, SaveImage, etc.

Default pad in canonical workflow: left=256, top=256 (overridden by preparation).

Output prefix: `ai_studio_base_outpainting`

**Capture:** graph showing ImagePadForOutpaint widget values.

---

## 5. Generation Quality Notes (SD1.5 limitations)

Document observed quality for review:

- Seam visibility at pad boundary
- Perspective consistency
- Prompt adherence in expanded regions

Prefer iterative 128–256 px expansions over single large pads.

---

## 6. Evidence Verification

```bash
python core/scripts/verify_generation.py --workflow outpainting --summary
```

**Capture:** verification summary and Drive sync screenshot.

---

## Pass / Fail

**PASS:** outpainting `READY`, valid expansion preparation, output with `ai_studio_base_outpainting` prefix, evidence check completes.

**FAIL:** ImagePadForOutpaint missing from workflow, negative expansion accepted, canonical workflow modified.

---

## Troubleshooting

| Issue | Action |
|-------|--------|
| Blurry expanded regions | Increase steps slightly; refine prompt for new area |
| Original image shifted | Check ImagePadForOutpaint left/top/right/bottom values |
| Large expansion artifacts | Reduce per-side pixels; run multiple passes |
