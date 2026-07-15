# Dogfooding Checklist — Package 4.5 Runtime Truthfulness

## Launch output cleanup

1. Launch Full mode on a fresh Colab runtime.
2. Confirm launch output does **not** instruct running `sync_outputs.py` or `verify_generation.py` as normal steps.
3. Confirm **Automatic output persistence** block is printed (watcher, Drive destination, evidence ledger).
4. Confirm txt2img guidance says outputs sync automatically after Run.

## Zero-command persistence (regression)

5. Generate txt2img — do not run manual sync commands.
6. Confirm Drive copy, SHA-256 match, and `generation_evidence.jsonl` verified row.

## Enriched provenance

7. Inspect evidence with `python core/scripts/show_generation.py --prompt-id <id> --json`.
8. Confirm `schema_version: 2` fields on the new verified row:
   - `workflow_identifier: base/txt2img`
   - `workflow_source: registered_canonical`
   - `workflow_hash_type: ui_workflow_v1`
   - `capability: txt2img`
   - `model_family: sd15`
   - `model_files: ["sd15.safetensors"]`
   - actual positive/negative prompts (resolved via KSampler wiring)
   - actual `seed`, `steps`, `cfg`, `sampler_name`, `scheduler`, `denoise`
   - `provenance_status: complete` (never falsely `complete`)
8b. Run img2img or outpainting and confirm it is **not** mislabeled `txt2img`
    (`capability: img2img` / `outpainting`).

## Inpainting truthfulness

9. Run `python core/scripts/validate_capabilities.py --capability inpainting`.
10. Confirm:
    - runtime: READY (when dependencies present)
    - quality: BENCHMARK_FAILED
    - production: EXPERIMENTAL
11. Confirm Qwen and FLUX remain benchmark-only in `workflow_catalog.py --summary`.

## Pass / Fail

**PASS:** truthful launch messaging, enriched provenance on new generations, inpainting quality gate explicit, zero-command persistence unchanged.

**FAIL:** manual sync presented as required, inpainting described as production-ready, or provenance fields guessed when unavailable.
