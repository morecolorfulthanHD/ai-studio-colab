# Decision: SD1.5 Inpainting Production Quality Gate

**Status:** Rejected for production editing default  
**Date:** 2026-07-14  
**Package:** 4.5 Runtime Truthfulness

## Decision

Do **not** approve SD1.5 inpainting as the final production editing experience.

## Evidence

- Dedicated SD1.5 inpainting checkpoint (`512-inpainting-ema.safetensors`) loads successfully.
- Canonical separate-mask workflow executes technically.
- Official embedded-alpha reference workflow executes technically.
- Both respect mask boundaries in synthetic and diagnostic tests.
- Real-world object removal/replacement (bicycle on brick wall) failed instruction adherence.
- Canonical and official reference workflows behaved similarly — confirming workflow plumbing, not a single-workflow defect.

## Capability signals

| Signal | Value |
|--------|-------|
| `runtime_status` | `ready` |
| `quality_status` | `benchmark_failed` |
| `production_status` | `experimental` |

SD1.5 inpainting remains available for diagnostics, baseline comparison, and mask workflow validation. It must **not** be presented as the recommended production editing model.

## Next steps

Evaluate modern editing benchmark candidates (Qwen-Image-Edit-2511, FLUX.1 Fill [dev]) against the bike/brick-wall benchmark manifest. Promotion requires live benchmark outputs and explicit user approval per `docs/decisions/modern-editing-selection-gate.md`.
