#!/usr/bin/env python3
"""Verify model files against model_registry.json.

Read-only — does not download anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ASSET_PREFIX_TO_DRIVE_SUBDIR = {
    "assets/checkpoints": "checkpoints",
    "assets/controlnets": "controlnet",
    "assets/loras": "loras",
    "assets/vaes": "vae",
    "assets/embeddings": "embeddings",
    "assets/upscalers": "upscale_models",
    "assets/ipadapter": "ipadapter",
    "assets/clip": "clip",
    "assets/insightface": "insightface",
}


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in (current, *current.parents):
        if (path / "configs" / "models" / "model_registry.json").is_file():
            return path
    raise FileNotFoundError("Could not locate repository root.")


def load_colab_paths(repo_root: Path) -> dict:
    manifest = repo_root / "configs" / "paths" / "colab_paths.json"
    with manifest.open(encoding="utf-8") as fh:
        return json.load(fh)["paths"]


def load_model_registry(repo_root: Path) -> list[dict]:
    manifest = repo_root / "configs" / "models" / "model_registry.json"
    with manifest.open(encoding="utf-8") as fh:
        data = json.load(fh)
    models = data.get("models", [])
    if not isinstance(models, list):
        raise ValueError("model_registry.json: 'models' must be a list")
    return models


def resolve_check_paths(
    entry: dict,
    repo_root: Path,
    drive_models: Path | None,
) -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []

    intended = entry.get("intended_path", "")
    if intended:
        paths.append(("repo", repo_root / intended))

    runtime = entry.get("runtime_path")
    if runtime:
        paths.append(("runtime", Path(runtime)))

    if drive_models and intended:
        intended_posix = intended.replace("\\", "/")
        for prefix, subdir in ASSET_PREFIX_TO_DRIVE_SUBDIR.items():
            if intended_posix.startswith(prefix + "/"):
                remainder = intended_posix[len(prefix) + 1 :]
                if remainder.endswith("/"):
                    paths.append(("drive", drive_models / subdir))
                else:
                    paths.append(("drive", drive_models / subdir / Path(remainder).name))
                break

    return paths


def check_entry(paths: list[tuple[str, Path]]) -> tuple[str, Path | None]:
    for _label, path in paths:
        if path.is_file():
            return "present", path
        if path.is_dir():
            try:
                if any(path.iterdir()):
                    return "present", path
            except OSError:
                pass
    return "missing", paths[0][1] if paths else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify models against model_registry.json.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument(
        "--drive-models",
        type=Path,
        default=None,
        help="Override Drive shared models root.",
    )
    parser.add_argument(
        "--require-active-only",
        action="store_true",
        help="Exit non-zero only when an 'active' model is missing.",
    )
    args = parser.parse_args()

    print("AI Studio Colab — Model Verification")
    print("=" * 40)

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
        colab_paths = load_colab_paths(repo_root)
        drive_models = args.drive_models or Path(colab_paths["drive_models"])
        registry = load_model_registry(repo_root)
    except (FileNotFoundError, ValueError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Registry:     {repo_root / 'configs/models/model_registry.json'}")
    print(f"Drive models: {drive_models}\n")

    present = 0
    missing_required = 0
    missing_optional = 0
    planned = 0
    fail = False

    for entry in registry:
        name = entry["name"]
        registry_status = entry.get("status", "planned")
        check_paths = resolve_check_paths(entry, repo_root, drive_models)
        check_status, found_path = check_entry(check_paths)

        is_required = name == "sd15_checkpoint" or "base_txt2img" in entry.get("required_for", [])

        if check_status == "present":
            present += 1
            marker = "PRESENT"
        else:
            if is_required:
                missing_required += 1
                marker = "MISSING"
                fail = True
            elif registry_status == "active":
                missing_optional += 1
                marker = "MISSING"
            else:
                planned += 1
                marker = "PLANNED"
                if registry_status == "missing":
                    marker = "MISSING"

        print(f"  [{marker:7}] {name} (registry: {registry_status}, required: {is_required})")
        if found_path:
            print(f"            checked: {found_path}")
        if check_paths:
            for label, path in check_paths:
                print(f"            {label}: {path}")

    print(f"\nSummary: {present} present, {missing_required} missing required, {missing_optional} missing optional active, {planned} planned/not required")

    if args.require_active_only:
        if fail:
            print("\nRESULT: FAIL — one or more required models are missing.", file=sys.stderr)
            return 1
        print("\nRESULT: OK — required models present.")
        return 0

    print("\nRESULT: OK — model verification complete (informational).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
