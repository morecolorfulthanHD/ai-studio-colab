#!/usr/bin/env python3
"""Plan ComfyUI custom node installs from node_registry.json (no installs yet)."""

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


@dataclass
class InstallStep:
    action: str
    name: str
    target_path: str
    source: str
    status: str
    notes: str = ""


def _node_folder(entry: dict) -> str:
    return entry.get("folder_name") or entry["name"]


def _inspect_node(path: Path) -> str:
    if not path.is_dir():
        return "missing"
    if (path / ".git").is_dir():
        return "installed"
    return "present"


def build_node_install_plan(bundle: RegistryBundle) -> list[InstallStep]:
    custom_nodes = bundle.path("comfyui_runtime") / "custom_nodes"
    steps: list[InstallStep] = []

    for entry in bundle.nodes:
        name = entry["name"]
        folder = _node_folder(entry)
        target = custom_nodes / folder
        state = _inspect_node(target)
        repo_url = entry.get("repo_url", "")

        if state == "installed":
            steps.append(
                InstallStep(
                    action="skip",
                    name=name,
                    target_path=str(target),
                    source=repo_url,
                    status="installed",
                    notes="Git clone already present.",
                )
            )
        elif state == "present":
            steps.append(
                InstallStep(
                    action="verify",
                    name=name,
                    target_path=str(target),
                    source=repo_url,
                    status="present",
                    notes="Directory exists; verify git remote and version.",
                )
            )
        else:
            steps.append(
                InstallStep(
                    action="git_clone",
                    name=name,
                    target_path=str(target),
                    source=repo_url,
                    status="missing",
                    notes=entry.get("notes", ""),
                )
            )
            steps.append(
                InstallStep(
                    action="pip_requirements",
                    name=name,
                    target_path=str(target / "requirements.txt"),
                    source=str(target),
                    status="planned",
                    notes="Install requirements.txt if present after clone.",
                )
            )

    return steps


def print_plan(steps: list[InstallStep], dry_run: bool) -> None:
    print("AI Studio — ComfyUI Node Install Plan")
    print("=" * 40)
    print(f"Mode: {'dry-run' if dry_run else 'plan-only (execution not implemented)'}\n")
    for step in steps:
        print(f"  [{step.action:16}] {step.name}")
        print(f"    target: {step.target_path}")
        print(f"    source: {step.source}")
        print(f"    status: {step.status}")
        if step.notes:
            print(f"    notes:  {step.notes}")
    print(f"\nTotal steps: {len(steps)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan ComfyUI node installs from registry.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print plan only (default behavior).")
    parser.add_argument("--json", action="store_true", help="Output plan as JSON.")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
        bundle = RegistryLoader(repo_root).load_all()
        steps = build_node_install_plan(bundle)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([asdict(s) for s in steps], indent=2))
    else:
        print_plan(steps, dry_run=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
