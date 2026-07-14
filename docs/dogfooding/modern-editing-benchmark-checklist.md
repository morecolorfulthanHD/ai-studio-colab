# Dogfooding Checklist — Modern Editing Benchmark (Package 4.4)

Compare SD1.5 baseline vs Qwen-Image-Edit-2511 vs FLUX.1 Fill [dev] on the bike/brick-wall tasks.

Do **not** change the production inpainting default during this dogfood.

## Setup

1. Manually download required weights (no auto-download; agree to FLUX license if using Fill).
2. Place under Drive:
   - `/content/drive/MyDrive/AI_Studio/models/shared/qwen_image_edit/`
   - `/content/drive/MyDrive/AI_Studio/models/shared/flux_fill/`
3. Read `docs/model-compatibility-modern-editing.md` and `docs/decisions/modern-editing-selection-gate.md`.

## Runs

Use identical source/mask where applicable and record outputs.

```bash
# SD1.5 baseline (existing production path)
python /content/ai-studio-colab/core/scripts/prepare_workflow.py \
  --workflow inpainting \
  --input <bike_source> \
  --mask <bike_mask> \
  --inspect

# Qwen candidate
python /content/ai-studio-colab/core/scripts/prepare_qwen_image_edit.py \
  --input <bike_source> \
  --positive-prompt "remove the bicycle and reconstruct the brick wall and pavement" \
  --summary

# FLUX Fill candidate
python /content/ai-studio-colab/core/scripts/prepare_flux_fill.py \
  --input <bike_rgba_or_rgb> \
  --mask <bike_mask> \
  --positive-prompt "replace the bicycle with a wooden bench" \
  --summary
```

Tasks: object removal, object replacement, local material/color edit, optional sign removal, outpainting.

Synthetic square fixture may be used only as a plumbing regression — not as a quality benchmark.

## Human scoring

Use the qualitative rubric (no invented automated scores):

- instruction adherence
- masked-region quality
- preservation outside mask
- seam/blend quality
- geometry consistency
- photographic realism
- unacceptable artifacts

```bash
python /content/ai-studio-colab/core/scripts/report_editing_benchmark.py --summary
```

## Selection

Promote a candidate only when all selection-gate criteria pass and the user approves. Keep FLUX Fill non-commercial license constraints explicit.
