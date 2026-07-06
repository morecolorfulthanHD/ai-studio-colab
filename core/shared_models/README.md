# Shared Models

Symlinks or junctions pointing to centralized model storage in `assets/`.

## Purpose

Both ComfyUI and A1111 resolve model paths through this directory, ensuring a single copy of each weight file on disk.

## Layout (Phase 1+)

```
shared_models/
├── checkpoints/   → ../../assets/checkpoints/
├── controlnets/   → ../../assets/controlnets/
├── loras/         → ../../assets/loras/
├── vaes/          → ../../assets/vaes/
├── embeddings/    → ../../assets/embeddings/
├── upscalers/     → ../../assets/upscalers/
├── ipadapter/     → ../../assets/ipadapter/
├── clip/          → ../../assets/clip/
└── insightface/   → ../../assets/insightface/
```

Symlinks are created by `core/comfyui/install.sh` and `core/automatic1111/install.sh`.
