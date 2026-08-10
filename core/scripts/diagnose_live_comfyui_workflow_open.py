#!/usr/bin/env python3
"""Read-only live diagnostic for ComfyUI prepared-workflow open failures (Package 4.8.3).

Captures environment/version signals, integrity, optional known-good comparison,
and exact manual browser evidence steps.

Does not mutate workflows, userdata, settings, or runtime state.
Does not call /prompt. Does not automate the browser.
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

from core.runtime.comfyui_live_diagnostics import (
    KNOWN_GOOD_CONTROL_FILENAME,
    analyze_preparation_open,
    browser_evidence_instructions,
    capture_live_environment,
    control_test_instructions,
    round_trip_test_instructions,
)
from core.runtime.comfyui_userdata import DEFAULT_COMFY_BASE_URL
from core.runtime.comfyui_workflow_integrity import compare_workflow_structures
from core.runtime.preparation_identity import InvalidPreparationIdError, normalize_preparation_id
from core.runtime.prepared_workflow_index import find_by_preparation_id, preparations_log_path
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _print_section(title: str, lines: list[str]) -> None:
    print()
    print(title)
    print("-" * len(title))
    for line in lines:
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Package 4.8.3 live ComfyUI workflow-open diagnostic. "
            "Never claims browser canvas success."
        )
    )
    parser.add_argument("--preparation-id", default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--comfyui-runtime", type=Path, default=None)
    parser.add_argument("--comfy-url", default=DEFAULT_COMFY_BASE_URL)
    parser.add_argument(
        "--known-good-filename",
        default=KNOWN_GOOD_CONTROL_FILENAME,
        help="Frontend-saved control workflow filename under workflows/",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("KNOWN_GOOD_JSON", "CANDIDATE_JSON"),
        help="Compare two local workflow JSON files structurally (read-only).",
    )
    parser.add_argument(
        "--instructions-only",
        action="store_true",
        help="Print control/browser evidence instructions without probing ComfyUI.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.instructions_only:
        payload = {
            "browser_evidence_instructions": browser_evidence_instructions(
                "ai_studio_prep_<uuid>.json"
            ),
            "control_test_instructions": control_test_instructions(),
            "round_trip_test_instructions": round_trip_test_instructions(),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            _print_section("Browser evidence", payload["browser_evidence_instructions"])
            _print_section("Control test", payload["control_test_instructions"])
            _print_section("Round-trip test", payload["round_trip_test_instructions"])
        return 0

    if args.compare:
        known_path = Path(args.compare[0])
        cand_path = Path(args.compare[1])
        try:
            known = json.loads(known_path.read_text(encoding="utf-8"))
            cand = json.loads(cand_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        comparison = compare_workflow_structures(known, cand)
        if args.json:
            print(json.dumps(comparison, indent=2))
        else:
            print("AI Studio — Workflow Structure Comparison")
            print("=" * 40)
            print(f"Difference count: {comparison['difference_count']}")
            for item in comparison["differences"]:
                print(f"- {item['field']}: known_good={item['known_good']!r} candidate={item['candidate']!r}")
            for item in comparison["widget_differences"]:
                print(f"- widget: {item}")
            print(f"Integrity known_good: {comparison['integrity_known_good'] or 'OK'}")
            print(f"Integrity candidate: {comparison['integrity_candidate'] or 'OK'}")
        return 0

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    comfyui_runtime = Path(args.comfyui_runtime or bundle.path("comfyui_runtime"))

    if not args.preparation_id:
        payload = capture_live_environment(comfyui_runtime=comfyui_runtime, base_url=args.comfy_url)
        payload["browser_evidence_instructions"] = browser_evidence_instructions(
            "ai_studio_prep_<uuid>.json"
        )
        payload["control_test_instructions"] = control_test_instructions()
        payload["round_trip_test_instructions"] = round_trip_test_instructions()
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("AI Studio — Live ComfyUI Environment Diagnostic")
            print("=" * 40)
            for key in (
                "comfyui_reachable",
                "comfyui_base_url",
                "python_version",
                "comfyui_backend_git",
                "comfyui_frontend_version_signal",
                "comfyui_frontend_package_version",
                "launch_arguments",
                "loaded_node_count",
                "custom_node_packages",
                "extensions",
            ):
                print(f"{key}: {payload.get(key)}")
            _print_section("Control test", payload["control_test_instructions"])
            _print_section("Browser evidence", payload["browser_evidence_instructions"])
        return 0

    try:
        preparation_id = normalize_preparation_id(args.preparation_id)
    except InvalidPreparationIdError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    record = find_by_preparation_id(preparations_log_path(bundle.path("drive_root")), preparation_id)
    if record is None:
        print(f"ERROR: Preparation not found: {preparation_id}", file=sys.stderr)
        return 1
    prepared_dir = Path(str(record.get("drive_prepared_dir") or record.get("runtime_prepared_dir") or ""))
    source = prepared_dir / f"{preparation_id}.workflow.json"

    payload = analyze_preparation_open(
        preparation_id=preparation_id,
        source_workflow_path=source,
        comfyui_runtime=comfyui_runtime,
        base_url=args.comfy_url,
        known_good_filename=args.known_good_filename,
    )

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("AI Studio — Live ComfyUI Workflow-Open Diagnostic")
        print("=" * 40)
        print(f"SERVER REGISTRATION: {payload.get('server_registration')}")
        print(f"BROWSER GRAPH OPEN:  {payload.get('browser_graph_open')}")
        print(f"Root cause status:   {payload.get('root_cause', {}).get('status')}")
        for key in (
            "preparation_id",
            "prepared_workflow_load_filename",
            "comfyui_reachable",
            "comfyui_backend_git",
            "comfyui_frontend_version_signal",
            "observed_workflow_version",
            "canonical_prepared_hash",
            "frontend_load_copy_hash",
            "schema_valid",
            "integrity_valid",
            "integrity_errors",
            "object_info_node_check",
            "workflow_listed",
            "listing_size_match",
            "userdata_get_ok",
            "userdata_get_starts_with_object",
            "userdata_get_preview",
            "known_good_control",
        ):
            value = payload.get(key)
            if key == "known_good_control" and isinstance(value, dict):
                print(f"{key}.available: {value.get('available')}")
                if value.get("comparison_to_ai_studio_load_copy"):
                    print(
                        f"{key}.difference_count: "
                        f"{value['comparison_to_ai_studio_load_copy'].get('difference_count')}"
                    )
            else:
                print(f"{key}: {value}")
        _print_section("Control test", payload.get("control_test_instructions") or [])
        _print_section("Browser evidence", payload.get("browser_evidence_instructions") or [])
        _print_section("Round-trip test", payload.get("round_trip_test_instructions") or [])
        print()
        print("NOTE: This diagnostic is read-only and does not prove browser graph open.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
