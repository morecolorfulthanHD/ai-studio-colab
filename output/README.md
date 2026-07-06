# Output

Default destination for generated images, videos, control maps, and intermediate artifacts.

Contents are gitignored. Only this README is version-controlled.

## Organization (recommended)

```
output/
├── <workflow_category>/
│   └── <workflow_name>/
│       └── <timestamp>/
│           ├── image_001.png
│           └── metadata.json
```

Use-case validation outputs may alternatively go to `use_cases/<project>/test_outputs/`.
