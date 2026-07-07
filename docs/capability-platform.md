# Capability Platform

Capabilities are the user-facing abstraction layer that answers:

> What can this AI Studio currently do?

## Why capabilities exist

The platform already tracks files and dependencies:

- Models (`model_registry.json`)
- Nodes (`node_registry.json`)
- Assets (`asset_registry.json`)
- Workflows (`workflow_registry.json`)

Those registries describe *what exists*.  
Capabilities describe *what functionality is achievable* given those dependencies.

## Capability vs other registries

| Layer | Represents |
|------|------------|
| Models | Weights/checkpoints and model-family metadata |
| Nodes | Engine extension packages |
| Assets | Cross-cutting inventory (models, prompts, references, maps, workflows) |
| Workflows | Concrete graph definitions and pipeline files |
| Capabilities | User-facing functionality (e.g., txt2img, depth extraction, SVD) |

Capabilities are not implementations.  
Workflows implement capabilities; capabilities evaluate whether implementations are runnable.

## Registry

Location: `configs/capabilities/capability_registry.json`

Each entry defines:

- identity (`id`, `name`, `description`)
- taxonomy (`category`, `maturity`, `status`)
- compatibility (`supported_engines`)
- requirements (`required_models`, `required_nodes`, `required_assets`, `required_workflows`)
- composition (`dependencies`)
- validation metadata (`validation_rules`, `notes`)

## Readiness model

`CapabilityManager` evaluates each capability into one of:

- `ready` — requirements satisfied and not disabled
- `partial` — some soft requirements (typically assets) still absent but core wiring exists
- `unavailable` — hard requirements missing (models/nodes/workflows)
- `blocked` — disabled capability or invalid dependency chain

This computed status is separate from registry `status` (planned/partial/ready/disabled).

### Dependency propagation

Dependencies are evaluated recursively by computed status, not just registry existence:

| Dependency state | Effect on dependent |
|------------------|---------------------|
| Unknown id | `blocked` |
| Circular reference | `blocked` |
| `blocked` or `unavailable` | `blocked` |
| `partial` | `partial` (unless already worse) |
| `ready` | Continue normal requirement checks |

Reason examples: `Dependency not ready: txt2img is partial`, `Dependency blocked: reference_lock is blocked`.

## Runtime integration

Capability awareness is integrated into:

- `core/runtime/registry_loader.py` (`bundle.capabilities`)
- `core/runtime/capability_manager.py`
- `core/runtime/runtime_health.py` (`capabilities` health component)
- `core/scripts/runtime_report.py` (human + summary + JSON output)
- `core/scripts/validate_capabilities.py` (CLI validation)

Notebook Cell 3c includes a lightweight capability summary call.

## Generic by design

Capabilities are platform-generic.  
Use cases (including future validation projects) consume capabilities but do not define core capability logic.

## Future extensibility

Future engines and runtimes can map into capabilities without changing the abstraction:

- Flux
- SDXL
- Forge
- Fooocus
- InvokeAI
- Kohya
- Local inference hosts
- Docker runtimes
- Cloud inference backends

Implementation is deferred; registry/model is ready.
