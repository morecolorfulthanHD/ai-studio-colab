#!/usr/bin/env python3
"""Read-only mask image diagnostics for inpainting workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SUPPORTED_CHANNELS = frozenset({"red", "green", "blue", "alpha", "luminance"})
MASK_CLASSIFICATIONS = frozenset({"all_black", "all_white", "partially_masked"})


COMFY_LOAD_IMAGE_ALPHA_NOTE = (
    "ComfyUI LoadImage MASK is derived as approximately 1 - alpha/255; "
    "transparent pixels (alpha=0) are inpainted, opaque pixels (alpha=255) are preserved."
)


@dataclass
class MaskDiagnosticReport:
    path: str
    filename: str
    dimensions: tuple[int, int]
    mode: str
    channel: str
    min_value: int
    max_value: int
    mean_value: float
    nonzero_pixel_count: int
    zero_pixel_count: int
    masked_percent: float
    bounding_box: tuple[int, int, int, int] | None
    classification: str
    inverted_relative_to: str | None = None
    comparison_path: str | None = None
    alpha_interpretation: str | None = None
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["dimensions"] = {"width": self.dimensions[0], "height": self.dimensions[1]}
        if self.bounding_box is not None:
            payload["bounding_box"] = {
                "x1": self.bounding_box[0],
                "y1": self.bounding_box[1],
                "x2": self.bounding_box[2],
                "y2": self.bounding_box[3],
            }
        return payload


from .png_utils import decode_png


def _load_image_array(path: Path) -> tuple[Any, str]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.copy(), image.mode
    except ImportError:
        (_, _), mode, rows = decode_png(path)
        return rows, mode


def _extract_channel(image: Any, channel: str) -> list[list[int]]:
    if isinstance(image, list):
        values: list[list[int]] = []
        for row in image:
            channel_row: list[int] = []
            for red, green, blue, alpha in row:
                if channel == "red":
                    channel_row.append(red)
                elif channel == "green":
                    channel_row.append(green)
                elif channel == "blue":
                    channel_row.append(blue)
                elif channel == "alpha":
                    channel_row.append(alpha)
                elif channel == "luminance":
                    channel_row.append(int(0.299 * red + 0.587 * green + 0.114 * blue))
                else:
                    raise ValueError(f"Unsupported channel: {channel}")
            values.append(channel_row)
        return values

    rgb = image.convert("RGBA")
    width, height = rgb.size
    pixels = rgb.load()
    values: list[list[int]] = []
    for y in range(height):
        row: list[int] = []
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if channel == "red":
                row.append(red)
            elif channel == "green":
                row.append(green)
            elif channel == "blue":
                row.append(blue)
            elif channel == "alpha":
                row.append(alpha)
            elif channel == "luminance":
                row.append(int(0.299 * red + 0.587 * green + 0.114 * blue))
            else:
                raise ValueError(f"Unsupported channel: {channel}")
        values.append(row)
    return values


def _bounding_box(values: list[list[int]]) -> tuple[int, int, int, int] | None:
    height = len(values)
    if height == 0:
        return None
    width = len(values[0])
    min_x = width
    min_y = height
    max_x = -1
    max_y = -1
    found = False
    for y, row in enumerate(values):
        for x, value in enumerate(row):
            if value > 0:
                found = True
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if not found:
        return None
    return min_x, min_y, max_x, max_y


def _classify_mask(nonzero_count: int, total_pixels: int) -> str:
    if nonzero_count == 0:
        return "all_black"
    if nonzero_count == total_pixels:
        return "all_white"
    return "partially_masked"


def _is_inverted(values: list[list[int]], comparison_values: list[list[int]]) -> bool:
    if len(values) != len(comparison_values):
        return False
    if not values:
        return False
    if len(values[0]) != len(comparison_values[0]):
        return False
    tolerance = 1
    for row, comparison_row in zip(values, comparison_values):
        for value, comparison_value in zip(row, comparison_row):
            if abs(value - (255 - comparison_value)) > tolerance:
                return False
    return True


def analyze_mask(
    mask_path: Path,
    *,
    channel: str = "red",
    comparison_path: Path | None = None,
    interpret_alpha_as_comfy_mask: bool = True,
) -> MaskDiagnosticReport:
    channel_name = channel.lower()
    if channel_name not in SUPPORTED_CHANNELS:
        raise ValueError(f"Unsupported channel {channel!r}; expected one of {sorted(SUPPORTED_CHANNELS)}")

    report = MaskDiagnosticReport(
        path=str(mask_path),
        filename=mask_path.name,
        dimensions=(0, 0),
        mode="unknown",
        channel=channel_name,
        min_value=0,
        max_value=0,
        mean_value=0.0,
        nonzero_pixel_count=0,
        zero_pixel_count=0,
        masked_percent=0.0,
        bounding_box=None,
        classification="all_black",
    )

    if not mask_path.is_file():
        report.errors.append(f"Mask file not found: {mask_path}")
        return report

    try:
        image, mode = _load_image_array(mask_path)
    except (OSError, RuntimeError) as exc:
        report.errors.append(str(exc))
        return report

    values = _extract_channel(image, channel_name)
    if channel_name == "alpha" and interpret_alpha_as_comfy_mask:
        # ComfyUI LoadImage: mask ≈ 1 - alpha/255 → transparent = inpaint region.
        values = [[255 - value for value in row] for row in values]
        report.alpha_interpretation = "comfyui_load_image_mask_inverted_alpha"
        report.notes.append(COMFY_LOAD_IMAGE_ALPHA_NOTE)

    flat = [value for row in values for value in row]
    total_pixels = len(flat)
    if total_pixels == 0:
        report.errors.append("Mask image contains no pixels.")
        return report

    nonzero = sum(1 for value in flat if value > 0)
    zero = total_pixels - nonzero
    report.dimensions = (len(values[0]), len(values))
    report.mode = mode
    report.min_value = min(flat)
    report.max_value = max(flat)
    report.mean_value = sum(flat) / total_pixels
    report.nonzero_pixel_count = nonzero
    report.zero_pixel_count = zero
    report.masked_percent = round((nonzero / total_pixels) * 100.0, 2)
    report.bounding_box = _bounding_box(values)
    report.classification = _classify_mask(nonzero, total_pixels)

    if comparison_path is not None:
        report.comparison_path = str(comparison_path)
        try:
            comparison_image, _ = _load_image_array(comparison_path)
            comparison_values = _extract_channel(comparison_image, channel_name)
            if channel_name == "alpha" and interpret_alpha_as_comfy_mask:
                comparison_values = [[255 - value for value in row] for row in comparison_values]
            if _is_inverted(values, comparison_values):
                report.inverted_relative_to = "inverted"
            else:
                report.inverted_relative_to = "not_inverted"
        except (OSError, RuntimeError) as exc:
            report.errors.append(f"Comparison mask error: {exc}")

    return report


def format_mask_summary(report: MaskDiagnosticReport) -> str:
    lines = [
        f"Mask: {report.filename}",
        f"Dimensions: {report.dimensions[0]}x{report.dimensions[1]}",
        f"Mode: {report.mode}",
        f"Channel: {report.channel}",
        f"Min: {report.min_value}",
        f"Max: {report.max_value}",
        f"Mean: {report.mean_value:.2f}",
        f"Masked pixels: {report.nonzero_pixel_count}",
        f"Zero pixels: {report.zero_pixel_count}",
        f"Masked percent: {report.masked_percent:.2f}%",
    ]
    if report.bounding_box is None:
        lines.append("Bounding box: none")
    else:
        x1, y1, x2, y2 = report.bounding_box
        lines.append(f"Bounding box: {x1},{y1},{x2},{y2}")
    lines.append(f"Classification: {report.classification}")
    if report.alpha_interpretation is not None:
        lines.append(f"Alpha interpretation: {report.alpha_interpretation}")
    if report.inverted_relative_to is not None:
        lines.append(f"Inverted relative to comparison: {report.inverted_relative_to}")
    for note in report.notes:
        lines.append(f"Note: {note}")
    for error in report.errors:
        lines.append(f"Error: {error}")
    return "\n".join(lines)
