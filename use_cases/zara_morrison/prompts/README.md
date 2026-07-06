# Prompts

Zara Morrison-specific prompt templates with variable slots.

## Planned Format

```
# Example (not yet implemented)
positive: "photo of zm_character, {outfit}, {setting}, {lighting}, high quality"
negative: "blurry, deformed, extra fingers"
variables:
  outfit: references to clothing descriptions
  setting: environment names matching environments/
  lighting: golden hour | studio | neon
```

Prompts reference platform presets from `configs/presets/` for generation parameters. Prompt text lives here; generation settings do not.
