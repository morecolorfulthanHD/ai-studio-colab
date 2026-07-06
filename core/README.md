# Core Layer

Engine installations, shared resources, and cross-platform scripts.

| Directory | Purpose |
|-----------|---------|
| [comfyui/](comfyui/) | ComfyUI installation and custom node management |
| [automatic1111/](automatic1111/) | A1111 WebUI installation and extensions |
| [shared_models/](shared_models/) | Symlinks to centralized `assets/` model storage |
| [shared_nodes/](shared_nodes/) | Custom node repos shared across engines |
| [storage/](storage/) | Runtime cache, temp files, upload staging |
| [scripts/](scripts/) | Install, update, health check, and batch utilities |

Engine directories (`ComfyUI/`, `stable-diffusion-webui/`) are gitignored and installed at runtime.
