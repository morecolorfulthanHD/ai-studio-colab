#!/usr/bin/env python3
"""Summarize generation evidence ledger history."""

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

from core.runtime.generation_history import list_recent_generations, prompt_excerpt, provenance_label, summarize_ledger
from core.runtime.registry_loader import RegistryLoader, find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Report generation evidence history.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()
    ledger_path = bundle.path("drive_logs") / "generation_evidence.jsonl"
    summary = summarize_ledger(ledger_path)
    recent = list_recent_generations(ledger_path, limit=args.limit, verified_only=True)
    payload = {"ledger_path": str(ledger_path), "summary": summary.to_dict(), "recent_verified": recent}

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    if args.summary:
        s = summary
        print(
            f"Generations: {s.total} total | verified={s.verified} pending={s.pending} failed={s.failed} | "
            f"legacy={s.legacy} complete_provenance={s.complete_provenance} partial={s.partial_provenance}"
        )
        return 0

    print("AI Studio — Generation History")
    print("=" * 40)
    print(json.dumps(summary.to_dict(), indent=2))
    print("\nRecent verified:")
    for row in recent:
        print(
            f"  {row.get('created_timestamp')} | {row.get('capability') or 'unknown'} | "
            f"{row.get('workflow_identifier') or 'unknown'} | {provenance_label(row)} | "
            f"{prompt_excerpt(row)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
