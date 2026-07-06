# Assets

Centralized storage for model weights and embeddings. Binary files are gitignored; only this documentation is version-controlled.

Download models per the registry in `configs/models/`. Both ComfyUI and A1111 access these via `core/shared_models/` symlinks.

| Directory | Contents |
|-----------|----------|
| [checkpoints/](checkpoints/) | Base model checkpoints (SD 1.5, SDXL, Flux, SVD) |
| [controlnets/](controlnets/) | ControlNet weight files |
| [loras/](loras/) | LoRA adapters |
| [vaes/](vaes/) | VAE files |
| [embeddings/](embeddings/) | Textual inversion embeddings |
| [upscalers/](upscalers/) | ESRGAN and other upscale models |
| [ipadapter/](ipadapter/) | IPAdapter model weights |
| [clip/](clip/) | CLIP vision models |
| [insightface/](insightface/) | InsightFace ONNX models |
