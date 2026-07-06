# Base Workflows

Fundamental image generation modes. These are the first workflows implemented (Phase 1) and serve as building blocks for all other categories.

| Workflow | Phase | Purpose |
|----------|-------|---------|
| [txt2img/](txt2img/) | 1 | Text prompt to image |
| [img2img/](img2img/) | 2 | Image refinement with denoise strength |
| [hires_fix/](hires_fix/) | 2 | Two-pass generation with upscale |
| [inpainting/](inpainting/) | 3 | Masked region regeneration |
| [outpainting/](outpainting/) | 3 | Canvas extension beyond original bounds |

## Composition

Base workflows are invoked directly or chained inside `pipelines/` and combined with `controlnet/` and `reference/` workflows.
