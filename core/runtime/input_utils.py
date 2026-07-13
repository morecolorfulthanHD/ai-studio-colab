#!/usr/bin/env python3
"""Helpers for Drive/runtime input discovery and validation."""

from __future__ import annotations

from pathlib import Path

ELIGIBLE_INPUT_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

PLACEHOLDER_BASENAMES = {
    "README.md",
    ".gitkeep",
}


def is_eligible_input(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        if path.stat().st_size == 0:
            return False
    except OSError:
        return False
    if path.name in PLACEHOLDER_BASENAMES:
        return False
    return path.suffix.lower() in ELIGIBLE_INPUT_SUFFIXES


def list_eligible_inputs(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        [path for path in directory.rglob("*") if is_eligible_input(path)],
        key=lambda path: path.name.lower(),
    )


def validate_input_path(path: Path) -> tuple[bool, str | None]:
    if not path.is_file():
        return False, f"Input file not found: {path}"
    if not is_eligible_input(path):
        return False, (
            f"Unsupported or invalid input file: {path.name} "
            f"(supported: {', '.join(sorted(ELIGIBLE_INPUT_SUFFIXES))})"
        )
    return True, None


def validate_matching_dimensions(
    source_path: Path,
    mask_path: Path,
) -> tuple[bool, str | None, str | None]:
    try:
        from PIL import Image
    except ImportError:
        return True, None, "Pillow not available; source/mask dimension check deferred."

    try:
        with Image.open(source_path) as source_image, Image.open(mask_path) as mask_image:
            if source_image.size != mask_image.size:
                return (
                    False,
                    (
                        f"Source and mask dimensions differ: source={source_image.size}, "
                        f"mask={mask_image.size}."
                    ),
                    None,
                )
    except OSError as exc:
        return False, f"Unable to read image dimensions: {exc}", None
    return True, None, None
