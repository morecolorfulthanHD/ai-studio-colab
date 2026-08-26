# Dogfooding — Package 4.12 Identity Method Benchmark

CODE/SIM readiness proves character foundation + benchmark plumbing.  
**Operational acceptance requires live Runs** — prepare/open alone is not a quality claim.

## Before live testing — operator must provide

Manual placement only (no auto-download):

| Asset | Expected Drive path (Colab) |
|-------|-----------------------------|
| InsightFace buffalo | `/content/drive/MyDrive/AI_Studio/models/shared/insightface/models/buffalo_l/w600k_r50.onnx` |
| FaceID Plus v2 SD1.5 | `/content/drive/MyDrive/AI_Studio/models/shared/ipadapter/ip-adapter-faceid-plusv2_sd15.bin` |
| Matching FaceID LoRA | `/content/drive/MyDrive/AI_Studio/models/shared/loras/ip-adapter-faceid-plusv2_sd15_lora.safetensors` |
| CLIP vision | `/content/drive/MyDrive/AI_Studio/models/shared/clip/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` |
| SD1.5 checkpoint | existing accepted path |
| `ComfyUI-ReActor` | Full-mode custom node (already in Full install order) |
| `ComfyUI_IPAdapter_plus` | Install/pin from `https://github.com/cubiq/ComfyUI_IPAdapter_plus` (planned registry entry) |

Review FaceID / InsightFace license cards before any production promotion.

## Live Cases A–F (do not start until CODE/SIM review approved)

| Case | Steps (summary) |
|------|-----------------|
| A | Register character + primary face; `list`/`show`; SHA verify |
| B | Runtime reset/relaunch; character still resolves |
| C | Both candidates × S1–S4: prepare (`--allow-benchmark`) → open → **Run** → ledger + human rubric |
| D | Fail closed: bad character ID / SHA mismatch / missing FaceID or ReActor deps |
| E | Confirm identity-benchmark outputs are not ordinary variation/reproduction parents |
| F | Smoke: Package 4.11 Create Variation still works |

## Explicit non-claims

- Simulations do not quality-benchmark either method  
- Prepare/open does not quality-benchmark either method  
- Package 4.12 does not select the 4.13 winner
