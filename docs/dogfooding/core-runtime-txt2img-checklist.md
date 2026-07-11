# Dogfooding Checklist — Core Runtime + Base txt2img

Validate Production Package 1 end-to-end in Google Colab before adding OpenPose, ControlNet extraction, IPAdapter, ReActor, SVD, or AnimateDiff.

**Latest validated commit target:** `ae103fa` — Document GitHub canonical notebook architecture

## Quick Path (Production Package 2)

1. Open notebook from GitHub in Colab
2. Run Cells 1–3c (including **Repository Sync**)
3. Run `control_panel()` → **1. Launch** → `minimal`
4. Open ComfyUI URL, import base txt2img workflow, generate image
5. Run `sync_outputs.py`

## Quick Support Script

From repository root:

```bash
python core/scripts/dogfood_core_runtime.py
```

This runs read-only checks and prints `PASS` / `WARN` / `FAIL` per item. It does not install, download, or delete anything.

---

## 1. Colab Runtime Setup

| Step | Action | Pass Criteria |
|------|--------|---------------|
| 1.1 | Open [AI_Studio_Control_Panel_Colab.ipynb](../../colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb) in Google Colab | Canonical notebook only (no duplicates) |
| 1.2 | Runtime → Change runtime type → **GPU** (T4 minimum) | GPU visible in environment checks |
| 1.3 | Confirm repo commit matches target (`51df04f` or newer) | `git log -1 --oneline` shows expected commit |

**Capture:** screenshot of Colab runtime type (GPU) and `git log -1`.

---

## 2. Drive Mount + Repo Clone/Pull

| Step | Action | Pass Criteria |
|------|--------|---------------|
| 2.1 | Run Drive mount cell in notebook | `/content/drive/MyDrive` exists |
| 2.2 | Clone or pull repo to `/content/ai-studio-colab` (or Drive-backed path) | `core/scripts/runtime_report.py` discoverable |
| 2.3 | `cd` to repository root before running scripts | `python core/scripts/bootstrap_repo.py` exits 0 |

**Capture:** Drive mount success output and repo root path.

---

## 3. Notebook Cells to Run

Run in order:

1. **Cells 1–3** — Environment, Drive mount, paths
2. **Repository Sync** — clone/pull from GitHub
3. **Cell 3b** — Repository Bootstrap & Validation
4. **Cell 3c** — Runtime Platform Health
5. **`control_panel()` → 1. Launch → `minimal`** — single-button install + ComfyUI launch
6. Manual workflow import + queue prompt

Optional consolidated check:

```bash
python core/scripts/dogfood_core_runtime.py
```

---

## 4. Bootstrap Validation

```bash
python core/scripts/bootstrap_repo.py
python core/scripts/validate_environment.py
python core/scripts/validate_paths.py
python core/scripts/validate_manifests.py
python core/scripts/list_workflows.py
```

| Check | Pass | Warn | Fail |
|-------|------|------|------|
| Repo structure | all required dirs/files present | — | missing required structure |
| Environment | Colab + GPU detected | local-like environment | script error |
| Manifests | `7/7` pass | — | any manifest schema failure |

---

## 5. Runtime Report + Capability Summary

```bash
python core/scripts/runtime_report.py
python core/scripts/runtime_report.py --summary
python core/scripts/validate_capabilities.py --summary
```

Expected in Colab **before** full install:

- Overall health may be `WARN`
- `txt2img` capability should be `partial` (not falsely `ready`) until SD1.5 + runtime are present

Expected in Colab **after** install + model + successful generation:

- ComfyUI status improves
- txt2img remains `partial` until model validation confirms SD1.5 present

**Capture:** full runtime report output and capability summary line.

---

## 6. ComfyUI Install Validation

Via **control_panel() → Launch** or manually:

```bash
bash core/comfyui/install.sh --execute
```

| Check | Pass | Warn | Fail |
|-------|------|------|------|
| ComfyUI clone | `/content/ComfyUI/.git` exists | path exists but not git clone | install script error |
| Models symlink | `/content/ComfyUI/models` → Drive shared models | symlink target mismatch | refused destructive replace |
| Python deps | requirements install completes | — | pip/install failure |

**Capture:** install script tail output showing `ComfyUI install/validation complete`.

---

## 7. Node Validation / Install Path

Dry-run:

```bash
python core/comfyui/install_nodes.py --dry-run
python core/scripts/check_nodes.py
```

Execute (if needed):

```bash
python core/comfyui/install_nodes.py --execute
python core/scripts/check_nodes.py
```

| Check | Pass | Warn | Fail |
|-------|------|------|------|
| Required node (`ComfyUI-Manager`) | installed | — | missing required after execute |
| Optional nodes | installed or reported missing | missing optional nodes tolerated | required node install failure |

---

## 8. Model Validation (SD 1.5)

No automated downloads in this sprint. Validate presence only:

```bash
python core/scripts/verify_models.py
python core/comfyui/install_models.py --dry-run
python core/comfyui/install_models.py --execute
```

### Verify `sd15.safetensors` exists

Expected Drive path:

```text
/content/drive/MyDrive/AI_Studio/models/shared/checkpoints/sd15.safetensors
```

Manual check:

```bash
ls -lh /content/drive/MyDrive/AI_Studio/models/shared/checkpoints/sd15.safetensors
```

| Check | Pass | Warn | Fail |
|-------|------|------|------|
| SD1.5 checkpoint | file exists and non-zero size | — | missing required checkpoint before generation |
| Advanced models | missing is acceptable | planned models missing | — |

---

## 9. Launch ComfyUI

Use notebook launch cell or manual:

```bash
cd /content/ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

Pass criteria:

- ComfyUI UI loads (Colab proxy URL or ngrok/tunnel if used)
- No immediate startup exceptions in console

**Capture:** ComfyUI startup log snippet and UI URL.

---

## 10. Import Base txt2img Workflow

Workflow file:

```text
workflows/base/txt2img/workflow.json
```

In ComfyUI UI:

1. Load → select workflow JSON from repo path
2. Confirm nodes render: CheckpointLoaderSimple, CLIPTextEncode (x2), EmptyLatentImage, KSampler, VAEDecode, SaveImage
3. Confirm checkpoint widget shows `sd15.safetensors`

| Check | Pass | Fail |
|-------|------|------|
| Workflow import | graph loads without missing-node errors | missing core nodes or invalid JSON |
| Checkpoint resolution | `sd15.safetensors` selectable/present | checkpoint not found |

**Capture:** screenshot of loaded workflow graph.

---

## 11. Queue Prompt + Confirm Output

1. Keep default prompt/negative prompt (or note any edits)
2. Queue prompt
3. Wait for completion

Expected output location:

```text
/content/ComfyUI/output/
```

Filename prefix from workflow: `ai_studio_base_txt2img`

| Check | Pass | Fail |
|-------|------|------|
| Generation completes | image file created in output dir | runtime error / OOM / missing model |
| Image quality sanity | non-black, non-empty image | black/corrupt output |

**Capture:** generated image screenshot and output path listing (`ls -lt /content/ComfyUI/output | head`).

---

## 12. Output Copy (Safe, Latest Only)

Preview:

```bash
python /content/ai-studio-colab/core/scripts/sync_outputs.py --dry-run
```

Copy latest eligible file only (not bulk sync):

```bash
python /content/ai-studio-colab/core/scripts/sync_outputs.py
```

These commands work from any Colab working directory; `%cd /content/ai-studio-colab` is not required.

The script ignores zero-byte placeholders such as `_output_images_will_be_put_here` and selects the newest eligible image/video output (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.mp4`, `.webm`).

Destination:

```text
/content/drive/MyDrive/AI_Studio/outputs/
```

---

## 13. Final State Verification

Re-run:

```bash
python core/scripts/dogfood_core_runtime.py
python core/scripts/runtime_report.py --summary
python core/scripts/validate_capabilities.py --capability txt2img
```

Confirm reports reflect actual runtime state (no false `ready` if SD1.5 or runtime prerequisites are missing).

---

## Pass / Fail Criteria (Sprint Gate)

### Sprint PASS

- Bootstrap + manifests pass
- ComfyUI installs and launches
- Required node path validated (Manager installed or documented workaround)
- SD1.5 checkpoint present at expected Drive path
- `workflows/base/txt2img/workflow.json` imports cleanly
- At least one successful txt2img image generated
- Latest output copied to Drive via `sync_outputs.py`
- Capability/runtime reports align with observed state

### Sprint FAIL

- Repository/schema validation fails
- ComfyUI cannot install or launch
- Workflow JSON invalid or fails to import due to repo issue
- Generation blocked by repo/config errors (not just missing manual model placement)

### Acceptable WARN (non-blocking)

- Optional nodes missing before execute
- Local dry-run environment without Colab/GPU/models
- txt2img capability remains `partial` until SD1.5 is manually placed

---

## Known Issues

| Issue | Notes |
|-------|-------|
| txt2img capability may stay `partial` | By design until SD1.5 presence is validated |
| Colab session timeout | Re-run install/launch cells; persist outputs with `sync_outputs.py` |
| Drive mount re-auth | Re-run mount cell if `validate_environment.py` warns on Drive |
| Windows local path checks | `\content\...` paths warn locally; validate in Colab for authoritative result |

---

## Rollback / Retry Steps

1. Re-clone or `git pull` repository to known good commit (`51df04f`).
2. Re-run bootstrap cells (3b, 3c) before install.
3. ComfyUI reinstall:
   - `bash core/comfyui/install.sh --execute --force-reinstall` (only if intentional reset needed)
4. Reinstall nodes:
   - `python core/comfyui/install_nodes.py --execute`
5. Re-verify SD1.5 path and re-import workflow JSON.
6. Re-queue prompt and re-run `sync_outputs.py --dry-run` before copying.

Do not delete Drive model files during rollback.

---

## Evidence to Attach in Review

- `dogfood_core_runtime.py` summary output
- `runtime_report.py --summary`
- `validate_capabilities.py --capability txt2img`
- ComfyUI startup log excerpt
- Workflow graph screenshot
- Generated image screenshot
- Output path listing + `sync_outputs.py` result
