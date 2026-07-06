# Roadmap

Phased development plan for AI Studio Colab. Each phase produces tested, documented, reusable building blocks before the next phase begins.

**Current status:** Phase 1 bootstrap foundation in progress. Repository architecture (Phase 0) complete. Notebook relocated. Config manifests and bootstrap scripts added.

---

## Phase 0 — Repository Architecture ✓

- [x] Folder structure and module boundaries
- [x] Architecture documentation
- [x] Roadmap and workflow progression docs
- [x] Placeholder README files per directory
- [x] Relocate `AI_Studio_Control_Panel_Colab.ipynb` to `colab/notebooks/`

---

## Phase 1 — Bootstrap Foundation (in progress)

**Goal:** Repository support files so the Colab control panel can orchestrate ComfyUI, models, nodes, and workflows.

| Deliverable | Location | Status |
|-------------|----------|--------|
| Config manifests | `configs/paths/`, `configs/models/`, etc. | Done |
| Bootstrap scripts | `core/scripts/` | Done |
| Control panel documentation | `docs/colab-control-panel.md` | Done |
| ComfyUI install script | `core/comfyui/` | Pending |
| Shared model path wiring | `core/shared_models/` | Pending |
| Base txt2img workflow JSON | `workflows/base/txt2img/` | Pending |
| Notebook integration | `colab/notebooks/` | Pending |
| Git integration for configs | repo root | Pending |

**Exit criteria:**
- ComfyUI launches from Colab control panel
- txt2img produces consistent output from documented settings
- Model and node versions are pinned in config

---

## Phase 1b — Core Foundation (continuation)

**Goal:** A working ComfyUI installation with a reproducible SD 1.5 txt2img workflow.

| Deliverable | Location |
|-------------|----------|
| ComfyUI install script | `core/comfyui/` |
| Shared model path wiring | `core/shared_models/`, `configs/paths/` |
| Base txt2img workflow | `workflows/base/txt2img/` |
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
