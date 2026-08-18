#!/usr/bin/env python3
"""Show details for one prepared workflow."""

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

from core.runtime.preparation_identity import InvalidPreparationIdError, normalize_preparation_id
from core.runtime.prepared_workflow_index import find_by_preparation_id, preparations_log_path
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.seed_mode import (
    extract_ksampler_seed,
    resolve_control_after_generate,
    resolve_seed_mode,
)


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _param(metadata: dict, record: dict, key: str, default: str = ""):
    parameters = metadata.get("parameters") if isinstance(metadata.get("parameters"), dict) else {}
    summary = record.get("parameter_summary") if isinstance(record.get("parameter_summary"), dict) else {}
    if key in metadata and metadata.get(key) not in (None, ""):
        return metadata.get(key)
    if key in parameters and parameters.get(key) not in (None, ""):
        return parameters.get(key)
    if key in summary and summary.get(key) not in (None, ""):
        return summary.get(key)
    return default


def main() -> int:
    parser = argparse.ArgumentParser(description="Show prepared workflow details.")
    parser.add_argument("--preparation-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    try:
        preparation_id = normalize_preparation_id(args.preparation_id)
    except InvalidPreparationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    log_path = preparations_log_path(bundle.path("drive_root"))
    record = find_by_preparation_id(log_path, preparation_id)
    if record is None:
        print(f"ERROR: Preparation not found: {preparation_id}", file=sys.stderr)
        return 1

    prepared_dir = Path(str(record.get("drive_prepared_dir") or record.get("runtime_prepared_dir") or ""))
    metadata = _load_json(prepared_dir / f"{preparation_id}.metadata.json") if prepared_dir.is_dir() else {}
    workflow_data = (
        _load_json(prepared_dir / f"{preparation_id}.workflow.json") if prepared_dir.is_dir() else {}
    )
    parameters = metadata.get("parameters") if isinstance(metadata.get("parameters"), dict) else {}
    seed_mode = resolve_seed_mode(
        parameters=parameters,
        metadata=metadata,
        index_record=record,
        workflow_data=workflow_data,
    )
    control = resolve_control_after_generate(
        parameters=parameters,
        metadata=metadata,
        index_record=record,
        workflow_data=workflow_data,
        seed_mode=seed_mode,
    )
    seed = _param(metadata, record, "seed")
    if seed in ("", None) and workflow_data:
        seed = extract_ksampler_seed(workflow_data)

    payload = {
        "index_record": record,
        "metadata": metadata,
        "seed": seed,
        "seed_mode": seed_mode,
        "control_after_generate": control,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("AI Studio — Prepared Workflow Info")
    print("=" * 40)
    print(f"Preparation ID:         {preparation_id}")
    kind = str(metadata.get("preparation_kind") or record.get("preparation_kind") or "ordinary")
    if kind == "generation_reproduction":
        print("Kind:                   generation reproduction")
    elif kind == "generation_derivation":
        print("Kind:                   generation derivation")
        print(f"Derivation type:        {metadata.get('derivation_type') or record.get('derivation_type') or '-'}")
    else:
        print(f"Kind:                   {kind}")
    print(f"Workflow:               {record.get('workflow_identifier')}")
    print(f"Project:                {record.get('project_slug') or '(global)'}")
    print(f"Readiness:              {record.get('readiness_status')}")
    if kind == "generation_reproduction":
        print(
            f"Source generation:      "
            f"{metadata.get('reproduction_source_generation_id') or record.get('source_generation_id') or '-'}"
        )
        print(f"Source prompt:          {metadata.get('reproduction_source_prompt_id') or '-'}")
        print(f"Source preparation:     {metadata.get('reproduction_source_preparation_id') or '-'}")
        print(f"Source image SHA:       {metadata.get('reproduction_source_image_sha256') or '-'}")
        scope = str(metadata.get("reproduction_scope") or record.get("reproduction_scope") or "")
        if scope == "source_batch_execution":
            print("Reproduction scope:     original batch execution")
        elif scope == "single_generation":
            print("Reproduction scope:     single generation")
        elif scope:
            print(f"Reproduction scope:     {scope}")
        if metadata.get("source_batch_size") is not None:
            print(f"Source batch size:      {metadata.get('source_batch_size')}")
        if metadata.get("source_output_index") is not None:
            print(f"Source output index:    {metadata.get('source_output_index')}")
    elif kind == "generation_derivation":
        print(
            f"Source generation:      "
            f"{metadata.get('derived_from_generation_id') or record.get('source_generation_id') or '-'}"
        )
        print(f"Source prompt:          {metadata.get('derivation_source_prompt_id') or '-'}")
        print(f"Source preparation:     {metadata.get('derivation_source_preparation_id') or '-'}")
        print(f"Source image SHA:       {metadata.get('derivation_source_image_sha256') or '-'}")
        print(f"Archived source:        {metadata.get('derivation_source_archived_path') or '-'}")
    print(f"Seed:                   {seed if seed not in (None, '') else '(unavailable)'}")
    print(f"Seed mode:              {seed_mode}")
    print(f"Control after generate: {control}")
    if args.summary:
        print(f"Prepared hash:          {record.get('prepared_workflow_hash')}")
        return 0

    print(f"Sampler:                {_param(metadata, record, 'sampler_name') or '(unavailable)'}")
    print(f"Scheduler:              {_param(metadata, record, 'scheduler') or '(unavailable)'}")
    print(f"Checkpoint:             {_param(metadata, record, 'checkpoint') or '(unavailable)'}")
    print(f"Steps:                  {_param(metadata, record, 'steps') or '(unavailable)'}")
    print(f"CFG:                    {_param(metadata, record, 'cfg') or '(unavailable)'}")
    denoise = _param(metadata, record, "denoise")
    if denoise not in (None, ""):
        print(f"Variation strength:     {denoise}")
    width = _param(metadata, record, "width")
    height = _param(metadata, record, "height")
    if width not in (None, "") or height not in (None, ""):
        print(f"Dimensions:             {width or '?'} x {height or '?'}")
    else:
        print("Dimensions:             (unavailable)")
    print(f"Batch size:             {_param(metadata, record, 'batch_size') or '(unavailable)'}")
    print(f"Save prefix:            {_param(metadata, record, 'save_prefix') or '(unavailable)'}")
    print(f"Drive/global path:      {record.get('drive_prepared_dir') or record.get('prepared_drive_path') or '(none)'}")
    project_path = record.get("project_prepared_dir") or record.get("prepared_project_path") or ""
    print(f"Project mirror path:    {project_path or '(none)'}")
    print(f"Runtime dir:            {record.get('runtime_prepared_dir') or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
