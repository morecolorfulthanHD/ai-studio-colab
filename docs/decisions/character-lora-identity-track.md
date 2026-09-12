# Decision Note — Character LoRA Identity Track (Future)

**Status:** Documented only — not implemented in Package 4.12.3  
**Date:** 2026-09-11  
**Context:** Fallback if zero-shot identity conditioning (InstantID SDXL) remains inadequate for pose/expression/scene control.

## Architecture concept

SDXL (or successor modern base) + character-specific LoRA + optional identity reinforcement + explicit pose control (ControlNet / OpenPose where needed).

## Reference dataset requirements

| Requirement | Guidance |
|-------------|----------|
| Minimum images | 15–25 curated references for a first viable LoRA; 30–50 for robust pose/expression |
| Diversity | Near-front, three-quarter left/right (~30–45°), profile samples, neutral + smile + other expressions |
| Quality | Consistent lighting where possible; avoid heavy filters; one identifiable person per image |
| Resolution | Native or upscaled to training pipeline input (typically 512–1024 short side for SDXL LoRA) |
| Exclusions | No mixed identities; no heavy occlusions in core set |

## Captions

- Per-image captions describing pose, expression, wardrobe, and environment
- Stable trigger token for the fictional character (e.g. `benchmark_persona`)
- Avoid conflicting identity tokens across the set

## Training estimates (Colab L4 class GPU)

| Phase | Rough estimate |
|-------|----------------|
| Dataset curation + captioning | 2–6 hours human |
| LoRA training (SDXL) | 1–3 hours GPU per experiment |
| Evaluation S1–S4 | Same benchmark scenarios as Package 4.12.3 |

## Expected benefits vs zero-shot InstantID

- Stronger wardrobe/environment adherence when LoRA encodes full-person appearance
- Potentially better expression/pose when training set includes diverse angles
- Higher upfront dataset and training cost; less flexible for ad-hoc new characters

## License implications

- Training images must be owned or licensed for derivative model training
- Base checkpoint license (SDXL Open RAIL++-M) governs generated outputs
- LoRA redistribution may be restricted depending on source likeness rights
- Commercial use requires explicit legal review of dataset + base model + tooling

## Package 4.12.3 stance

Character LoRA training pipeline is **not** implemented in 4.12.3. InstantID SDXL zero-shot investigation proceeds first. LoRA track activates only if architecture benchmark fails after credible InstantID configuration attempts.
