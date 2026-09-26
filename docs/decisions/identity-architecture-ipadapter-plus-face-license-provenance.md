# Decision — IP-Adapter Plus Face Final License + Provenance Gate (Package 4.12.3)

**Status:** Accepted for license/provenance (prototype; not promoted)  
**Date:** 2026-09-26  
**Previous SHA:** `5fb602db7e8bf30e0aa934179e94548e383319a4` (IP-ADAPTER PLUS FACE PROTOTYPE FOUNDATION)

## Product constraints (unchanged)

- Zero paid model/checkpoint licensing; SaaS/cloud OK
- No InsightFace / FaceID / antelope / buffalo; no research-only/NC as hard license
- Fail closed on unresolved licensing
- InstantID remains `BLOCKED_FOR_COMMERCIAL`
- `promotion_allowed=false` for Plus Face even when component licenses are `ACCEPTABLE`
- No Package 4.13; no automatic promote; no asset download / GPU in this checkpoint

## License resolutions (REVIEW_REQUIRED → ACCEPTABLE)

| Component | Code | Weights | SaaS | Paid? | Notes |
|-----------|------|---------|------|-------|-------|
| ComfyUI_IPAdapter_plus `@a0f451a5…` | GPL-3.0 | n/a | yes | no | LICENSE at pinned commit |
| ipadapter_plus_face_sdxl_vit_h | Apache-2.0 | Apache-2.0 | yes | no | Plus Face ≠ FaceID |
| clip_vision_vit_h_openclip | MIT (OpenCLIP) | MIT (LAION tag) | yes | no | via h94 image_encoder |
| sdxl_base | n/a | Open RAIL++-M | yes | no | free commercial + Attachment A |

## Provenance pins

| Asset | Immutable revision | SHA256 | Size |
|-------|-------------------|--------|------|
| Plus Face SDXL ViT-H | `018e4027…` (h94/IP-Adapter) | `677ad886…` | 847517512 |
| OpenCLIP ViT-H (h94 path) | `018e4027…` | `6ca9667d…` | 2528373448 |
| SDXL Base 1.0 | `46216598…` | `31e35c80…` | 6938078334 |

All SHA256 values are published Hugging Face LFS pointer oids (not invented).

## Hard stops preserved

- InstantID license gate unchanged (`BLOCKED_FOR_COMMERCIAL`)
- Forbidden scan must stay clean on PATH C graph
- Controlled asset acquisition is next; this checkpoint does not download or run GPU
