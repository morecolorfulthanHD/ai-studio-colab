#!/usr/bin/env python3
"""Prepare runtime workflow copies with user-selected inputs."""

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

from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_library_preparation import prepare_library_workflow
from core.runtime.workflow_manifest import resolve_workflow_identifier
from core.runtime.workflow_preparation import prepare_workflow

LEGACY_WORKFLOWS = frozenset({"img2img", "inpainting", "outpainting"})


def _parse_param(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"Invalid --param (expected key=value): {raw}")
    key, value = raw.split("=", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"Invalid --param key: {raw}")
    return key, value


def _looks_like_library_workflow(workflow: str) -> bool:
    text = workflow.strip()
    if "/" in text or text.startswith("base_") or text.startswith("reference_"):
        return True
    if text in {"txt2img", "qwen_image_edit", "flux_fill"}:
        return True
    return False


def _use_library_mode(args: argparse.Namespace) -> bool:
    if args.library:
        return True
    if args.param or args.params_json or args.params_file:
        return True
    if _looks_like_library_workflow(args.workflow):
        return True
    if args.workflow == "img2img" and not args.input:
        return False
    return False


def _load_params(args: argparse.Namespace) -> dict:
    params: dict = {}
    for raw in args.param:
        key, value = _parse_param(raw)
        params[key] = value
    if args.params_json:
        loaded = json.loads(args.params_json)
        if not isinstance(loaded, dict):
            raise ValueError("--params-json must be a JSON object")
        params.update(loaded)
    if args.params_file:
        loaded = json.loads(Path(args.params_file).read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("--params-file must contain a JSON object")
        params.update(loaded)
    return params


def _run_legacy(args: argparse.Namespace, repo_root: Path) -> int:
    if not args.input:
        print("ERROR: Legacy mode requires --input.", file=sys.stderr)
        return 1
    bundle = RegistryLoader(repo_root).load_all()
    runtime_dir = args.runtime_dir or bundle.path("runtime_workflows")
    comfyui_input_dir = args.comfyui_input_dir or (bundle.path("comfyui_runtime") / "input")
    expansion = {
        "left": args.left,
        "right": args.right,
        "top": args.top,
        "bottom": args.bottom,
    }
    result = prepare_workflow(
        repo_root,
        runtime_dir,
        comfyui_input_dir=comfyui_input_dir,
        workflow=args.workflow,
        input_path=args.input.resolve(),
        mask_path=args.mask.resolve() if args.mask else None,
        expansion=expansion if args.workflow == "outpainting" else None,
        dry_run=args.dry_run,
        diagnostics=args.inspect and args.workflow == "inpainting",
        drive_prepared_dir=bundle.path("drive_workflows") / "prepared",
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — Workflow Preparation (Legacy)")
        print("=" * 40)
        print(f"Workflow:   {result.workflow} ({result.workflow_id})")
        print(f"Canonical:  {result.canonical_path}")
        if result.prepared_path:
            print(f"Prepared workflow: {result.prepared_path}")
        for message in result.messages:
            print(f"Note: {message}")
        for error in result.errors:
            print(f"Error: {error}", file=sys.stderr)
    if not result.ok:
        print("\nRESULT: FAIL — workflow preparation failed.", file=sys.stderr)
        return 1
    print("\nRESULT: OK — workflow preparation complete.")
    return 0


def _run_library(args: argparse.Namespace, repo_root: Path) -> int:
    bundle = RegistryLoader(repo_root).load_all()
    runtime_prepared_root = args.runtime_dir or (bundle.path("runtime_root") / "prepared_workflows")
    drive_prepared_root = bundle.path("drive_workflows") / "prepared"
    comfyui_input_dir = args.comfyui_input_dir or (bundle.path("comfyui_runtime") / "input")
    drive_root = bundle.path("drive_root")
    allowed_roots = [bundle.path("drive_inputs"), repo_root / "inputs"]
    active_project = None
    if args.project:
        from core.runtime.project_workspace import ProjectWorkspace

        workspace = ProjectWorkspace(drive_root)
        active_project = workspace.get_active_project()

    params = _load_params(args)
    result = prepare_library_workflow(
        repo_root,
        workflow_identifier=args.workflow,
        parameters=params,
        runtime_prepared_root=runtime_prepared_root,
        drive_prepared_root=drive_prepared_root,
        comfyui_input_dir=comfyui_input_dir,
        drive_root=drive_root,
        active_project=active_project,
        allow_experimental=args.allow_experimental,
        allow_benchmark=args.allow_benchmark,
        dry_run=args.dry_run,
        allowed_input_roots=allowed_roots,
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    elif args.summary:
        print(
            f"{result.preparation_id} {result.workflow_identifier} "
            f"readiness={result.readiness_status} ok={result.ok}"
        )
    else:
        print("AI Studio — Workflow Preparation (Library)")
        print("=" * 40)
        print(f"Workflow:       {result.workflow_identifier} ({result.workflow_id})")
        print(f"Preparation ID: {result.preparation_id}")
        print(f"Readiness:      {result.readiness_status}")
        print(f"Prepared hash:  {result.prepared_workflow_hash}")
        if result.runtime_workflow_path:
            print(f"Runtime path:   {result.runtime_workflow_path}")
        if result.drive_prepared_dir:
            print(f"Drive path:     {result.drive_prepared_dir}")
        for message in result.messages:
            print(f"Note: {message}")
        for error in result.errors:
            print(f"Error: {error}", file=sys.stderr)
    if not result.ok:
        print("\nRESULT: FAIL — library workflow preparation failed.", file=sys.stderr)
        return 1
    print("\nRESULT: OK — library workflow preparation complete.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare runtime workflow JSON with selected inputs.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--input", type=Path, default=None, help="Persistent source image path (legacy mode).")
    parser.add_argument("--mask", type=Path, default=None, help="Persistent mask image path (legacy inpainting).")
    parser.add_argument("--left", type=int, default=0)
    parser.add_argument("--right", type=int, default=0)
    parser.add_argument("--top", type=int, default=0)
    parser.add_argument("--bottom", type=int, default=0)
    parser.add_argument("--runtime-dir", type=Path, default=None)
    parser.add_argument("--comfyui-input-dir", type=Path, default=None)
    parser.add_argument("--library", action="store_true", help="Force library preparation mode.")
    parser.add_argument("--param", action="append", default=[], help="Parameter key=value (repeatable).")
    parser.add_argument("--params-json", default="", help="JSON object of workflow parameters.")
    parser.add_argument("--params-file", type=Path, default=None, help="JSON file of workflow parameters.")
    parser.add_argument("--project", action="store_true", help="Also copy prepared workflow to active project.")
    parser.add_argument("--global", dest="use_global", action="store_true", help="Accepted for compatibility.")
    parser.add_argument("--allow-experimental", action="store_true")
    parser.add_argument("--allow-benchmark", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--inspect", action="store_true", help="Print inpainting diagnostics after preparation.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
        if _use_library_mode(args):
            resolve_workflow_identifier(args.workflow)
            return _run_library(args, repo_root)
        if args.workflow not in LEGACY_WORKFLOWS:
            print(
                f"ERROR: Unknown legacy workflow {args.workflow!r}. "
                "Use library mode with --workflow base/... or --library.",
                file=sys.stderr,
            )
            return 1
        return _run_legacy(args, repo_root)
    except (FileNotFoundError, KeyError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
