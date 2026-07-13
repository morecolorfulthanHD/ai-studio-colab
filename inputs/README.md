# Persistent Drive inputs

Place source images and masks here for img2img, inpainting, and outpainting workflows.

## Recommended layout

```text
/content/drive/MyDrive/AI_Studio/inputs/images/
/content/drive/MyDrive/AI_Studio/inputs/masks/
```

## Supported formats

- `.png`
- `.jpg` / `.jpeg`
- `.webp`

Use `python core/scripts/list_inputs.py` to list eligible files and exact runtime paths.

Do not commit real user images to the repository.
