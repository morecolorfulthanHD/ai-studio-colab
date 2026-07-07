#!/usr/bin/env python3
"""Plan Automatic1111 runtime install (no installs yet)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.runtime.registry_loader import RegistryBundle, RegistryLoader, find_repo_root

DEFAULT_A1111_REPO = "https://github.com/AUTOMATIC1111/stable-diffusion-webui.git"


@dataclass
class InstallStep:
    action: str
    target_path: str
    source: str
    status: str
    notes: str = ""


def build_install_plan(bundle: RegistryBundle) -> dict:
    a1111_dir = bundle.path("a1111_runtime")
    shared_models = bundle.path("drive_models")
    steps: list[InstallStep] = []

    if (a1111_dir / ".git").is_dir():
        steps.append(
            InstallStep(
                action="skip",
                target_path=str(a1111_dir),
                source=DEFAULT_A1111_REPO,
                status="installed",
                notes="A1111 git clone already present.",
            )
        )
    else:
        steps.append(
            InstallStep(
                action="git_clone",
                target_path=str(a1111_dir),
                source=DEFAULT_A1111_REPO,
                status="missing",
                notes="Clone stable-diffusion-webui to runtime path.",
            )
        )
        steps.append(
            InstallStep(
                action="pip_bootstrap",
                target_path=str(a1111_dir / "launch.py"),
                source=str(a1111_dir),
                status="planned",
                notes="First launch installs WebUI dependencies.",
            )
        )

    symlink_map = {
        "checkpoints": shared_models / "checkpoints",
        "controlnet": shared_models / "controlnet",
        "vae": shared_models / "vae",
        "loras": shared_models / "loras",
    }
    for label, target in symlink_map.items():
        link = a1111_dir / "models" / label
        steps.append(
            InstallStep(
                action="symlink",
                target_path=str(link),
                source=str(target),
                status="planned",
                notes=f"Link A1111 models/{label} to Drive shared storage.",
            )
        )

    return {
        "engine": "a1111",
        "runtime_path": str(a1111_dir),
        "steps": [asdict(s) for s in steps],
    }


def print_plan(plan: dict) -> None:
    print("AI Studio — A1111 Install Plan")
    print("=" * 40)
    print("Mode: dry-run / plan-only (execution not implemented)\n")
    print(f"Runtime: {plan['runtime_path']}\n")
    for step in plan["steps"]:
        print(f"  [{step['action']:14}] {step['target_path']}")
        print(f"    source: {step['source']}")
        print(f"    status: {step['status']}")
        if step.get("notes"):
            print(f"    notes:  {step['notes']}")
    print(f"\nTotal steps: {len(plan['steps'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan A1111 install from registry paths.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
        bundle = RegistryLoader(repo_root).load_all()
        plan = build_install_plan(bundle)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print_plan(plan)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
