# Dogfooding — Package 4.12 Identity Method Benchmark

CODE/SIM readiness proves character foundation + **executable** benchmark graphs.  
**Operational acceptance requires live Runs** — prepare/open alone is not a quality claim.

## Before Case C — operator dependency path

1. **Full Launch** (reinstalls custom nodes after Full Reset via `install_nodes.py --execute`, including pinned commits).
2. **Characters → 4. Check identity-benchmark dependencies** (or `python core/scripts/check_identity_benchmark_deps.py`).
3. Place any **MISSING** restricted assets manually (no auto-download).

### Nodes (automated via Full Launch / install_nodes)

| Node | Pin |
|------|-----|
| `ComfyUI-ReActor` | `6ad6b35a4df250d14cb2abf0808c9ffedf59f747` |
| `ComfyUI_IPAdapter_plus` | `a0f451a5113cf9becb0847b92884cb10cbdec0ef` |

### Manual weights (fail closed)

| Asset | Exact filename | Drive destination |
|-------|----------------|-------------------|
| InsightFace buffalo detection | `det_10g.onnx` | `/content/drive/MyDrive/AI_Studio/models/shared/insightface/models/buffalo_l/det_10g.onnx` |
| InsightFace buffalo recognition | `w600k_r50.onnx` | `/content/drive/MyDrive/AI_Studio/models/shared/insightface/models/buffalo_l/w600k_r50.onnx` |
| ReActor swap model | `inswapper_128.onnx` | `/content/drive/MyDrive/AI_Studio/models/shared/insightface/inswapper_128.onnx` |
| FaceID Plus v2 SD1.5 | `ip-adapter-faceid-plusv2_sd15.bin` | `/content/drive/MyDrive/AI_Studio/models/shared/ipadapter/ip-adapter-faceid-plusv2_sd15.bin` |
| Matching FaceID LoRA | `ip-adapter-faceid-plusv2_sd15_lora.safetensors` | `/content/drive/MyDrive/AI_Studio/models/shared/loras/ip-adapter-faceid-plusv2_sd15_lora.safetensors` |
| CLIP ViT-H | `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | `/content/drive/MyDrive/AI_Studio/models/shared/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` |
| SD1.5 checkpoint | existing accepted path | (unchanged) |

### FaceID runtime prerequisites (dependency checker)

| Prerequisite | What “ready” means |
|--------------|-------------------|
| InsightFace Python package | `insightface==0.7.3` importable in ComfyUI interpreter |
| ONNX Runtime | `onnxruntime>=1.16.0` with `CPUExecutionProvider` |
| buffalo_l detection | `det_10g.onnx` present on Drive + bridged to runtime |
| buffalo_l recognition | `w600k_r50.onnx` present on Drive + bridged to runtime |
| FaceAnalysis initialization | bounded probe succeeds (`detection` + `recognition` in models; no auto-download) |
| FaceID IPAdapter weights | `.bin` + LoRA verified on Drive + runtime discovery |
| CLIP Vision | ViT-H verified on Drive + runtime discovery |

Verify afterward with Characters → **4. Check identity-benchmark dependencies** (`ready_for_case_c=True`).

**Character for Case C (already live):** `char_7471a702-55cf-4c7b-adb2-e17404d28c91` — do not re-register.

Review FaceID / InsightFace license cards before any production promotion.

## Live Cases A–F

| Case | Status / steps |
|------|----------------|
| A | **LIVE PASS** — character register/list/show + SHA |
| B | **LIVE PASS** — Full Reset + relaunch; character still resolves |
| C | **IN PROGRESS** — ReActor S1–S4 + FaceID S1–S3 executed; FaceID S4 not yet run; human rubric pending |
| D–F | **NOT STARTED** |

## Live Case C notes (human-observed; not automated scores)

Character: `char_7471a702-55cf-4c7b-adb2-e17404d28c91` (Benchmark Persona).  
Do **not** overwrite `human_review=pending` ledger fields automatically — enter rubric manually.

### ReActor (summary)

- Pipeline operational; visual identity consistency poor across S1–S4.
- Not acceptable for 4.13 virtual-character identity as currently observed.

### FaceID — S1 (`prep_efa7b6d8-58ec-4d26-8d19-697ec3ce9558`, seed `4791031672062905`)

- Historical successful executions (same prep/seed/SHA, different prompt IDs) preserved on Drive; do not delete.
- Visual: identity similarity good; facial naturalness good; near-front adherence acceptable.
- Strongest FaceID result so far; does **not** alone prove pose/expression robustness.

### FaceID — S2 (`prep_dcacc2ae-dc0a-45e7-90a5-5b6eb8026b1b`, seed `470280831310422`)

- Prompt requested ~40° right / three-quarter view.
- Output remained essentially face-forward / near-front (minimal head-angle change).
- Identity held; **pose-angle robustness NOT demonstrated**; pose instruction adherence failed.
- Operator note: *FaceID preserved recognizable identity and facial naturalness, but failed the intended ~40° three-quarter pose. The subject remained nearly frontal, so this run does not demonstrate robust identity preservation under meaningful head-angle change.*

### FaceID — S3 (`prep_5b0773a9-30fc-436a-aa30-d40dec98e517`, seed `5926742613902171`)

- Prompt requested genuine smile with visible teeth.
- Output remained essentially neutral (no meaningful smile / visible teeth).
- Identity held reasonably well; **expression robustness NOT demonstrated**; expression adherence failed.
- Operator note: *FaceID preserved identity reasonably well, but failed the requested expression change. The output remained essentially neutral rather than producing a genuine smile with visible teeth.*

### FaceID — S4

- **Not yet run.** Do not start until operator requests.

### Promotion stance (Package 4.12)

- FaceID is currently stronger than ReActor for near-front identity fidelity.
- FaceID has **not** demonstrated robust controlled pose/expression variation (S2/S3).
- **Do not auto-promote FaceID.** Promotion remains pending until S1–S4 complete, licensing/ops acceptable, and explicit human selection.
- **Neither** remains a valid final Package 4.12 outcome.

## Explicit non-claims

- Simulations do not quality-benchmark either method  
- Prepare/open does not quality-benchmark either method  
- Package 4.12 does not select the 4.13 winner
- Case C readiness is structural/execution readiness only
- Live visual notes above are human-observed; not automated perceptual scores
