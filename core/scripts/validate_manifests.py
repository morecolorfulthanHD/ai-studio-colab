#!/usr/bin/env python3
"""Validate JSON manifest files under configs/."""

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

from core.runtime.registry_loader import find_repo_root



MANIFEST_RULES: dict[str, dict] = {
    "paths/colab_paths.json": {
        "required_keys": {"version", "environment", "paths"},
        "paths_keys": {
            "drive_root",
            "comfyui_runtime",
            "a1111_runtime",
            "comfyui_output",
            "drive_outputs",
            "drive_inputs",
            "drive_models",
            "drive_workflows",
            "runtime_workflows",
        },
    },
    "models/model_registry.json": {
        "required_keys": {"version", "models"},
        "entry_keys": {"name", "category", "intended_path", "required_for", "status", "notes"},
        "list_key": "models",
        "optional_entry_keys": {"runtime_path"},
    },
    "nodes/node_registry.json": {
        "required_keys": {"version", "nodes"},
        "entry_keys": {"name", "repo_url", "category", "required_for", "install_mode", "notes"},
        "list_key": "nodes",
        "optional_entry_keys": {"folder_name"},
    },
    "presets/default_generation_presets.json": {
        "required_keys": {"version", "presets"},
        "entry_keys": {
            "name",
            "checkpoint",
            "width",
            "height",
            "steps",
            "cfg",
            "sampler",
            "scheduler",
            "notes",
        },
        "list_key": "presets",
        "optional_entry_keys": {"denoise"},
    },
    "workflows/workflow_registry.json": {
        "required_keys": {"version", "workflows"},
        "entry_keys": {"id", "category", "path", "status", "required_models", "required_nodes", "notes"},
        "list_key": "workflows",
    },
    "assets/asset_registry.json": {
        "required_keys": {"version", "assets"},
        "entry_keys": {
            "id",
            "name",
            "asset_type",
            "category",
            "scope",
            "engine",
            "intended_path",
            "required_for",
            "status",
            "source_type",
            "source_url",
            "license_notes",
            "notes",
        },
        "list_key": "assets",
        "optional_entry_keys": {"runtime_path"},
    },
    "capabilities/capability_registry.json": {
        "required_keys": {"version", "capabilities"},
        "entry_keys": {
            "id",
            "name",
            "description",
            "category",
            "maturity",
            "status",
            "implementation_status",
            "supported_engines",
            "required_models",
            "required_nodes",
            "required_assets",
            "required_workflows",
            "dependencies",
            "validation_rules",
            "notes",
        },
        "list_key": "capabilities",
    },
}


def validate_manifest(rel_path: str, data: object) -> list[str]:
    rules = MANIFEST_RULES.get(rel_path)
    if rules is None:
        return []

    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{rel_path}: root must be a JSON object"]

    missing_top = rules["required_keys"] - set(data.keys())
    if missing_top:
        errors.append(f"{rel_path}: missing top-level keys: {sorted(missing_top)}")

    if rel_path == "paths/colab_paths.json":
        paths = data.get("paths")
        if isinstance(paths, dict):
            missing_paths = rules["paths_keys"] - set(paths.keys())
            if missing_paths:
                errors.append(f"{rel_path}: missing paths keys: {sorted(missing_paths)}")
        else:
            errors.append(f"{rel_path}: 'paths' must be an object")

    list_key = rules.get("list_key")
    entry_keys = rules.get("entry_keys")
    optional_keys = rules.get("optional_entry_keys", set())

    if list_key and entry_keys:
        entries = data.get(list_key)
        if not isinstance(entries, list):
            errors.append(f"{rel_path}: '{list_key}' must be a list")
        else:
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    errors.append(f"{rel_path}: {list_key}[{index}] must be an object")
                    continue
                missing = entry_keys - set(entry.keys())
                if missing:
                    errors.append(
                        f"{rel_path}: {list_key}[{index}] missing keys: {sorted(missing)}"
                    )
                extra_unknown = set(entry.keys()) - entry_keys - optional_keys - {"id", "name"}
                # Allow id/name alias fields without noise

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate configs/*.json manifests.")
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args()

    print("AI Studio Colab — Manifest Validation")
    print("=" * 40)

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    configs_root = repo_root / "configs"
    json_files = sorted(configs_root.rglob("*.json"))

    if not json_files:
        print("ERROR: No JSON files found under configs/", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    passed = 0

    for path in json_files:
        rel = path.relative_to(configs_root).as_posix()
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            print(f"  [FAIL] {rel}: invalid JSON — {exc}")
            all_errors.append(rel)
            continue

        errors = validate_manifest(rel, data)
        if errors:
            print(f"  [FAIL] {rel}")
            for err in errors:
                print(f"         {err}")
            all_errors.append(rel)
        else:
            print(f"  [PASS] {rel}")
            passed += 1

    print(f"\nRESULT: {passed}/{len(json_files)} manifest(s) passed.")
    if all_errors:
        print(f"Failed: {', '.join(all_errors)}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
