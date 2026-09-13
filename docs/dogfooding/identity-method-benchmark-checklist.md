# Dogfooding — Package 4.12 Identity Method Benchmark

CODE/SIM readiness proves character foundation + **executable** benchmark graphs.  
**Operational acceptance requires live Runs** — prepare/open alone is not a quality claim.

## Package 4.12.3 — Production identity architecture (InstantID SDXL)

| Architecture | Status |
|--------------|--------|
| ReActor | **REJECTED_FOR_PRODUCTION_IDENTITY** |
| SD1.5 FaceID | **REJECTED_FOR_PRODUCTION_IDENTITY** |
| FaceID 4.12.2 sweep | **FAILED_FIRST_SWEEP** |
| InstantID SDXL | **INVESTIGATION** |

### Recommended normal workflow

**Characters → 11. Run production identity benchmark**

One action orchestrates character resolve → runtime preflight → prepare S1–S4 → ComfyUI `/prompt` execute → durable Drive capture → automated scenario QA → **Package 4.12.3 consolidated QA** → consolidated status/report.

Ends in exactly one of: `COMPLETE` | `HUMAN_REVIEW_REQUIRED` | `FAILED`.

CLI equivalent:

```bash
python core/scripts/run_production_identity_benchmark.py --scenario S1-S4 --json
# Interactive [y/N] confirmation, or:
#   --user-confirmed-gpu-run
#   --operator-live-intent   # Cursor only when user explicitly asked to RUN live
```

Status/report: **Characters → 12**. Advanced/debug (prepare, raw execute, diagnostics): **Characters → 13**.

Do **not** use prepare → manually run → manually report as the normal path.

- Ledger: `AI_Studio/logs/identity_architecture_benchmark.jsonl` (separate from `identity_benchmark.jsonl` and tuning ledger)
- Automated QA config: `configs/benchmarks/identity_architecture_qa.json` (`calibration_status: uncalibrated`)
- Consolidated QA: `python core/scripts/qa_package4123.py`
- S4 resolution: **1024×768** landscape (not 512×768 portrait)
- Do **not** retune rejected SD1.5 FaceID graphs
- Cursor/Colab operator: `docs/cursor-colab-operator.md` — navigate `9 → 13 → 11`
## OPERATIONAL PASS vs VISUAL SCENARIO PASS

Never use “benchmark passed” when only execution/capture succeeded.

| Scenario | Execution (operational) | Identity | Scenario adherence | Quality result |
|----------|-------------------------|----------|--------------------|----------------|
| **Baseline FaceID S1** | PASS | GOOD | PASS | PASS |
| **Baseline FaceID S2** | PASS | GOOD | FAIL (near-front; ~40° turn missing) | FAIL |
| **Baseline FaceID S3** | PASS | GOOD | FAIL (neutral; no visible-teeth smile) | FAIL |
| **Baseline FaceID S4** | PASS | GOOD | FAIL (wardrobe/environment/framing) | FAIL |
| **Package 4.12 overall visual selection** | — | — | — | **PENDING / NOT ACCEPTED** |

Package 4.12.2 FaceID conditioning-sweep infrastructure may be **CODE/SIM accepted** before live tuning Runs. That does **not** mean any variant passed, FaceID is selected, or Package 4.12 is visually accepted.

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

## Frozen baseline evidence (do not rerun)

| Scenario | Prep ID | Seed |
|----------|---------|------|
| S1 | `prep_efa7b6d8-58ec-4d26-8d19-697ec3ce9558` | `4791031672062905` |
| S2 | `prep_dcacc2ae-dc0a-45e7-90a5-5b6eb8026b1b` | `470280831310422` |
| S3 | `prep_5b0773a9-30fc-436a-aa30-d40dec98e517` | `5926742613902171` |
| S4 | `prep_5b669994-aa64-44bf-b349-3ec1e9021800` | `2792331214840135` |

Preserve historical Drive outputs. Do not delete. Do not overwrite baseline ledger rows.

## Live Cases A–F

| Case | Status / steps |
|------|----------------|
| A | **LIVE PASS** — character register/list/show + SHA |
| B | **LIVE PASS** — Full Reset + relaunch; character still resolves |
| C | **OPERATIONAL PASS / VISUAL PENDING** — ReActor + FaceID S1–S4 executed; FaceID visual scenario adherence FAIL on S2/S3/S4 |
| D–F | **NOT STARTED** (selection / promotion) |

## Live Case C notes (human-observed; not automated scores)

Character: `char_7471a702-55cf-4c7b-adb2-e17404d28c91` (Benchmark Persona).  
Do **not** overwrite `human_review=pending` ledger fields automatically — enter rubric manually.

### ReActor (summary)

- Pipeline operational; visual identity consistency poor across S1–S4.
- Not acceptable for 4.13 virtual-character identity as currently observed.

### FaceID — S1 (`prep_efa7b6d8-58ec-4d26-8d19-697ec3ce9558`, seed `4791031672062905`)

- Historical successful executions preserved on Drive; do not delete.
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

### FaceID — S4 (`prep_5b669994-aa64-44bf-b349-3ec1e9021800`, seed `2792331214840135`)

- Identity held; facial naturalness good.
- Red jacket FAILED; city-street environment FAILED; full-scene framing FAILED.
- Scene robustness not demonstrated.

### Promotion stance (Package 4.12)

- FaceID is currently stronger than ReActor for near-front identity fidelity.
- FaceID has **not** demonstrated robust controlled pose/expression variation (S2/S3).
- **Do not auto-promote FaceID.** Promotion remains pending.
- **Neither** remains a valid final Package 4.12 outcome.

## Package 4.12.2 — FaceID conditioning sweep (tuning)

Isolated from baseline `identity_benchmark.jsonl`. Ledger: `AI_Studio/logs/identity_benchmark_tuning.jsonl`.

| Item | Value |
|------|-------|
| preparation_kind | `identity_benchmark_tuning` |
| subtype | `faceid_conditioning_sweep` |
| First phase | **S2 + S3 only** (S1/S4 refused) |
| Variants | A `faceid_v2_1p5_full`, B `faceid_v2_1p0_full`, C `faceid_v2_1p5_end080`, D `faceid_v2_1p0_end080` |
| Changed fields | `weight`, `weight_faceidv2`, `start_at`, `end_at` only |
| Unchanged | lora_strength, weight_type, combine_embeds, sampler/steps/cfg/checkpoint/neg prompt |
| Seeds | Reuse frozen baseline S2/S3 seeds |
| Prompts | Exact baseline S2/S3 prompts |
| UX | Characters → **9** prepare tuning / **10** tuning report |
| Max runs | 8 (A–D × S2/S3), manual one-at-a-time operator Runs |

### Explicit pass bar (human)

- **S2 pass** requires unmistakable ~40° three-quarter turn + same character + no severe distortion. Near-front = FAIL even if identity is good.
- **S3 pass** requires unmistakable genuine smile with visible teeth + same character. Neutral = FAIL even if identity is good.

### Decision after first sweep

- If one variant passes **both** S2 and S3 → nominate as tuned candidate; still **do not promote**; next step = S4 validation.
- If different winners for S2 vs S3 → report split; do not silently blend.
- If none pass both → first-sweep FAILED; stop endless tuning; recommend NEITHER or different architecture.

### Deferred S4 composition (document only — not chosen in 4.12.2)

Current baseline S4 used portrait-biased framing. Before any future tuned S4 Run, review explicitly:

| Option | Notes |
|--------|-------|
| 768×512 landscape | Favors environmental width; may help city-street framing |
| 768×768 square | Neutral; may still portrait-bias if camera is close |
| 512×768 portrait | Baseline-like; **not recommended** for S4 scene tests |

Do **not** hardcode a choice silently. Future S4 prompt may be more explicit about full-body / red jacket / city street after S2/S3 winner selection.

## Explicit non-claims

- Simulations do not quality-benchmark either method  
- Prepare/open does not quality-benchmark either method  
- Package 4.12 does not select the 4.13 winner
- Operational execution/capture PASS ≠ visual scenario PASS
- Live visual notes above are human-observed; not automated perceptual scores
- Package 4.12.2 CODE/SIM ≠ FaceID promotion
