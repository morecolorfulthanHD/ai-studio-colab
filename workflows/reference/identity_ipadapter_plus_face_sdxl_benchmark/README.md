# Identity Architecture — IP-Adapter Plus Face SDXL (CLIP NON-FaceID)

**Package:** 4.12.3  
**architecture_id:** `ipadapter_plus_face_sdxl`  
**Status:** PROTOTYPE foundation (no live GPU / no asset download in this checkpoint)

## Purpose

PATH C primary prototype for production-oriented identity **without** InsightFace / FaceID / InstantID commercial blockers.

Order (accepted): (1) IP-Adapter Plus Face SDXL CLIP first; (2) PhotoMaker V1 later (not implemented here).

## Required assets (contract)

| Asset | Filename | Source |
|-------|----------|--------|
| Plus Face SDXL | `ip-adapter-plus-face_sdxl_vit-h.safetensors` | `h94/IP-Adapter` `sdxl_models/` (Apache-2.0); published LFS SHA256 pinned in model_registry |
| OpenCLIP ViT-H | `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | OpenCLIP / IP-Adapter image encoder |
| SDXL base | `sd_xl_base_1.0.safetensors` | Stability AI SDXL 1.0 |

Hashes: use published upstream SHA256 where available; otherwise `PENDING_FIRST_DOWNLOAD_PIN` (fail closed — controlled first-download→hash→pin). **No download in this checkpoint.**

## Face crop (Bucket A)

Deterministic center crop / OpenCV Haar / `PrepImageForClipVision` only.  
**Fail closed** on InsightFace, FaceID, antelopev2, buffalo_l.

## S1–S4

Same scenario IDs, prompts, dimensions, QA thresholds, and HUMAN_REVIEW semantics as InstantID architecture benchmark. Architecture-specific metadata/gates only.

## ControlNet

Pose/expression ControlNet is **GATED_DEFINITION_ONLY** — not downloaded; InstantID keypoints must not be reused.

## Not in this path

InstantID, FaceID, InsightFace, PhotoMaker V1/V2, PuLID, FLUX.dev, Package 4.13.
