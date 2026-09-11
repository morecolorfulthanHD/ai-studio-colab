# Decision Record — Identity Method Selection Gate (Package 4.12)

**Status:** Open — no Package 4.13 production identity default yet  
**Date opened:** 2026-08-26  
**Baseline tooling commit:** handoff metadata on `main`; Package 4.12 product CODE/SIM pending review

## Context

Package 4.12 compares two live identity-method candidates for a persistent virtual person under pose/scene change. It does **not** select the Package 4.13 production method automatically.

## Live candidates

1. `reactor_faceswap_benchmark` — post-process face replacement (ReActor / InsightFace)  
2. `ipadapter_faceid_sd15_benchmark` — generative identity conditioning (IPAdapter FaceID Plus v2 SD1.5)

## Deferred

- InstantID / SDXL identity lane — not a bounded SD1.5 live candidate in 4.12

## Promotion criteria for later Package 4.13 design (all required)

1. Candidate × S1–S4 Runs recorded with output SHA  
2. Human rubric completed (eight keys)  
3. No systemic `fail` on identity + scene for S2–S4  
4. License review permits intended use  
5. Colab L4 operational complexity acceptable  
6. **User explicitly records** the selection (or “neither / revisit InstantID-SDXL later”)

Prepare/open/simulation success is **not** sufficient.

## Current decision

Deferred. No automatic promotion. No production identity default claimed by Package 4.12.

**Visual selection status:** PENDING / NOT ACCEPTED — FaceID baseline S2/S3/S4 scenario adherence failed; Package 4.12.2 conditioning sweep is method-fitness investigation only (not promotion).
