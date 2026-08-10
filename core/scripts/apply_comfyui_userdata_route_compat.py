#!/usr/bin/env python3
"""Apply or inspect ComfyUI userdata multi-segment route compatibility (Package 4.8.4)."""

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

from core.runtime.comfyui_userdata_route_compat import (
    apply_userdata_route_compat,
    explain_colab_proxy_failure,
    inspect_userdata_route_patterns,
    remove_userdata_route_compat,
    simulate_proxy_decoded_userdata_paths,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Apply reversible ComfyUI userdata {file:.*} route compat for Colab proxy. "
            "Does not change workflow serialization. Restart ComfyUI after apply."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--comfyui-runtime", type=Path, default=None)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.explain and not (args.inspect or args.apply or args.remove):
        payload = {
            "explanation": explain_colab_proxy_failure(),
            "path_forms": simulate_proxy_decoded_userdata_paths(),
        }
        print(json.dumps(payload, indent=2) if args.json else json.dumps(payload, indent=2))
        return 0

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    runtime = Path(args.comfyui_runtime or bundle.path("comfyui_runtime"))

    if args.remove:
        result = remove_userdata_route_compat(runtime, dry_run=args.dry_run)
    elif args.apply:
        result = apply_userdata_route_compat(runtime, dry_run=args.dry_run)
    else:
        # Default: inspect (+ optional explain).
        inspection = inspect_userdata_route_patterns(runtime)
        payload = {
            "inspection": inspection,
            "explanation": explain_colab_proxy_failure() if args.explain else None,
            "path_forms": simulate_proxy_decoded_userdata_paths(),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("AI Studio — ComfyUI Userdata Route Compat")
            print("=" * 40)
            for key, value in inspection.items():
                print(f"{key}: {value}")
            print("path_forms:", json.dumps(payload["path_forms"], indent=2))
        return 0 if inspection.get("available") else 1

    payload = result.to_dict()
    if args.explain:
        payload["explanation"] = explain_colab_proxy_failure()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — ComfyUI Userdata Route Compat")
        print("=" * 40)
        for key in (
            "comfyui_runtime",
            "user_manager_path",
            "available",
            "already_compatible",
            "applied",
            "changed",
            "dry_run",
            "replacements",
            "active",
        ):
            print(f"{key}: {payload.get(key)}")
        for message in result.messages:
            print(f"Note: {message}")
        for error in result.errors:
            print(f"Error: {error}", file=sys.stderr)
        if result.applied and not args.dry_run:
            print("Restart ComfyUI so the patched routes are loaded.")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
