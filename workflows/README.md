# Workflows

Composable ComfyUI workflow definitions organized by capability.

**Status:** Base generation/editing workflows and Package 4.8 library manifests are implemented.
Each production/benchmark workflow directory includes `workflow.json` plus `manifest.json` (parameter schema, statuses, hashes).

| Category | Purpose | Phase |
|----------|---------|-------|
| [base/](base/) | Fundamental generation modes (txt2img, img2img, inpainting, outpainting) | 1 / Package 4–4.8 |
| [controlnet/](controlnet/) | ControlNet-guided generation | 2 |
| [extraction/](extraction/) | Control map extraction from source images | 2 |
| [reference/](reference/) | Identity, reference locking, and modern editing benchmarks | 3 / Package 4.4+ |
| [animation/](animation/) | Motion and video generation | 6 |
| [pipelines/](pipelines/) | Multi-step composed production pipelines | 3–4 |

See [docs/workflow-guide.md](../docs/workflow-guide.md) and [docs/workflow-library.md](../docs/workflow-library.md).

## Layers (Package 4.8)

1. **Canonical** — repository `workflow.json` (immutable during normal use)
2. **Prepared** — parameterized `prep_<uuid>` instances (runtime + Drive + optional project mirror)
3. **Executed snapshot** — Package 4.7 exact post-run capture under `generations/`

## Per-Workflow Documentation

Each workflow directory contains a README with purpose, required models/nodes, inputs, outputs, dependencies, settings, and limitations. Library-facing parameter bindings live in `manifest.json`.
