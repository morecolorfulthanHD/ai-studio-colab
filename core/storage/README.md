# Runtime Storage

Transient data used during workflow execution. Contents are gitignored.

| Subdirectory | Purpose |
|--------------|---------|
| `cache/` | Preprocessor cache, intermediate ComfyUI outputs |
| `temp/` | Short-lived files during batch runs |
| `uploads/` | Staging area for user-uploaded reference images |

For persistent generated artifacts, use `output/` at the repository root.
