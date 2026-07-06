# Workflow Registry

Canonical index of platform workflows. On-disk workflow JSON files live under `workflows/`; this registry tracks metadata, dependencies, and implementation status.

**Manifest:** `workflow_registry.json`

List implemented workflow JSON files on disk:

```bash
python core/scripts/list_workflows.py
```

Workflow entries include `id`, `category`, `path`, `status`, `required_models`, `required_nodes`, and `notes`. Status is `planned` until the workflow JSON is implemented and tested.
