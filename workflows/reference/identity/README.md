# Identity Preservation

**Status:** Not yet implemented (Phase 3, refined in Phase 5)

## Purpose

Preserve facial identity across generations using IPAdapter Face and (Phase 5) ReActor/InsightFace refinement.

## Inputs

- Face reference image(s)
- Identity strength parameter
- Prompts, ControlNet maps (optional)

## Outputs

- Identity-consistent PNG → `output/`

## Dependencies

- `reference/ipadapter/`
- Phase 5: ReActor nodes, InsightFace models

## Known Limitations

- Single reference may drift at extreme angles; multi_reference improves consistency.
