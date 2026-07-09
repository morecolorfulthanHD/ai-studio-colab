#!/usr/bin/env python3
"""Plan or execute ComfyUI custom node installs from node_registry.json."""

from __future__ import annotations

import argparse
import json
import subprocess
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
    required: bool = False


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
        required_for = entry.get("required_for", [])
        required = "all" in required_for or entry.get("install_mode") == "required"

        if state == "installed":
            steps.append(
                InstallStep(
                    action="skip",
                    name=name,
                    target_path=str(target),
                    source=repo_url,
                    status="installed",
                    notes="Git clone already present.",
                    required=required,
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
                    required=required,
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
                    required=required,
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
                    required=required,
                )
            )

    return steps


def print_plan(steps: list[InstallStep], dry_run: bool) -> None:
    print("AI Studio — ComfyUI Node Install Plan")
    print("=" * 40)
    print(f"Mode: {'dry-run' if dry_run else 'execute'}\n")
    for step in steps:
        print(f"  [{step.action:16}] {step.name}")
        print(f"    target: {step.target_path}")
        print(f"    source: {step.source}")
        print(f"    status: {step.status}")
        print(f"    required: {step.required}")
        if step.notes:
            print(f"    notes:  {step.notes}")
    print(f"\nTotal steps: {len(steps)}")


def _run(command: list[str], dry_run: bool) -> None:
    if dry_run:
        print(f"DRY-RUN: {' '.join(command)}")
        return
    subprocess.run(command, check=True)


def execute_plan(steps: list[InstallStep], dry_run: bool) -> tuple[int, int, int]:
    installed = 0
    skipped = 0
    failed = 0
    requirements_installed_for: set[str] = set()

    print("\nExecution")
    print("=" * 40)
    for step in steps:
        target = Path(step.target_path)
        print(f"[{step.action}] {step.name}")
        try:
            if step.action == "skip":
                skipped += 1
                print("  status: skipped (already installed)")
                continue

            if step.action == "verify":
                skipped += 1
                print("  status: skipped (manual verification suggested)")
                continue

            if step.action == "git_clone":
                if target.exists():
                    skipped += 1
                    print("  status: skipped (target already exists)")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                _run(["git", "clone", step.source, str(target)], dry_run=dry_run)
                installed += 1
                print("  status: cloned")
                continue

            if step.action == "pip_requirements":
                node_root = target.parent
                req = target
                if not req.exists():
                    skipped += 1
                    print("  status: skipped (requirements.txt not present)")
                    continue
                if node_root.name in requirements_installed_for:
                    skipped += 1
                    print("  status: skipped (already processed)")
                    continue
                _run([sys.executable, "-m", "pip", "install", "-r", str(req)], dry_run=dry_run)
                requirements_installed_for.add(node_root.name)
                installed += 1
                print("  status: requirements installed")
                continue
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  status: failed ({exc})")
            if step.required:
                raise RuntimeError(f"Required node step failed for {step.name}") from exc
            print("  note: optional node step failure tolerated")

    return installed, skipped, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan ComfyUI node installs from registry.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print/execute in dry-run mode (default).")
    parser.add_argument("--execute", action="store_true", help="Execute clone/install steps.")
    parser.add_argument("--json", action="store_true", help="Output plan as JSON.")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
        bundle = RegistryLoader(repo_root).load_all()
        steps = build_node_install_plan(bundle)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    dry_run = not args.execute or args.dry_run

    if args.json:
        print(json.dumps([asdict(s) for s in steps], indent=2))
        return 0

    print_plan(steps, dry_run=dry_run)
    try:
        installed, skipped, failed = execute_plan(steps, dry_run=dry_run)
    except RuntimeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    print("\nNode install summary")
    print("=" * 40)
    print(f"Installed actions: {installed}")
    print(f"Skipped actions:   {skipped}")
    print(f"Failed actions:    {failed}")

    if failed > 0:
        print("\nRESULT: WARN — one or more optional node steps failed.", file=sys.stderr)
        return 0

    print("\nRESULT: OK — node install/validation complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
