# Decision — Secondary Identity Architecture Candidate (Package 4.12.3)

**Status:** Closed for 4.12.3  
**Date:** 2026-09-11

## Question

Should Package 4.12.3 benchmark a second live SDXL identity architecture alongside InstantID?

## Candidates considered

| Candidate | Outcome |
|-----------|---------|
| **PuLID SDXL** | Investigated; **not added** as second live candidate |
| Other SDXL identity nodes | No mature, pinnable, license-clear alternative met all selection criteria |

## Selection criteria (all required for second live candidate)

1. Current ComfyUI compatibility with deterministic pin
2. Acceptable license path for eventual production/commercial use
3. Identity preservation under pose/expression change (evidence or credible upstream claims)
4. Operational complexity acceptable on Colab L4 Full Launch stack
5. Stable enough to avoid fragile dual-candidate maintenance burden

## PuLID SDXL — why not selected

- Additional custom node + weight surface area with overlapping InstantID role
- License and weight provenance require separate review pass
- Maintenance/pin burden without proven advantage over InstantID for AI Studio's S1–S4 gate
- Risk of burning GPU on two immature stacks in parallel

## Decision

**Benchmark InstantID SDXL alone** for Package 4.12.3 (`instantid_sdxl_benchmark`).

Document PuLID as `investigated_not_selected`. Revisit only if InstantID fails after credible configuration attempts or license blockers emerge.

## Primary candidate pin

- Node: `ComfyUI_InstantID` @ `72495e806bc2ab9c41581e15ccaa1bcf83c477e8`
- Workflow: `reference/identity_instantid_sdxl_benchmark`
