# Identity Benchmark — IPAdapter FaceID SD1.5

**Status:** Package 4.12 benchmark-only (executable graph; quality untested)

**Candidate:** `ipadapter_faceid_sd15_benchmark`

## Graph intent

Uses the approved FaceID Plus v2 SD1.5 path from `ComfyUI_IPAdapter_plus`:

1. `IPAdapterUnifiedLoaderFaceID` preset **FACEID PLUS V2** (loads matching FaceID adapter + LoRA by exact filename).
2. `IPAdapterFaceID` conditions the SD1.5 model from the registered character primary face.
3. Scenario prompt + seed drive `KSampler` → `VAEDecode` → `SaveImage`.

Prepare binds: staged face filename, scenario prompt, seed (`fixed`), save prefix.

Do not substitute InstantID/SDXL or a different FaceID preset silently.

Prepare/open alone does **not** quality-benchmark the method.
