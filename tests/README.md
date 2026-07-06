# Tests

Workflow and integration tests for AI Studio Colab.

**Status:** Placeholder. Tests will be added as workflows are implemented.

## Planned Test Categories

| Category | Phase | Description |
|----------|-------|-------------|
| Config validation | 1 | Verify `configs/` schemas and path resolution |
| Node manifest | 1 | Installed nodes match `configs/nodes/` |
| Model verification | 1 | Model hashes match `configs/models/` |
| Workflow smoke tests | 1+ | Each workflow produces expected output shape |
| Pipeline integration | 3+ | Multi-step pipelines complete without error |
| Reproducibility | 2+ | Same seed + preset produces consistent output |
| Use case validation | 7 | Zara Morrison checklist passes |

## Test Conventions

- Tests live alongside or mirror the workflow directory structure
- Smoke tests use minimal resolution and step count for speed
- Golden reference images stored outside Git or in Git LFS
