#!/usr/bin/env python3
"""Synthetic inpainting diagnostic fixture generation."""

from __future__ import annotations

from pathlib import Path

from .png_utils import write_rgb_png, write_rgba_png

CANVAS_WIDTH = 512
CANVAS_HEIGHT = 512
BACKGROUND = (200, 200, 200)
RED_SQUARE = {"color": (220, 40, 40), "box": (96, 96, 192, 192)}
BLUE_SQUARE = {"color": (40, 80, 220), "box": (288, 96, 384, 192)}
GREEN_CIRCLE = {"color": (40, 180, 80), "center": (256, 352), "radius": 56}

# ComfyUI LoadImage MASK ≈ 1 - alpha/255:
# transparent (alpha=0) regions are inpainted; opaque (alpha=255) regions are preserved.
COMFY_ALPHA_INPAINT = 0
COMFY_ALPHA_PRESERVE = 255


def _inside_box(x: int, y: int, box: tuple[int, int, int, int]) -> bool:
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def _inside_circle(x: int, y: int, center: tuple[int, int], radius: int) -> bool:
    cx, cy = center
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def _source_color(x: int, y: int) -> tuple[int, int, int]:
    color = BACKGROUND
    if _inside_box(x, y, RED_SQUARE["box"]):
        color = RED_SQUARE["color"]
    elif _inside_box(x, y, BLUE_SQUARE["box"]):
        color = BLUE_SQUARE["color"]
    elif _inside_circle(x, y, GREEN_CIRCLE["center"], GREEN_CIRCLE["radius"]):
        color = GREEN_CIRCLE["color"]
    return color


def _draw_fixture_source(path: Path) -> None:
    rows: list[list[tuple[int, int, int]]] = []
    for y in range(CANVAS_HEIGHT):
        row: list[tuple[int, int, int]] = []
        for x in range(CANVAS_WIDTH):
            row.append(_source_color(x, y))
        rows.append(row)
    write_rgb_png(path, CANVAS_WIDTH, CANVAS_HEIGHT, rows)


def _draw_mask(path: Path, *, inverted: bool = False) -> None:
    rows: list[list[tuple[int, int, int]]] = []
    for y in range(CANVAS_HEIGHT):
        row: list[tuple[int, int, int]] = []
        for x in range(CANVAS_WIDTH):
            inside = _inside_box(x, y, RED_SQUARE["box"])
            value = 255 if inside else 0
            if inverted:
                value = 255 - value
            row.append((value, value, value))
        rows.append(row)
    write_rgb_png(path, CANVAS_WIDTH, CANVAS_HEIGHT, rows)


def _draw_rgba_source_with_alpha_mask(path: Path) -> None:
    """RGBA source where alpha=0 covers only the red square (ComfyUI inpaint region)."""
    rows: list[list[tuple[int, int, int, int]]] = []
    for y in range(CANVAS_HEIGHT):
        row: list[tuple[int, int, int, int]] = []
        for x in range(CANVAS_WIDTH):
            red, green, blue = _source_color(x, y)
            alpha = COMFY_ALPHA_INPAINT if _inside_box(x, y, RED_SQUARE["box"]) else COMFY_ALPHA_PRESERVE
            row.append((red, green, blue, alpha))
        rows.append(row)
    write_rgba_png(path, CANVAS_WIDTH, CANVAS_HEIGHT, rows)


def create_fixture_bundle(output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = output_dir / "diagnostic_source.png"
    mask_path = output_dir / "diagnostic_mask_red_square.png"
    inverted_mask_path = output_dir / "diagnostic_mask_inverted.png"
    rgba_path = output_dir / "diagnostic_source_rgba.png"
    _draw_fixture_source(source_path)
    _draw_mask(mask_path, inverted=False)
    _draw_mask(inverted_mask_path, inverted=True)
    _draw_rgba_source_with_alpha_mask(rgba_path)
    return {
        "source": str(source_path),
        "mask": str(mask_path),
        "inverted_mask": str(inverted_mask_path),
        "source_rgba": str(rgba_path),
    }
