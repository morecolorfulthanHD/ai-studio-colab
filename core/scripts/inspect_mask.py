#!/usr/bin/env python3
"""Inspect mask images for inpainting diagnostics (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.mask_diagnostics import analyze_mask, format_mask_summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect a mask image for inpainting diagnostics. "
            "Use --channel alpha on an RGBA source to inspect the embedded ComfyUI LoadImage MASK "
            "(transparent pixels are treated as the inpaint region)."
        )
    )
    parser.add_argument("--mask", required=True, type=Path, help="Path to mask image.")
    parser.add_argument(
        "--channel",
        default="red",
        choices=["red", "green", "blue", "alpha", "luminance"],
        help="Channel to analyze (default: red).",
    )
    parser.add_argument("--comparison", type=Path, default=None, help="Optional comparison mask.")
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary.")
    parser.add_argument("--json", action="store_true", help="Print structured JSON.")
    args = parser.parse_args()

    try:
        report = analyze_mask(
            args.mask.resolve(),
            channel=args.channel,
            comparison_path=args.comparison.resolve() if args.comparison else None,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    elif args.summary or not args.json:
        print("AI Studio — Mask Inspection")
        print("=" * 40)
        print(format_mask_summary(report))

    if report.errors:
        print("\nRESULT: FAIL — mask inspection reported errors.", file=sys.stderr)
        return 1

    print("\nRESULT: OK — mask inspection complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
