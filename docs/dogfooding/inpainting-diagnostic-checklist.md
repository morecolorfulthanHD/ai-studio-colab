# Dogfooding Checklist — Inpainting Diagnostics

Validate Production Package 4.3 mask diagnostics and **honest** canonical vs official-reference comparison in Google Colab.

## Quick Path

1. Generate synthetic RGB + grayscale mask + RGBA alpha fixtures
2. Inspect standalone mask and embedded alpha
3. Prepare canonical and official-reference workflows
4. Compare workflows (expect materially different mask architectures)
5. Side-by-side generate with matched sampler settings

---

## Two Mask Architectures

| Path | Source image | Mask input | Node |
|------|--------------|------------|------|
| **A — AI Studio canonical** | RGB PNG | Separate grayscale/red mask file | `LoadImage` + `LoadImageMask` (red) |
| **B — Official ComfyUI reference** | RGBA PNG with embedded alpha | Same file's alpha → `MASK` | Single `LoadImage` (IMAGE + MASK) |

ComfyUI `LoadImage` MASK convention: approximately `1 - alpha/255`. Transparent pixels (`alpha = 0`) are inpainted; opaque pixels (`alpha = 255`) are preserved.

Do **not** treat these architectures as equivalent merely because both feed a MASK socket.

---

## Diagnostic Dimensions (keep separate)

1. **Mask size** — small regions are harder to notice at thumbnail scale, but masked pixels should still respond to conditioning.
2. **Mask correctness** — channel, polarity, bounding box, masked percent.
3. **Prompt adherence** — whether the model follows text inside the mask.
4. **Workflow architecture** — separate `LoadImageMask` vs embedded alpha from `LoadImage`.

A small masked percent does **not** by itself explain failure.

---

## Test 1 — Synthetic Fixture, Red-Square Mask (canonical inputs)

| Item | Value |
|------|-------|
| Source | `diagnostic_source.png` (RGB) |
| Mask | `diagnostic_mask_red_square.png` (grayscale/red) |
| Prompt | `a bright yellow square` |

**Expected:**

- Mask statistics show a partially masked region over the red square
- Red square changes materially after generation
- Blue square and green circle remain stable

```bash
python core/scripts/create_inpainting_diagnostic_fixture.py --summary
python core/scripts/inspect_mask.py --mask <fixture>/diagnostic_mask_red_square.png --channel red --summary
```

---

## Test 2 — Inverted Mask (canonical inputs)

| Item | Value |
|------|-------|
| Mask | `diagnostic_mask_inverted.png` |

**Expected:**

- `inspect_mask.py` reports `inverted` relative to the original mask
- Generation regenerates everything except the red square region

```bash
python core/scripts/inspect_mask.py \
  --mask <fixture>/diagnostic_mask_inverted.png \
  --comparison <fixture>/diagnostic_mask_red_square.png \
  --channel red --summary
```

---

## Test 3 — Embedded Alpha Fixture (official path input)

```bash
python core/scripts/inspect_mask.py \
  --mask <fixture>/diagnostic_source_rgba.png \
  --channel alpha --summary
```

**Expected:**

- Alpha interpretation uses ComfyUI LoadImage MASK semantics (inverted alpha)
- Bounding box matches the red square
- Classification is `partially_masked`

---

## Test A / Test B — Side-by-Side Dogfood (Live Colab)

Generate fixtures first (runtime/temp dir is fine):

```bash
python /content/ai-studio-colab/core/scripts/create_inpainting_diagnostic_fixture.py --summary
```

Use identical:

- checkpoint (`512-inpainting-ema.safetensors`)
- prompt: `a bright yellow square`
- seed / sampler / scheduler / steps / CFG
- denoise `1.0`
- `grow_mask_by` `6` (temporary prepared reference sets this; extracted provenance JSON stays unchanged)

Both prepared JSON files must land under `/content/ai-studio-runtime/workflows`.
Both staged inputs must land under `/content/ComfyUI/input`.

### Test A — AI Studio canonical path

- RGB source + separate grayscale red-channel mask

```bash
python /content/ai-studio-colab/core/scripts/prepare_workflow.py \
  --workflow inpainting \
  --input <fixture>/diagnostic_source.png \
  --mask <fixture>/diagnostic_mask_red_square.png \
  --inspect
```

### Test B — Official reference path

- RGBA source with embedded alpha mask
- Official reference workflow (diagnostic only; not a production capability)

```bash
python /content/ai-studio-colab/core/scripts/prepare_inpainting_reference.py \
  --input <fixture>/diagnostic_source_rgba.png \
  --match-canonical-sampler \
  --positive-prompt "a bright yellow square" \
  --negative-prompt "blurry, low quality, distorted, seams, artifacts" \
  --summary
```

Confirm the printed resolved paths:

```
ComfyUI input:       /content/ComfyUI/input
Prepared workflows:  /content/ai-studio-runtime/workflows
```

Optional shortcut that also copies canonical prompts when prompt flags are omitted:

```bash
python /content/ai-studio-colab/core/scripts/prepare_inpainting_reference.py \
  --input <fixture>/diagnostic_source_rgba.png \
  --match-canonical-settings \
  --positive-prompt "a bright yellow square" \
  --negative-prompt "blurry, low quality, distorted, seams, artifacts" \
  --summary
```

### Diagnostic outcome

1. **Official works, canonical does not** → separate-mask handling is the likely defect
2. **Both fail** → model / sampler / runtime behavior
3. **Both work** → photographic test failure is prompt / mask-size / subject complexity

Keep these separate: mask size, mask correctness, prompt adherence, workflow architecture.
A small masked percent does not by itself explain failure; masked pixels should still respond to conditioning.

---

## Test 4 — Workflow Comparison

```bash
python core/scripts/compare_inpainting_workflows.py --summary
```

**Expected:**

```
Overall: materially_different
mask source architecture:
  canonical = separate red-channel mask
  reference = embedded alpha from LoadImage
```

Reference provenance must be present under `workflows/reference/inpainting_official/provenance.json`.

---

## Test 5 — Mask Preview Workflow

Load `workflows/diagnostics/inpainting_mask_preview/workflow.json` with the fixture source and separate mask.

---

## Pass / Fail

**PASS:**

- mask statistics and alpha bounding box are correct
- preview matches intended masked area
- comparison reports architectures as materially different
- side-by-side A/B supports one of the three diagnostic outcomes above

**FAIL:**

- reference still uses `LoadImageMask`
- comparison reports `equivalent` solely because both end at a MASK socket
- prepared canonical reverts mask channel to `alpha`
- provenance metadata missing

---

## Troubleshooting

| Issue | Action |
|-------|--------|
| Mask percent near 0% for visible white region | Run `inspect_mask.py --channel red` and verify channel selection |
| RGBA alpha looks “empty” | Inspect with `--channel alpha` (ComfyUI inverts alpha for MASK) |
| Reference and canonical look identical in compare | Rebuild/compare after Package 4.3 reference correction |
| A/B unfair due to sampler drift | Use `--match-canonical-sampler` on reference preparation |
