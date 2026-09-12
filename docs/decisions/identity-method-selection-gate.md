# Decision Record — Identity Method Selection Gate (Package 4.12)

**Status:** Open — no Package 4.13 production identity default yet  
**Date opened:** 2026-08-26  
**Updated:** 2026-09-11 (Package 4.12.3 architecture investigation)  
**Baseline tooling commit:** handoff metadata on `main`; Package 4.12 product CODE/SIM pending review

## Context

Package 4.12 compares two live identity-method candidates for a persistent virtual person under pose/scene change. It does **not** select the Package 4.13 production method automatically.

## Architecture status (Package 4.12.3)

| Architecture | Status |
|--------------|--------|
| `reactor_faceswap_benchmark` | **REJECTED_FOR_PRODUCTION_IDENTITY** |
| `ipadapter_faceid_sd15_benchmark` | **REJECTED_FOR_PRODUCTION_IDENTITY** |
| `faceid_conditioning_sweep` (4.12.2) | **FAILED_FIRST_SWEEP** |
| `instantid_sdxl_benchmark` | **INVESTIGATION** (Package 4.12.3 live candidate) |

Reason for rejections: identity retention alone is insufficient when required pose/expression/scene transformations fail.

## Package 4.12 live candidates (historical — frozen)

1. `reactor_faceswap_benchmark` — post-process face replacement (ReActor / InsightFace)  
2. `ipadapter_faceid_sd15_benchmark` — generative identity conditioning (IPAdapter FaceID Plus v2 SD1.5)

Do not retune or rerun these graphs. Evidence preserved on Drive.

## Package 4.12.3 investigation candidate

- `instantid_sdxl_benchmark` — SDXL + InstantID identity conditioning  
- Secondary: PuLID SDXL investigated, **not selected** as second live candidate (see `identity-architecture-secondary-candidate.md`)

## Promotion criteria for later Package 4.13 design (all required)

1. Candidate × S1–S4 Runs recorded with output SHA  
2. Human rubric completed (eight keys)  
3. No systemic `fail` on identity + scene for S2–S4  
4. License review permits intended use  
5. Colab L4 operational complexity acceptable  
6. **User explicitly records** the selection (or “neither / revisit InstantID-SDXL later”)

Prepare/open/simulation success is **not** sufficient.

## Current decision

Deferred. No automatic promotion. No production identity default claimed by Package 4.12 or 4.12.3.

**Visual selection status:** PENDING / NOT ACCEPTED

- FaceID baseline S2/S3/S4 scenario adherence failed (REJECTED)  
- Package 4.12.2 conditioning sweep failed all variants (FAILED_FIRST_SWEEP)  
- InstantID SDXL: **INVESTIGATION** — prepare/open/CODE/SIM is not a quality claim; live GPU + automated visual QA required
