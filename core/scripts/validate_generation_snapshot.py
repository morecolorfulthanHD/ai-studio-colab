#!/usr/bin/env python3
"""Validate generation snapshot integrity."""

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

from core.runtime.generation_snapshot import global_generations_root, load_snapshot_by_id, validate_snapshot
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate AI Studio generation snapshots.")
    parser.add_argument("--generation-id", default="")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    if not args.generation_id and not args.all:
        parser.error("Specify --generation-id or --all.")

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    drive_root = bundle.path("drive_root")

    roots: list[Path] = []
    if args.generation_id:
        manifest = load_snapshot_by_id(drive_root, args.generation_id)
        if manifest is None:
            print(f"ERROR: Unknown generation ID: {args.generation_id}", file=sys.stderr)
            return 1
        roots.append(Path(str(manifest.get("snapshot_root") or "")))
    else:
        candidates = [global_generations_root(drive_root)]
        projects_root = drive_root / "projects"
        if projects_root.is_dir():
            for project_dir in projects_root.iterdir():
                gen_root = project_dir / "generations"
                if gen_root.is_dir():
                    candidates.append(gen_root)
        for base in candidates:
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir()):
                if child.is_dir():
                    roots.append(child)

    results = []
    for root in roots:
        errors = validate_snapshot(root)
        results.append({"snapshot_root": str(root), "valid": not errors, "errors": errors})

    if args.json:
        print(json.dumps(results, indent=2))
        return 0 if all(r["valid"] for r in results) else 1
    if args.summary:
        ok = sum(1 for r in results if r["valid"])
        print(f"Validated snapshots: {ok}/{len(results)} passed")
        return 0 if ok == len(results) else 1

    print("AI Studio — Snapshot Validation")
    print("=" * 40)
    exit_code = 0
    for row in results:
        status = "PASS" if row["valid"] else "FAIL"
        print(f"[{status}] {row['snapshot_root']}")
        for error in row["errors"]:
            print(f"  - {error}")
        if not row["valid"]:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
