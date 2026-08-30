#!/usr/bin/env python3
"""Report identity-method benchmark ledger contents."""

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

from core.runtime.identity_benchmark import format_identity_benchmark_report, load_identity_benchmark_records
from core.runtime.identity_benchmark_capture import recover_identity_benchmarks_from_history
from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.workflow_provenance import load_registered_workflow_hashes


def _format_recovery_section(recovery_report: dict | None) -> tuple[str, str]:
    """Return (section_text, overall_status_token)."""
    if recovery_report is None:
        return (
            "History recovery\n"
            "----------------------------------------\n"
            "status=skipped (--no-recover-history)\n",
            "SKIPPED",
        )
    failed = int(recovery_report.get("failed") or 0)
    errors = list(recovery_report.get("errors") or [])
    ok = bool(recovery_report.get("ok")) and failed == 0 and not errors
    if ok:
        status = "OK"
    elif int(recovery_report.get("captured") or 0) > 0 or int(recovery_report.get("duplicates") or 0) > 0:
        status = "PARTIAL_FAIL"
    else:
        status = "FAIL"
    lines = [
        "History recovery",
        "-" * 40,
        f"status={status}",
        (
            f"examined={recovery_report.get('examined')} "
            f"captured={recovery_report.get('captured')} "
            f"duplicates={recovery_report.get('duplicates')} "
            f"reclassified={recovery_report.get('reclassified')} "
            f"failed={recovery_report.get('failed')}"
        ),
    ]
    for msg in recovery_report.get("messages") or []:
        lines.append(f"  {msg}")
    for err in errors:
        lines.append(f"ERROR: {err}")
    if status != "OK":
        lines.append(
            "STOP: History recovery did not fully succeed. "
            "Do not treat this report as proof that live executions were reconciled."
        )
    return "\n".join(lines) + "\n", status


def main() -> int:
    parser = argparse.ArgumentParser(description="Report identity method benchmark ledger.")
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--recover-history",
        action="store_true",
        default=True,
        help="Attempt missed-history recovery before reporting (default: on).",
    )
    parser.add_argument(
        "--no-recover-history",
        action="store_true",
        help="Skip ComfyUI history recovery; report ledger only.",
    )
    parser.add_argument("--comfyui-base-url", default=None)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    ledger = args.ledger or (bundle.path("drive_logs") / "identity_benchmark.jsonl")

    recover = bool(args.recover_history) and not bool(args.no_recover_history)
    recovery_report = None
    if recover:
        base = args.comfyui_base_url
        if not base:
            from core.runtime.comfyui_userdata import DEFAULT_COMFY_BASE_URL

            base = DEFAULT_COMFY_BASE_URL
        registered = load_registered_workflow_hashes(repo_root, bundle.workflows)
        recovery_report = recover_identity_benchmarks_from_history(
            drive_root=bundle.path("drive_root"),
            ledger_path=ledger,
            comfy_output_dir=bundle.path("comfyui_runtime") / "output",
            base_url=base,
            registered_hashes=registered,
            drive_output_dir=bundle.path("drive_root") / "outputs",
            evidence_path=bundle.path("drive_logs") / "autosync" / "evidence.jsonl",
        )

    records = load_identity_benchmark_records(ledger)
    recovery_section, recovery_status = _format_recovery_section(recovery_report)

    if args.json:
        print(
            json.dumps(
                {
                    "records": records,
                    "recovery": recovery_report,
                    "recovery_status": recovery_status,
                    "ledger_report_loaded": True,
                },
                indent=2,
            )
        )
    else:
        print(recovery_section)
        print(format_identity_benchmark_report(records))
        print()
        print(f"Ledger report: LOADED ({len(records)} record(s))")
        print(f"History recovery: {recovery_status}")
        if recovery_status == "OK" or recovery_status == "SKIPPED":
            print("RESULT: OK — identity benchmark report complete.")
            return 0
        print(
            "RESULT: STOP — identity benchmark ledger listed above, "
            "but history recovery did not fully succeed."
        )
        return 2
    if recovery_status in {"OK", "SKIPPED"}:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
