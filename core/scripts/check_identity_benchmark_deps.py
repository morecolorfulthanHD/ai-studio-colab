#!/usr/bin/env python3
"""Check Package 4.12 identity-benchmark dependency readiness (no auto-download)."""

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

from core.runtime.identity_benchmark import (
    CANDIDATE_FACEID,
    CANDIDATE_REACTOR,
    LIVE_CANDIDATES,
    assess_identity_benchmark_dependencies,
)
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def _yn(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def _print_human(report: dict) -> None:
    print("AI Studio — Identity Benchmark Dependency Check")
    print("=" * 40)
    print(f"Package: {report['package_version']}")
    print(f"Quality claim: {report['quality_claim']}")
    oi = report.get("comfyui_object_info") or {}
    print(f"ComfyUI object_info: {oi.get('status')} — {oi.get('notes')}")
    print()

    reactor = (report.get("candidates") or {}).get(CANDIDATE_REACTOR) or {}
    rd = reactor.get("detail") or {}
    print("REACTOR")
    print(f"  custom node present: {_yn(rd.get('custom_node_present'))} ({rd.get('custom_node')})")
    if rd.get("pinned_revision_determinable"):
        print(
            f"  pinned revision match: {_yn(rd.get('pinned_revision_match'))} "
            f"(want {(rd.get('pinned_commit') or '')[:12]} have {(rd.get('current_commit') or '')[:12]})"
        )
    else:
        print("  pinned revision match: not determinable")
    print(f"  registration/import: {rd.get('registration_status')}")
    if rd.get("registration_notes"):
        print(f"    notes: {rd.get('registration_notes')}")
    print(f"  w600k_r50.onnx present: {_yn(rd.get('w600k_r50_onnx'))}")
    print(f"  inswapper_128.onnx present: {_yn(rd.get('inswapper_128_onnx'))}")
    print(f"  candidate ready: {_yn(reactor.get('ready'))}")
    print()

    faceid = (report.get("candidates") or {}).get(CANDIDATE_FACEID) or {}
    fd = faceid.get("detail") or {}
    print("IPADAPTER FACEID")
    print(f"  custom node present: {_yn(fd.get('custom_node_present'))} ({fd.get('custom_node')})")
    if fd.get("pinned_revision_determinable"):
        print(
            f"  pinned revision match: {_yn(fd.get('pinned_revision_match'))} "
            f"(want {(fd.get('pinned_commit') or '')[:12]} have {(fd.get('current_commit') or '')[:12]})"
        )
    else:
        print("  pinned revision match: not determinable")
    print(f"  registration/import: {fd.get('registration_status')}")
    if fd.get("registration_notes"):
        print(f"    notes: {fd.get('registration_notes')}")
    print(f"  FaceID Plus v2 .bin present: {_yn(fd.get('faceid_plusv2_bin'))}")
    print(f"  matching LoRA present: {_yn(fd.get('faceid_plusv2_lora'))}")
    print(f"  CLIP ViT-H present: {_yn(fd.get('clip_vit_h'))}")
    print(f"  w600k_r50.onnx present: {_yn(fd.get('w600k_r50_onnx'))}")
    print(f"  candidate ready: {_yn(faceid.get('ready'))}")
    print()

    print("OVERALL")
    print(f"  ready_for_case_c={report.get('ready_for_case_c')}")
    print()
    print(
        "Manual asset download instructions are deferred until this live probe "
        "identifies what is actually missing. Restricted weights are never auto-downloaded."
    )
    missing = report.get("missing_model_names") or []
    if missing:
        print(f"Missing model registry names (probe only): {', '.join(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report ReActor/FaceID node pins and manual model presence for Case C readiness. "
            "Does not download restricted weights. Does not claim visual quality."
        )
    )
    parser.add_argument("--candidate", choices=list(LIVE_CANDIDATES), default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--comfyui-base-url", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    comfy = bundle.path("comfyui_runtime") / "custom_nodes"
    report = assess_identity_benchmark_dependencies(
        bundle_models=list(bundle.models),
        bundle_nodes=list(bundle.nodes),
        comfyui_custom_nodes=comfy if comfy.parent.is_dir() else None,
        candidate=args.candidate,
        comfyui_base_url=args.comfyui_base_url,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)
    return 0 if report.get("ready_for_case_c") else 2


if __name__ == "__main__":
    raise SystemExit(main())
