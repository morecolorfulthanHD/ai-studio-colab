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
    INTEGRITY_VERIFIED,
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


def _integrity_label(status: str | None, *, verified: bool | None = None) -> str:
    if status:
        return str(status)
    if verified:
        return "VERIFIED"
    return "MISSING"


def _print_asset_status(label: str, row: dict | None) -> None:
    row = row or {}
    status = _integrity_label(row.get("status"), verified=row.get("verified"))
    filename = row.get("filename") or label
    print(f"  {label}: {status} ({filename})")
    if status not in {INTEGRITY_VERIFIED, "PRESENT"}:
        path = row.get("runtime_path")
        if path:
            print(f"    path: {path}")


def _verified_or_status(status: str | None, *, verified: bool | None = None) -> str:
    if verified is True:
        return "VERIFIED"
    raw = str(status or "UNCHECKED").strip()
    if raw.lower() in {"ok", "verified"}:
        return "VERIFIED"
    return raw.upper() if raw else "UNCHECKED"


def _print_human(report: dict) -> None:
    print("AI Studio — Identity Benchmark Dependency Check")
    print("=" * 40)
    print(f"Package: {report['package_version']}")
    print(f"Quality claim: {report['quality_claim']}")
    if report.get("faceid_license_note"):
        print(f"FaceID license: {report['faceid_license_note']}")
    oi = report.get("comfyui_object_info") or {}
    print(f"ComfyUI object_info: {oi.get('status')} — {oi.get('notes')}")
    attempts = oi.get("attempts") or []
    if attempts:
        print(
            f"  object_info attempts: {len(attempts)} "
            f"(bounded retry; last={attempts[-1].get('status')})"
        )
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
    print(f"  Canonical Drive w600k_r50.onnx: {rd.get('canonical_buffalo_status') or 'unknown'}")
    print(
        f"  ReActor runtime w600k_r50.onnx: "
        f"{rd.get('reactor_runtime_buffalo_status') or 'unknown'} "
        f"(verified={_yn(rd.get('reactor_runtime_buffalo_verified'))})"
    )
    print(f"  Canonical Drive inswapper_128.onnx: {rd.get('canonical_inswapper_status') or 'unknown'}")
    print(
        f"  ReActor runtime inswapper_128.onnx: "
        f"{rd.get('reactor_runtime_inswapper_status') or 'unknown'} "
        f"(verified={_yn(rd.get('reactor_runtime_inswapper_verified'))})"
    )
    print(
        f"  Live ReActor swap_model option: "
        f"{rd.get('live_swap_model_option_status') or 'unknown'} "
        f"(verified={_yn(rd.get('live_swap_model_option_verified'))})"
    )
    if rd.get("live_swap_model_option_notes"):
        print(f"    notes: {rd.get('live_swap_model_option_notes')}")
    options = rd.get("live_swap_model_options") or []
    if options:
        preview = ", ".join(str(x) for x in options[:8])
        more = "" if len(options) <= 8 else f" (+{len(options) - 8} more)"
        print(f"    options: {preview}{more}")
    print(f"  w600k_r50.onnx ready: {_yn(rd.get('w600k_r50_onnx'))}")
    print(f"  inswapper_128.onnx ready: {_yn(rd.get('inswapper_128_onnx'))}")
    print(f"  candidate ready: {_yn(reactor.get('ready'))}")
    print()

    faceid = (report.get("candidates") or {}).get(CANDIDATE_FACEID) or {}
    fd = faceid.get("detail") or {}
    assets = fd.get("assets") or {}
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
    _print_asset_status("FaceID Plus v2 .bin", assets.get("ipadapter_faceid_plusv2_sd15"))
    _print_asset_status("matching LoRA", assets.get("ipadapter_faceid_plusv2_sd15_lora"))
    _print_asset_status("CLIP ViT-H", assets.get("clip_vision_sd15"))
    _print_asset_status("w600k_r50.onnx", assets.get("insightface_w600k_r50"))
    print(
        f"  Runtime CLIP Vision bridge: "
        f"{_verified_or_status(fd.get('runtime_clip_vision_discovery_status'), verified=fd.get('runtime_clip_vision_discovery_verified'))}"
    )
    print(
        f"  Runtime FaceID .bin bridge: "
        f"{_verified_or_status(fd.get('runtime_ipadapter_discovery_status'), verified=fd.get('runtime_ipadapter_discovery_verified'))}"
    )
    print(
        f"  Runtime FaceID LoRA bridge: "
        f"{_verified_or_status(fd.get('runtime_lora_discovery_status'), verified=fd.get('runtime_lora_discovery_verified'))}"
    )
    print(
        f"  Live FaceID node registration: "
        f"{_verified_or_status(fd.get('live_node_registration_status') or fd.get('registration_status'), verified=fd.get('live_node_registration_verified'))}"
    )
    print(
        f"  FaceID CLIP resolver/discovery: "
        f"{_verified_or_status(fd.get('live_clip_discovery_status'), verified=fd.get('live_clip_discovery_verified'))}"
    )
    if fd.get("live_clip_discovery_notes"):
        print(f"    notes: {fd.get('live_clip_discovery_notes')}")
    print(
        f"  InsightFace Python module: "
        f"{_verified_or_status(fd.get('insightface_python_status'), verified=fd.get('insightface_python_verified'))}"
    )
    if fd.get("insightface_python_notes"):
        print(f"    notes: {fd.get('insightface_python_notes')}")
    if fd.get("insightface_python_executable"):
        print(f"    python: {fd.get('insightface_python_executable')}")
    print(
        "  benchmark execution: not yet tested"
        if not fd.get("benchmark_execution_tested")
        else "  benchmark execution: tested"
    )
    print(f"  candidate ready: {_yn(faceid.get('ready'))}")
    print()

    print("OVERALL")
    print(f"  ready_for_case_c={report.get('ready_for_case_c')}")
    print()
    print(
        "Restricted FaceID/InsightFace weights are never auto-downloaded. "
        "Drive models/shared/insightface is canonical; Full Launch creates a real "
        "ComfyUI/models/insightface directory with file-level bridges so ReActor "
        "glob discovery and live object_info advertise inswapper_128.onnx. "
        "Filesystem presence alone is not sufficient — live swap_model option must be VERIFIED. "
        "When registry integrity metadata is configured for FaceID, assets must be VERIFIED "
        "(existence + size + SHA256). FaceID candidate ready also requires live ComfyUI "
        "object_info, FaceID node registration, runtime CLIP/IPAdapter/LoRA bridges, "
        "pinned CLIP resolver/discovery, and importable insightface/onnxruntime in the "
        "ComfyUI Python interpreter — unchecked/timeout/error is not ready."
    )
    failures = report.get("integrity_failures") or []
    if failures:
        print()
        print("Integrity failures:")
        for line in failures:
            print(f"  - {line}")
    missing = report.get("missing_model_names") or []
    if missing:
        print(f"Not-ready model registry names: {', '.join(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report ReActor/FaceID node pins and model integrity for Case C readiness. "
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
    comfyui_runtime = bundle.path("comfyui_runtime")
    comfy = comfyui_runtime / "custom_nodes"

    def _hash_status(filename: str) -> None:
        if not args.json:
            print(f"Verifying SHA256: {filename} ...", flush=True)

    report = assess_identity_benchmark_dependencies(
        bundle_models=list(bundle.models),
        bundle_nodes=list(bundle.nodes),
        comfyui_custom_nodes=comfy if comfy.is_dir() else None,
        comfyui_runtime=comfyui_runtime if comfyui_runtime.is_dir() else None,
        candidate=args.candidate,
        comfyui_base_url=args.comfyui_base_url,
        hash_status_callback=None if args.json else _hash_status,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)
    return 0 if report.get("ready_for_case_c") else 2


if __name__ == "__main__":
    raise SystemExit(main())
