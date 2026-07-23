# inpainting

**Status:** Implemented — Package 4.8 Workflow Library (`base/inpainting`) — **experimental**

## Purpose

Regenerate masked regions while preserving context (SD1.5 inpainting checkpoint).

## Truthful status

- Runtime: ready
- Quality: **benchmark_failed**
- Production: **experimental**

This workflow executes technically but did not pass the real-world inpainting quality benchmark. Use for testing only.

Preparation requires `--allow-experimental` (CLI) or notebook YES confirmation.

See [docs/workflow-library.md](../../../docs/workflow-library.md) and [docs/decisions/sd15-inpainting-quality-gate.md](../../../docs/decisions/sd15-inpainting-quality-gate.md).
