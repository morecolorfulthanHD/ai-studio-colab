# Runtime Platform

Registry-driven runtime layer for AI Studio orchestration.

## Modules

| Module | Purpose |
|--------|---------|
| `registry_loader.py` | Auto-discover and load all `configs/**/*.json` manifests |
| `runtime_state.py` | In-memory session state (models, nodes, launch mode, workflow) |
| `runtime_health.py` | Structured health checks per platform component |
| `runtime_manager.py` | Central entry point — status, health, future install hooks |

## Quick Usage

```python
from pathlib import Path
import sys

sys.path.insert(0, "/content/ai-studio-colab")
from core.runtime.runtime_manager import RuntimeManager

manager = RuntimeManager(Path("/content/ai-studio-colab"))
print(manager.get_runtime_status())
print(manager.health_report().to_human())
```

From shell:

```bash
python core/scripts/runtime_report.py
python core/scripts/runtime_report.py --json
python core/scripts/runtime_report.py --summary
```

## Design

- **Registry-driven** — paths, models, nodes, workflows come from `configs/`
- **Structured health** — `HealthCheck` / `HealthReport` dataclasses, not print-only
- **Plan before execute** — install scripts emit plans; execution deferred
- **Composition** — runtime manager delegates to loader, health, and install planners

## Future Hooks

`RuntimeManager.extension_points()` documents slots for:

- Additional model families (Flux, SDXL)
- Additional engines and inference servers
- Docker, Windows local, and Linux server deployments

See [docs/runtime-platform.md](../../docs/runtime-platform.md).

## Related

| Path | Role |
|------|------|
| `core/scripts/runtime_report.py` | CLI unified report |
| `core/comfyui/install_nodes.py` | Node install plan (dry-run) |
| `core/comfyui/install_models.py` | Model install plan (dry-run) |
| `core/a1111/install.py` | A1111 install plan (dry-run) |
