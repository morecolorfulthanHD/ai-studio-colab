# Reference Workflows

Identity locking, reference image conditioning, and multi-reference pipelines.

**Status:** Not yet implemented (Phase 3–5)

| Workflow | Purpose |
|----------|---------|
| [reference_lock/](reference_lock/) | Lock visual attributes from a reference image |
| [ipadapter/](ipadapter/) | IPAdapter-based style and composition transfer |
| [identity/](identity/) | Facial identity preservation |
| [multi_reference/](multi_reference/) | Combine multiple reference images |

## Required Models

- IPAdapter weights → `assets/ipadapter/`
- CLIP vision → `assets/clip/`
- InsightFace (Phase 5) → `assets/insightface/`

## Composition

Reference workflows layer on top of `base/` and `controlnet/` workflows. They do not replace structural control — they add identity and style conditioning.
