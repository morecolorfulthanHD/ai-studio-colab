#!/usr/bin/env python3
"""Report installed vs. missing ComfyUI custom nodes from node_registry.json.

Read-only — does not install anything.
"""

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


def load_paths(repo_root: Path) -> Path:
    manifest = repo_root / "configs" / "paths" / "colab_paths.json"
    with manifest.open(encoding="utf-8") as fh:
        data = json.load(fh)
    comfyui_runtime = Path(data["paths"]["comfyui_runtime"])
    return comfyui_runtime / "custom_nodes"


def load_node_registry(repo_root: Path) -> list[dict]:
    manifest = repo_root / "configs" / "nodes" / "node_registry.json"
    with manifest.open(encoding="utf-8") as fh:
        data = json.load(fh)
    nodes = data.get("nodes", [])
    if not isinstance(nodes, list):
        raise ValueError("node_registry.json: 'nodes' must be a list")
    return nodes


def folder_name(entry: dict) -> str:
    return entry.get("folder_name") or entry["name"]


def inspect_node(path: Path) -> str:
    if not path.exists():
        return "missing"
    if not path.is_dir():
        return "invalid"
    if (path / ".git").is_dir():
        return "installed"
    return "present"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ComfyUI custom nodes against registry.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument(
        "--custom-nodes-dir",
        type=Path,
        default=None,
        help="Override custom_nodes path (default: from colab_paths.json).",
    )
    args = parser.parse_args()

    print("AI Studio Colab — Node Check")
    print("=" * 40)

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
        custom_nodes_dir = args.custom_nodes_dir or load_paths(repo_root)
        registry = load_node_registry(repo_root)
    except (FileNotFoundError, ValueError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Registry:        {repo_root / 'configs/nodes/node_registry.json'}")
    print(f"custom_nodes dir: {custom_nodes_dir}\n")

    if not custom_nodes_dir.is_dir():
        print(f"WARN: custom_nodes directory does not exist yet: {custom_nodes_dir}")
        print("      Install ComfyUI before expecting nodes.\n")

    installed = 0
    missing_required = 0
    missing_optional = 0

    for entry in registry:
        name = entry["name"]
        folder = folder_name(entry)
        node_path = custom_nodes_dir / folder
        state = inspect_node(node_path)
        install_mode = entry.get("install_mode", "planned")
        required = "all" in entry.get("required_for", []) or install_mode == "required"

        if state in {"installed", "present"}:
            installed += 1
            marker = "INSTALLED" if state == "installed" else "PRESENT"
        else:
            if required:
                missing_required += 1
            else:
                missing_optional += 1
            marker = "MISSING"

        print(f"  [{marker:9}] {name}")
        print(f"             path: {node_path}")
        print(f"             install_mode: {install_mode}")
        print(f"             required: {required}")

    print(
        f"\nSummary: {installed} installed/present, "
        f"{missing_required} required missing, "
        f"{missing_optional} optional missing (of {len(registry)} registered)"
    )

    if missing_required > 0:
        print("\nRESULT: INCOMPLETE — one or more required nodes are missing.", file=sys.stderr)
        return 1

    if missing_optional > 0:
        print("\nRESULT: WARN — optional nodes are missing.")
        return 0

    print("\nRESULT: OK — all registered nodes found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
