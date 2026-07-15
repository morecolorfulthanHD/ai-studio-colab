# Decision Record — Modern Editing Model Selection Gate (Package 4.4)

**Status:** Open — no production default change yet  
**Date opened:** 2026-07-14

## Context

Package 4.3 showed SD1.5 inpainting plumbing is correct, but real-world bike/brick object removal and replacement instruction following is unacceptable.

## Candidates

1. **Qwen-Image-Edit-2511** (Apache-2.0) — instruction-driven edits  
2. **FLUX.1 Fill [dev]** (FLUX.1-dev non-commercial weights) — mask-driven fill

## Promotion criteria (all required)

A candidate may become the production editing default only after:

1. All required files are verified present
2. Workflow runs on Colab L4
3. Object removal is materially better than SD1.5 on the bike benchmark
4. Object replacement is materially better than SD1.5
5. Preservation outside the edit region is acceptable
6. Licensing permits the intended production use
7. User explicitly approves benchmark outputs

Executing a workflow alone is **not** sufficient.

## Current decision

- SD1.5 inpainting remains **technically available** (`runtime_status: ready`) but is **quality-unqualified** (`quality_status: benchmark_failed`, `production_status: experimental`) per `docs/decisions/sd15-inpainting-quality-gate.md`
- Do **not** present SD1.5 inpainting as the recommended production editing model
- Treat Qwen / FLUX Fill as **benchmark-only** capabilities
- Do **not** promote FLUX Fill as a commercial production default under the current non-commercial weight license

## Record

| Field | Value |
|-------|-------|
| Decision | Deferred |
| Selected default | `inpainting` capability retained for diagnostics; **not** quality-approved for production editing |
| Next action | Complete live dogfood under `docs/dogfooding/modern-editing-benchmark-checklist.md` |
