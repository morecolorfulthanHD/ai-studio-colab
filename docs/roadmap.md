# Roadmap

Phased development plan for AI Studio Colab. Each phase produces tested, documented, reusable building blocks before the next phase begins.

**Current status:** Epic 2 Package 2 — unified asset registry foundation.

---

## Epic 2 — Runtime Platform

### Package 1 — Runtime Foundation ✓

- [x] Runtime manager, health model, registry loader
- [x] Install planners (dry-run), `runtime_report.py`, Cell 3c

### Package 2 — Unified Asset Registry (in progress)

**Goal:** Cross-cutting asset inventory layer for models, workflows, references, anchors, and maps.

| Deliverable | Location | Status |
|-------------|----------|--------|
| Asset registry manifest | `configs/assets/asset_registry.json` | Done |
| Asset manager | `core/runtime/asset_manager.py` | Done |
| Asset validation CLI | `core/scripts/validate_assets.py` | Done |
| Runtime integration | health + `runtime_report.py` | Done |
| Asset registry docs | `docs/asset-registry.md` | Done |
| Notebook asset check | Cell 3c `--summary` | Done |

**Exit criteria:**
- `validate_assets.py` reports by type, status, workflow
- `runtime_report.py` includes asset summary
- Health check includes `assets` component

### Package 3 — Install Execution (planned)

- Execute install plans from registry planners
- Wire runtime manager into notebook Cell 9
- First workflow JSON (`base/txt2img`)

---

## Phase 0 — Repository Architecture ✓

- [x] Folder structure and module boundaries
- [x] Architecture documentation
- [x] Roadmap and workflow progression docs
- [x] Placeholder README files per directory
- [x] Relocate `AI_Studio_Control_Panel_Colab.ipynb` to `colab/notebooks/`

---

## Phase 1 — Bootstrap Foundation ✓

- [x] Config manifests (`configs/paths/`, `configs/models/`, etc.)
- [x] Bootstrap scripts (`core/scripts/`)
- [x] Control panel documentation (`docs/colab-control-panel.md`)

---

## Phase 1b — Notebook Wiring & ComfyUI Install Prep ✓

- [x] Notebook bootstrap cells (Cell 3b)
- [x] ComfyUI `install.sh`
- [x] `check_nodes.py`, `verify_models.py`

---

## Phase 1c — Core Foundation (continuation)

**Goal:** A working ComfyUI installation with a reproducible SD 1.5 txt2img workflow.

| Deliverable | Location |
|-------------|----------|
| Notebook install.sh integration | `colab/notebooks/` Cell 9 |
| Custom node install script | `core/comfyui/install_nodes.sh` |
| Base txt2img workflow JSON | `workflows/base/txt2img/` |
| Launch integration | `colab/launch/` |
| Model download logic | driven by `configs/models/model_registry.json` |

**Exit criteria:**
- ComfyUI launches from Colab control panel
- txt2img produces consistent output from documented settings
- SD 1.5 checkpoint entry marked `active` in model registry

---

## Phase 2 — ControlNet & Structural Guidance

**Goal:** ControlNet workflows for pose, depth, edges, normals, and segmentation.

| Deliverable | Location |
|-------------|----------|
| ControlNet model configs | `configs/models/`, `assets/controlnets/` |
| ControlNet Aux node setup | `configs/nodes/` |
| Canny, depth, openpose workflows | `workflows/controlnet/` |
| Normal, segmentation, lineart workflows | `workflows/controlnet/` |
| Map extraction workflows | `workflows/extraction/` |
| img2img and hires fix base workflows | `workflows/base/` |

**Exit criteria:**
- Each ControlNet type produces documented sample output
- Extraction workflows generate reusable control maps from source images

---

## Phase 3 — Reference Locking & Identity

**Goal:** Multi-reference pipelines that preserve character and environment identity.

| Deliverable | Location |
|-------------|----------|
| IPAdapter model assets | `assets/ipadapter/` |
| Reference lock workflow | `workflows/reference/reference_lock/` |
| IPAdapter workflow | `workflows/reference/ipadapter/` |
| Identity preservation workflow | `workflows/reference/identity/` |
| Multi-reference pipeline | `workflows/reference/multi_reference/` |
| Inpainting / outpainting base | `workflows/base/` |

**Exit criteria:**
- Identity consistency demonstrated across 5+ generations from one reference set
- Environment reference locking produces coherent backgrounds

---

## Phase 4 — Environment & Multi-Angle

**Goal:** Environment reconstruction, new camera angles, and consistency across viewpoints.

| Deliverable | Location |
|-------------|----------|
| Environment generation pipeline | `workflows/pipelines/environment_generation/` |
| Environment reconstruction pipeline | `workflows/pipelines/environment_reconstruction/` |
| Multi-angle generation pipeline | `workflows/pipelines/multi_angle_generation/` |
| Portrait generation pipeline | `workflows/pipelines/portrait_generation/` |

**Exit criteria:**
- Environment reconstructed from 3+ reference viewpoints
- New camera angles generated with consistent lighting and objects

---

## Phase 5 — Face & Identity Refinement

**Goal:** Face swap, restoration, and identity refinement via ReActor and InsightFace.

| Deliverable | Location |
|-------------|----------|
| InsightFace model assets | `assets/insightface/` |
| ReActor node integration | `configs/nodes/` |
| Face workflows integrated into reference pipelines | `workflows/reference/` |

**Exit criteria:**
- Face replacement and restoration workflows documented with before/after samples
- Identity refinement improves consistency without artifacts

---

## Phase 6 — Animation & Video

**Goal:** Image sequences, AnimateDiff animations, and SVD video generation.

| Deliverable | Location |
|-------------|----------|
| AnimateDiff workflow | `workflows/animation/animatediff/` |
| SVD workflow | `workflows/animation/svd/` |
| Image sequence workflow | `workflows/animation/image_sequence/` |
| Video model configs | `configs/models/` |

**Exit criteria:**
- Short animation clips generated from single reference images
- SVD produces stable video from still inputs
- Camera movement sequences documented

---

## Phase 7 — Production & Automation

**Goal:** Batch processing, dataset management, prompt libraries, and social automation hooks.

| Deliverable | Location |
|-------------|----------|
| Batch workflow runner | `core/scripts/` |
| Prompt library structure | `use_cases/` pattern + shared `configs/presets/` |
| Dataset management utilities | `core/scripts/`, `colab/utilities/` |
| Automation integration points | `colab/launch/` |
| Full test suite | `tests/` |

**Exit criteria:**
- End-to-end batch run processes a reference set unattended
- Zara Morrison validation use case passes full checklist (see `use_cases/zara_morrison/`)

---

## Future (Post Phase 7)

| Item | Notes |
|------|-------|
| SDXL support | Parallel workflow tree, model config entries |
| Flux support | New checkpoint family, updated presets |
| A1111 workflow parity | Select pipelines where WebUI extensions excel |
| Social media automation | Built on Phase 7 automation layer |

---

## Validation Milestone: Zara Morrison

Zara Morrison is the first production validation target. It exercises Phases 3–7 capabilities but does not drive architecture decisions. Success means:

- Facial, hairstyle, and clothing consistency across unlimited images
- Environment consistency and multi-viewpoint reconstruction
- Image and animated sequence generation
- Reusable references for future content pipelines

All Zara-specific assets live in `use_cases/zara_morrison/` only.
