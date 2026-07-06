# Workflows

Composable ComfyUI workflow definitions organized by capability.

**Status:** Architecture only. No workflow JSON files exist yet.

| Category | Purpose | Phase |
|----------|---------|-------|
| [base/](base/) | Fundamental generation modes | 1 |
| [controlnet/](controlnet/) | ControlNet-guided generation | 2 |
| [extraction/](extraction/) | Control map extraction from source images | 2 |
| [reference/](reference/) | Identity and reference locking | 3 |
| [animation/](animation/) | Motion and video generation | 6 |
| [pipelines/](pipelines/) | Multi-step composed production pipelines | 3–4 |

See [docs/workflow-guide.md](../docs/workflow-guide.md) for composition rules and progression order.

## Per-Workflow Documentation

Each workflow directory contains a README with purpose, required models/nodes, inputs, outputs, dependencies, settings, and limitations. Workflow JSON is added during implementation phases.
