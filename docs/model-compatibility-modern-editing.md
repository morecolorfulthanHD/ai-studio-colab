# Modern Editing Model Compatibility (Package 4.4)

Benchmark candidates only. **Do not** treat either candidate as the production inpainting default until a documented selection gate passes.

## Summary

| Candidate | Purpose | License | Gated download | Commercial production default? |
|-----------|---------|---------|----------------|--------------------------------|
| Qwen-Image-Edit-2511 | Instruction-driven object/material edits | **Apache-2.0** (official model card) | Usually no (public Apache weights; verify source) | Eligible for consideration after benchmark + user approval |
| FLUX.1 Fill [dev] | Mask-driven inpaint/outpaint | **FLUX.1-dev Non-Commercial License** | Yes (HF agreement required) | **No** — do not silently designate as commercial production default |

Sources consulted: https://huggingface.co/Qwen/Qwen-Image-Edit-2511 , https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit-2511 , https://docs.comfy.org/tutorials/flux/flux-1-fill-dev , https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev

---

## Qwen-Image-Edit-2511

- **Source:** Qwen / Comfy-Org repackaged ComfyUI weights
- **License:** Apache License 2.0 (official card: "Qwen-Image is licensed under Apache 2.0.")
- **Commercial-use restrictions:** Follow Apache-2.0; no FLUX-style non-commercial weight restriction
- **Gated download:** Not gated like FLUX Fill; still download manually (AI Studio does not auto-download)
- **Expected files (official template):**
  - `qwen_image_edit_2511_fp8mixed.safetensors` (diffusion; docs also mention bf16 variant)
  - `qwen_2.5_vl_7b_fp8_scaled.safetensors` (text encoder)
  - `qwen_image_vae.safetensors` (VAE)
  - Optional: `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors`
- **Suggested Drive layout:**
  - `/content/drive/MyDrive/AI_Studio/models/shared/qwen_image_edit/`
- **L4 compatibility:** Prefer **fp8mixed** on Colab L4 (~24GB); bf16 may require offload / fail
- **Approximate VRAM modes:** fp8 (recommended L4), bf16 (higher), quantized GGUF (community; not Package 4.4 official), CPU offload if needed
- **Verification:** `python core/scripts/verify_models.py` (after registry entries) and prepare-script preflight

---

## FLUX.1 Fill [dev]

- **Source:** Black Forest Labs + ComfyUI official tutorials
- **License:** FLUX.1 [dev] Non-Commercial License (weights)
- **Commercial-use restrictions:** Weights are non-commercial; official docs note generated outputs may be usable for personal/scientific/commercial purposes under the license text — **verify the current LICENSE.md** before any commercial reliance
- **Gated download:** Yes — must agree on Hugging Face before download
- **Expected files:**
  - `flux1-fill-dev.safetensors`
  - `clip_l.safetensors`
  - `t5xxl_fp16.safetensors` (fp8 optional for lower VRAM)
  - `ae.safetensors`
- **Suggested Drive layout:**
  - `/content/drive/MyDrive/AI_Studio/models/shared/flux_fill/`
- **L4 compatibility:** Often requires **fp8 text encoder** and/or aggressive offload; validate live before promotion
- **Approximate VRAM modes:** native (heavy), fp8, quantized (community), CPU offload often required on 24GB
- **Commercial production default:** **Forbidden without an alternate license grant**

---

## Missing-file instructions

1. Do **not** run automatic gated downloads from AI Studio scripts.
2. Manually place files under the Drive paths above (or symlink into ComfyUI `models/`).
3. Re-run the corresponding `prepare_*` script; it validates required files before writing prepared JSON.
4. Keep SD1.5 inpainting available until the selection gate and user approval complete.
