# Workflow Guide

How workflows are organized, how they compose, and the intended progression from simple generation to full production pipelines.

## Workflow Documentation Standard

Every workflow directory will eventually contain:

| Field | Description |
|-------|-------------|
| **Purpose** | What this workflow does and when to use it |
| **Required models** | Checkpoints, ControlNets, LoRAs, VAEs, etc. |
| **Required nodes** | Custom ComfyUI nodes and versions |
| **Inputs** | Prompts, images, masks, control maps, parameters |
| **Outputs** | Image/video files, intermediate maps, metadata |
| **Dependencies** | Other workflows or extraction steps that must run first |
| **Recommended settings** | Sampler, steps, CFG, resolution, denoise strength |
| **Sample images** | Reference outputs stored in workflow directory or `output/` |
| **Known limitations** | Edge cases, quality caveats, hardware requirements |

Workflow JSON files and their README documentation live in the same directory. The canonical index of planned and active workflows is `configs/workflows/workflow_registry.json`. Cross-cutting asset dependencies are tracked in `configs/assets/asset_registry.json` and user-facing functionality readiness is tracked in `configs/capabilities/capability_registry.json` — see [asset-registry.md](../docs/asset-registry.md) and [capability-platform.md](capability-platform.md).

List on-disk workflow JSON files:

```bash
python core/scripts/list_workflows.py
```

## Workflow Taxonomy

```
workflows/
├── base/              # Fundamental generation modes
├── controlnet/        # ControlNet-guided generation
├── extraction/        # Preprocessor map generation
├── reference/         # Identity and reference locking
├── animation/         # Motion and video
└── pipelines/         # Multi-step composed pipelines
```

## Intended Progression

Workflows are designed to be learned and adopted in this order. Each stage builds on the previous.

### Stage 1 — Base Generation

Start here. No ControlNet or reference images required.

```
txt2img → hires_fix → img2img
                    → inpainting
                    → outpainting
```

| Workflow | Purpose |
|----------|---------|
| `base/txt2img/` | Text prompt to image (SD 1.5) |
| `base/hires_fix/` | Two-pass upscale refinement |
| `base/img2img/` | Image refinement with denoise |
| `base/inpainting/` | Masked region regeneration |
| `base/outpainting/` | Canvas extension beyond original bounds |

### Stage 2 — Structural Control

Add ControlNet guidance and learn to extract control maps from source images.

```
extraction/depth_map  ──┐
extraction/pose_map   ──┼──► controlnet/depth
extraction/normal_map ──┤    controlnet/openpose
extraction/seg_map    ──┘    controlnet/normal
                             controlnet/segmentation
                             controlnet/canny
                             controlnet/lineart
```

**Pattern:** Run an extraction workflow on a source image → feed the resulting map into the matching ControlNet workflow.

### Stage 3 — Reference & Identity

Lock visual identity across generations using reference images.

```
reference/reference_lock  ──► base workflows
reference/ipadapter       ──► controlnet workflows
reference/identity        ──► pipelines/portrait_generation
reference/multi_reference ──► pipelines (combined)
```

**Composition example — consistent portrait with pose control:**

1. `extraction/pose_map` — extract pose from reference photo
2. `reference/ipadapter` — load character reference for identity
3. `controlnet/openpose` — generate with locked pose + identity

### Stage 4 — Pipelines

Pre-composed multi-step workflows for common production tasks. Pipelines internally chain base, controlnet, extraction, and reference workflows.

| Pipeline | Composes |
|----------|----------|
| `pipelines/portrait_generation/` | reference + base txt2img/hires_fix |
| `pipelines/environment_generation/` | base + controlnet depth/normal |
| `pipelines/environment_reconstruction/` | multi_reference + extraction + controlnet |
| `pipelines/multi_angle_generation/` | environment_reconstruction + controlnet openpose |

### Stage 5 — Animation & Video

Extend still-image pipelines into motion.

```
pipelines/portrait_generation ──► animation/image_sequence
                                ──► animation/animatediff
                                ──► animation/svd
```

| Workflow | Input | Output |
|----------|-------|--------|
| `animation/image_sequence/` | Keyframe images + prompts | Numbered frame sequence |
| `animation/animatediff/` | Single image or short prompt | Short animated clip |
| `animation/svd/` | Single still image | Video clip |

## Composition Rules

1. **Prefer small workflows** — Chain two or three focused workflows rather than one large graph.
2. **Extraction before control** — Always generate control maps via `extraction/` workflows; do not embed preprocessors inside generation workflows unless performance requires it.
3. **Configs, not hardcodes** — Workflows reference `configs/presets/` keys for parameters; never embed model filenames in workflow JSON.
4. **Document the chain** — Pipeline README files must list every sub-workflow invoked and the data passed between them.
5. **Use cases consume, don't fork** — Project-specific prompts and references go in `use_cases/`; the workflow JSON stays in `workflows/`.

## Capabilities vs Workflows

- A **workflow** is an implementation artifact (`workflow.json`) for a specific graph/pipeline.
- A **capability** is a user-facing function (e.g. txt2img, depth extraction) that may be implemented by one or more workflows.
- Capability readiness is computed from required models/nodes/assets/workflows, not from one file existing.

In short: workflows *implement* capabilities; capabilities *describe what the platform can currently do*.

## Workflow File Conventions

```
workflows/<category>/<name>/
├── README.md           # Full documentation (required)
├── workflow.json       # ComfyUI workflow export (Phase 1+)
├── workflow_api.json   # API-format export for scripting (optional)
└── samples/            # Example outputs (optional, gitignored if large)
```

### Naming

- Directories: `snake_case`
- Workflow files: `workflow.json` (default), or `<variant>_workflow.json` for alternates
- Preset references: match keys in `configs/presets/`

## Relating Workflows to Use Cases

Use cases in `use_cases/<project>/` provide:

- **prompts/** — Prompt templates with variable slots
- **references/** — Character and object reference images
- **environments/** — Environment capture sets
- **test_outputs/** — Validation run results
- **documentation/** — Project-specific workflow chains and checklists

A use case README describes which platform workflows it chains together and with what inputs. It does not duplicate workflow JSON.

### Example: Zara Morrison Portrait Chain

```
use_cases/zara_morrison/references/face_ref.png
        │
        ▼
workflows/reference/ipadapter/        (identity lock)
        +
workflows/controlnet/openpose/        (pose from extraction/pose_map)
        │
        ▼
workflows/pipelines/portrait_generation/
        │
        ▼
use_cases/zara_morrison/test_outputs/
```

## Status

`base_txt2img` is now implemented at `workflows/base/txt2img/workflow.json` and serves as the first production baseline. Remaining workflows in `configs/workflows/workflow_registry.json` are still planned.

Launch and select workflows via [`colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb`](../colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb) once workflow menus are wired in the control panel.
