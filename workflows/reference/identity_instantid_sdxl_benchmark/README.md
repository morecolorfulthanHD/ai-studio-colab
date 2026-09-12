# InstantID SDXL — Production Identity Architecture Benchmark (Package 4.12.3)

Benchmark-only. Not a Package 4.13 production default.

## Candidate

`instantid_sdxl_benchmark`

## Node pin

- Repo: https://github.com/cubiq/ComfyUI_InstantID
- Commit: `72495e806bc2ab9c41581e15ccaa1bcf83c477e8` (maintenance-mode tag, 2025-04-14)
- Compatibility: SDXL-only native InstantID. Requires current ComfyUI; fail closed if live import fails.

## Required assets (manual placement; no auto-download)

| Asset | Drive destination (canonical) |
|-------|-------------------------------|
| SDXL base | `models/shared/checkpoints/sd_xl_base_1.0.safetensors` |
| InstantID IP-Adapter | `models/shared/instantid/ip-adapter.bin` |
| InstantID ControlNet | `models/shared/controlnet/instantid/diffusion_pytorch_model.safetensors` |
| InsightFace antelopev2 pack | `models/shared/insightface/models/antelopev2/` |

## Graph

Based on cubiq `InstantID_basic` example, adapted to:

- `ApplyInstantIDAdvanced` (separate ip_weight / cn_strength)
- `SaveImage` output
- Bound parameters: face image, prompt, seed, width/height, save prefix
- S4 default latent: **1024×768** landscape (not 512×768 portrait)

Pose conditioning: optional `image_kps` on ApplyInstantIDAdvanced when a pose reference is available. Default graph uses identity-image keypoints; lower `cn_strength` may be required for text-driven pose — fail-fast after credible attempts.

## Status

INVESTIGATION. Rejected architectures (ReActor, SD1.5 FaceID) remain preserved and must not be retuned.
