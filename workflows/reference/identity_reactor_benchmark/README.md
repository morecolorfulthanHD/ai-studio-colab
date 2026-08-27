# Identity Benchmark — ReActor Face Swap

**Status:** Package 4.12 benchmark-only (executable graph; quality untested)

**Candidate:** `reactor_faceswap_benchmark`

## Graph intent

1. Generate an SD1.5 scenario image (`CheckpointLoaderSimple` → prompts → `KSampler` → `VAEDecode`).
2. Load the registered character primary face (`LoadImage`).
3. Apply `ReActorFaceSwap` with character face as **source** and scenario image as **input/target**.
4. Save the swapped result for S1–S4 human scoring.

Prepare binds: staged face filename, scenario prompt, seed (`fixed`), save prefix.

Prepare/open alone does **not** quality-benchmark the method.
