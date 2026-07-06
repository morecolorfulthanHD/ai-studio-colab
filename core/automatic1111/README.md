# Automatic1111 (A1111)

Secondary WebUI engine for select pipelines and rapid prototyping.

## Contents (Phase 1+)

| Item | Purpose |
|------|---------|
| `install.sh` | Clone stable-diffusion-webui, install dependencies |
| `install_extensions.sh` | Install WebUI extensions matching platform capabilities |
| `launch.sh` | Start A1111 with shared model paths |

The `stable-diffusion-webui/` directory is gitignored and created at install time.

## Strategy

A1111 is secondary to ComfyUI. New workflows are authored in ComfyUI first. A1111 is used where WebUI extensions offer capabilities not yet available as ComfyUI nodes.

Model weights are shared with ComfyUI via `assets/` — no duplicate copies.
