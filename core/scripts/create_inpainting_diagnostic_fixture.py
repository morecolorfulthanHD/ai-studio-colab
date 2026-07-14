#!/usr/bin/env python3
"""Create synthetic inpainting diagnostic fixtures in a runtime directory."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.diagnostic_fixtures import RED_SQUARE, create_fixture_bundle
from core.runtime.mask_diagnostics import analyze_mask, format_mask_summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate synthetic inpainting diagnostic fixtures in a runtime directory."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory. Defaults to a temporary runtime directory.",
    )
    parser.add_argument("--json", action="store_true", help="Print structured JSON.")
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary.")
    args = parser.parse_args()

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.output_dir is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="ai_studio_inpaint_diag_")
        output_dir = Path(temp_dir.name)
    else:
        output_dir = args.output_dir.resolve()

    try:
        paths = create_fixture_bundle(output_dir)
        mask_report = analyze_mask(Path(paths["mask"]), channel="red")
        inverted_report = analyze_mask(
            Path(paths["inverted_mask"]),
            channel="red",
            comparison_path=Path(paths["mask"]),
        )
        alpha_report = analyze_mask(Path(paths["source_rgba"]), channel="alpha")
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = {
        "output_dir": str(output_dir),
        "paths": paths,
        "mask_report": mask_report.to_dict(),
        "inverted_mask_report": inverted_report.to_dict(),
        "rgba_alpha_report": alpha_report.to_dict(),
        "comfy_alpha_convention": (
            "LoadImage MASK ~= 1 - alpha/255; transparent (alpha=0) is inpainted; "
            "opaque (alpha=255) is preserved."
        ),
        "red_square_box": RED_SQUARE["box"],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — Inpainting Diagnostic Fixture")
        print("=" * 40)
        print(f"Output dir: {output_dir}")
        for label, value in paths.items():
            print(f"{label}: {value}")
        print("\nMask report (separate grayscale/red):")
        print(format_mask_summary(mask_report))
        print("\nInverted mask report:")
        print(format_mask_summary(inverted_report))
        print("\nRGBA embedded alpha (ComfyUI LoadImage MASK semantics):")
        print(format_mask_summary(alpha_report))
        print("\nNote: ComfyUI LoadImage MASK ~= 1 - alpha/255.")
        print("      Transparent pixels (alpha=0) are inpainted; opaque are preserved.")

    if temp_dir is not None:
        print("\nNote: fixtures were written to a temporary runtime directory.")

    print("\nRESULT: OK — diagnostic fixture generation complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
