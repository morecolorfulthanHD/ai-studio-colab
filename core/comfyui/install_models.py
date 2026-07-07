#!/usr/bin/env python3
"""Plan model placement/downloads from model_registry.json (no downloads yet)."""

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
    registry_status: str
    status: str
    notes: str = ""


def _exists(path: Path) -> bool:
    if path.is_file():
        return True
    if path.is_dir():
        try:
            return any(path.iterdir())
        except OSError:
            return False
    return False


def build_model_install_plan(bundle: RegistryBundle) -> list[InstallStep]:
    steps: list[InstallStep] = []

    for entry in bundle.models:
        name = entry["name"]
        registry_status = entry.get("status", "planned")
        intended = bundle.repo_root / entry.get("intended_path", "")
        runtime = Path(entry["runtime_path"]) if entry.get("runtime_path") else None

        targets = [("repo", intended)]
        if runtime:
            targets.append(("runtime", runtime))

        all_present = all(_exists(p) for _, p in targets if str(p))
        any_present = any(_exists(p) for _, p in targets if str(p))

        if all_present and targets:
            steps.append(
                InstallStep(
                    action="skip",
                    name=name,
                    target_path=str(runtime or intended),
                    registry_status=registry_status,
                    status="present",
                    notes="All configured paths satisfied.",
                )
            )
        elif any_present:
            steps.append(
                InstallStep(
                    action="verify",
                    name=name,
                    target_path=str(runtime or intended),
                    registry_status=registry_status,
                    status="partial",
                    notes="Present in some paths; verify consistency.",
                )
            )
        else:
            primary = runtime or intended
            steps.append(
                InstallStep(
                    action="download_or_copy",
                    name=name,
                    target_path=str(primary),
                    registry_status=registry_status,
                    status="missing",
                    notes=entry.get("notes", "Download logic deferred to future package."),
                )
            )

    return steps


def print_plan(steps: list[InstallStep]) -> None:
    print("AI Studio — Model Install Plan")
    print("=" * 40)
    print("Mode: dry-run / plan-only (downloads not implemented)\n")
    for step in steps:
        print(f"  [{step.action:18}] {step.name} ({step.status})")
        print(f"    target: {step.target_path}")
        print(f"    registry_status: {step.registry_status}")
        if step.notes:
            print(f"    notes:  {step.notes}")
    print(f"\nTotal steps: {len(steps)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan model installs from registry.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print plan only (default).")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
        bundle = RegistryLoader(repo_root).load_all()
        steps = build_model_install_plan(bundle)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([asdict(s) for s in steps], indent=2))
    else:
        print_plan(steps)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
