#!/usr/bin/env python3
"""Plan or validate model placement from model_registry.json (no downloads)."""

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
    required: bool = False


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
        required = name == "sd15_checkpoint" or "base_txt2img" in entry.get("required_for", [])
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
                    required=required,
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
                    required=required,
                )
            )
        else:
            primary = runtime or intended
            steps.append(
                InstallStep(
                    action="validate_missing",
                    name=name,
                    target_path=str(primary),
                    registry_status=registry_status,
                    status="missing",
                    notes=entry.get("notes", "Missing model. Downloads intentionally disabled in this package."),
                    required=required,
                )
            )

    return steps


def print_plan(steps: list[InstallStep], dry_run: bool) -> None:
    print("AI Studio — Model Install Plan")
    print("=" * 40)
    print(f"Mode: {'dry-run' if dry_run else 'execute validation'} (downloads disabled)\n")
    for step in steps:
        print(f"  [{step.action:18}] {step.name} ({step.status})")
        print(f"    target: {step.target_path}")
        print(f"    registry_status: {step.registry_status}")
        print(f"    required: {step.required}")
        if step.notes:
            print(f"    notes:  {step.notes}")
    print(f"\nTotal steps: {len(steps)}")


def execute_validation(steps: list[InstallStep], dry_run: bool) -> tuple[int, int, int]:
    present = 0
    warnings = 0
    failures = 0
    print("\nModel validation")
    print("=" * 40)
    for step in steps:
        if step.status == "present":
            present += 1
            print(f"[OK] {step.name}")
            continue
        if step.status == "partial":
            warnings += 1
            print(f"[WARN] {step.name} partial presence")
            continue

        if step.required:
            failures += 1
            print(f"[FAIL] {step.name} missing (required for base generation)")
        else:
            warnings += 1
            print(f"[WARN] {step.name} missing (planned/advanced)")
        if dry_run:
            print("       dry-run: download/copy intentionally skipped")
    return present, warnings, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan model installs from registry.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print plan only (default).")
    parser.add_argument("--execute", action="store_true", help="Execute validation pass (no downloads).")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
        bundle = RegistryLoader(repo_root).load_all()
        steps = build_model_install_plan(bundle)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    dry_run = not args.execute or args.dry_run

    if args.json:
        print(json.dumps([asdict(s) for s in steps], indent=2))
    else:
        print_plan(steps, dry_run=dry_run)
        present, warnings, failures = execute_validation(steps, dry_run=dry_run)
        print("\nModel summary")
        print("=" * 40)
        print(f"Present:  {present}")
        print(f"Warnings: {warnings}")
        print(f"Failures: {failures}")
        if failures > 0 and not dry_run:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
