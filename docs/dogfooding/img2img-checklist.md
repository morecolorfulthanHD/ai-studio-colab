# Dogfooding Checklist — Base img2img

Validate Production Package 4 img2img in Google Colab before identity-lock or scene-consistency workflows.

## Quick Path

1. Open canonical notebook from GitHub in Colab
2. Run Cells 1–3c (including **Repository Sync**)
3. `control_panel()` → **1. Launch** → `minimal`
4. Place a source image in `AI_Studio/inputs/images/`
5. `control_panel()` → **7. Image Editing** → **1. img2img**
6. Prepare workflow, load in ComfyUI, queue prompt
7. `sync_outputs.py` and `verify_generation.py --workflow img2img`

---

## 1. Fresh Colab Startup

| Step | Action | Pass Criteria |
|------|--------|---------------|
| 1.1 | GPU runtime enabled | GPU visible in environment checks |
| 1.2 | Repository sync to `/content/ai-studio-colab` | `runtime_report.py` runs |

**Capture:** GPU runtime and `git log -1`.

---

## 2. Launch Mode

| Step | Action | Pass Criteria |
|------|--------|---------------|
| 2.1 | `control_panel()` → 1 → `minimal` | ComfyUI URL printed |
| 2.2 | SD1.5 checkpoint present on Drive | `verify_models.py` OK |

**Capture:** ComfyUI URL and SD1.5 path confirmation.

---

## 3. Input Placement

| Step | Action | Pass Criteria |
|------|--------|---------------|
| 3.1 | Create `AI_Studio/inputs/images/` if missing | Directory exists on Drive |
| 3.2 | Copy a `.png` or `.jpg` source image | `list_inputs.py` lists the file |

**Capture:** `list_inputs.py` output with exact path.

---

## 4. Workflow Preparation

```bash
python core/scripts/prepare_workflow.py --workflow img2img --input /path/to/source.png
python core/scripts/prepare_workflow.py --workflow img2img --input /path/to/source.png --dry-run
```

| Check | Pass | Fail |
|-------|------|------|
| Valid image path | Staged copy in ComfyUI/input + prepared JSON | Preparation error |
| Invalid extension (`.txt`) | Error reported | Silent success |
| Canonical `workflows/base/img2img/workflow.json` | Unchanged byte-for-byte | Modified |

**Capture:** preparation stdout with prepared path.

---

## 5. Capability Readiness

```bash
python core/scripts/validate_capabilities.py --capability img2img
```

| Field | Expected (installed runtime) |
|-------|------------------------------|
| `computed_status` | `ready` |
| `execution_input_status` | `not_selected` or `available` (does not downgrade readiness) |

**Capture:** capability summary line.

---

## 6. ComfyUI Import and Generation

| Step | Action | Pass Criteria |
|------|--------|---------------|
| 6.1 | Load prepared workflow JSON in ComfyUI | 8-node graph visible |
| 6.2 | Confirm nodes: LoadImage, VAEEncode, KSampler, VAEDecode, SaveImage | All present |
| 6.3 | Import prepared workflow; staged files already in ComfyUI/input | Image and mask load without manual copy |
| 6.4 | Queue prompt | Output with prefix `ai_studio_base_img2img` |

**Capture:** ComfyUI graph screenshot and output filename.

---

## 7. Output Verification

```bash
python core/scripts/sync_outputs.py --dry-run
python core/scripts/sync_outputs.py
python core/scripts/verify_generation.py --workflow img2img --summary
```

| Check | Pass |
|-------|------|
| Local evidence | Eligible output found |
| Drive evidence | Exact byte-size match after sync |
| Verification state | `verified` or `verified_local` |

**Capture:** verify_generation summary.

---

## Pass / Fail Criteria

**PASS** when:

- `img2img` capability is `READY` with valid workflow
- Preparation succeeds for a valid input
- At least one `ai_studio_base_img2img_*` output generated
- Evidence verification reports expected state after sync

**FAIL** when:

- Workflow validation fails
- Preparation modifies canonical workflow JSON
- Capability downgraded to `PARTIAL` solely because no input is selected

---

## Troubleshooting

| Issue | Action |
|-------|--------|
| LoadImage shows missing file | Copy image to ComfyUI `input/` or use absolute path |
| Capability `PARTIAL` | Run `validate_capabilities.py --capability img2img` for reasons |
| No Drive evidence | Run `sync_outputs.py`; confirm Drive mount |
| High denoise destroys composition | Lower denoise toward 0.45–0.55 |
