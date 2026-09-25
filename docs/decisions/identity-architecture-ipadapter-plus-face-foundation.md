# Decision — IP-Adapter Plus Face Prototype Foundation (Package 4.12.3)

**Status:** Accepted — prototype foundation  
**Date:** 2026-09-25

## Product decisions

- Zero paid model/checkpoint licensing; **PATH C** primary
- InstantID production **blocked** (`BLOCKED_FOR_COMMERCIAL`); Characters option **11 blocked**; Package **4.13 closed**
- Prototype order: (1) **IP-Adapter Plus Face SDXL CLIP NON-FaceID first**; (2) PhotoMaker V1 later (**not implemented**)
- Still Package **4.12.3**
- Prior shortlist flipped: IP-Adapter Plus Face is now the first implementation spike (PhotoMaker V1 remains later)

## Architecture IDs

| architecture_id | Role |
|-----------------|------|
| `instantid_sdxl` | Existing path; commercially blocked; gates unchanged |
| `ipadapter_plus_face_sdxl` | New PATH C prototype |

## Hard stops preserved

- Do not weaken InstantID fail-closed gates (`promotion_allowed=false`)
- No FaceID / InsightFace / antelopev2 / buffalo_l / InstantID checkpoints / PhotoMaker V2 / PuLID / FLUX.dev on the Plus Face path
- No Colab Full Launch / asset download / S1–S4 GPU / option 11 / promote / 4.13 in this checkpoint
- No invented SHA256 — published upstream SHA only, else `PENDING_FIRST_DOWNLOAD_PIN`

## Face crop

**Bucket A** only (deterministic / OpenCV Haar / `PrepImageForClipVision`).
