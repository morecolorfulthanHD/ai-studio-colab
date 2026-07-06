# Extraction Workflows

Generate control maps and structural guides from source images. Output maps feed into `controlnet/` workflows.

**Status:** Not yet implemented (Phase 2)

| Workflow | Output Map |
|----------|-----------|
| [depth_map/](depth_map/) | Grayscale depth image |
| [normal_map/](normal_map/) | RGB normal map |
| [segmentation_map/](segmentation_map/) | Color-coded segmentation |
| [pose_map/](pose_map/) | OpenPose skeleton render |

## Required Nodes

- ControlNet Aux preprocessors
- ComfyUI Impact Pack (segmentation)

## Pattern

```
source_image.png → extraction/<type>/ → control_map.png → controlnet/<type>/
```
