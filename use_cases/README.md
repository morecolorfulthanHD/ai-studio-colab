# Use Cases

Project-specific datasets, prompts, and validation workflows. Use cases **consume** platform workflows from `workflows/` — they do not modify or fork them.

| Project | Purpose | Status |
|---------|---------|--------|
| [zara_morrison/](zara_morrison/) | Virtual influencer validation (first production use case) | Placeholder |

## Adding a New Use Case

1. Create `use_cases/<project_name>/` with the standard subdirectories below
2. Document which platform workflows are chained in the project README
3. Store all project-specific assets (references, prompts, test outputs) here
4. Never add project logic to `core/`, `workflows/`, or `configs/`

## Standard Layout

```
use_cases/<project>/
├── README.md
├── prompts/
├── references/
├── environments/
├── test_outputs/
└── documentation/
```
