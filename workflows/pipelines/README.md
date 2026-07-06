# Pipeline Workflows

Pre-composed multi-step workflows for common production tasks. Pipelines internally chain `base/`, `controlnet/`, `extraction/`, and `reference/` workflows.

**Status:** Not yet implemented (Phase 3–4)

| Pipeline | Phase | Purpose |
|----------|-------|---------|
| [portrait_generation/](portrait_generation/) | 3 | Consistent character portraits |
| [environment_generation/](environment_generation/) | 4 | Coherent environment scenes |
| [environment_reconstruction/](environment_reconstruction/) | 4 | Rebuild environment from multiple viewpoints |
| [multi_angle_generation/](multi_angle_generation/) | 4 | New camera angles from references |

Each pipeline README documents the full sub-workflow chain and data passed between steps.
