#!/usr/bin/env python3
"""Package 4.12.3 consolidated automated QA runner."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.registry_loader import RegistryLoader, find_repo_root
from core.runtime.studio_timezone import studio_date_stamp, studio_now

_PASS_RE = re.compile(r"RESULT:\s*(\d+)/(\d+)")
_ALT_PASS_RE = re.compile(r"(?:results|Summary):\s*(\d+)\s*(?:passed|/)", re.IGNORECASE)
_ALT_TOTAL_RE = re.compile(r"(\d+)\s*(?:passed).*(?:(\d+)\s*total|/(\d+))", re.IGNORECASE)
_SUITE_PASS_RE = re.compile(r"(?:\[PASS\]|^PASS:)", re.MULTILINE)


def _run_suite(repo_root: Path, script_name: str) -> dict:
    script = repo_root / "core" / "scripts" / script_name
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    pass_hits = len(_SUITE_PASS_RE.findall(combined))
    match = _PASS_RE.search(combined)
    if match:
        passed = int(match.group(1))
        total = int(match.group(2))
        pass_line = match.group(0)
    else:
        alt = None
        for line in combined.splitlines()[::-1]:
            if "passed" in line.lower() and ("total" in line.lower() or "/" in line):
                alt = line
                break
        if alt and "results:" in alt.lower():
            # Package 4.11 results: 35 passed, 0 failed, 35 total
            m_res = re.search(
                r"results:\s*(\d+)\s+passed,\s*\d+\s+failed,\s*(\d+)\s+total",
                alt,
                re.IGNORECASE,
            )
            if m_res:
                passed = int(m_res.group(1))
                total = int(m_res.group(2))
            else:
                passed = total = pass_hits
            pass_line = alt.strip()
        elif alt and "Summary:" in alt:
            # Summary: 80/80 simulations passed
            m2 = re.search(r"(\d+)/(\d+)", alt)
            if m2:
                passed, total = int(m2.group(1)), int(m2.group(2))
            else:
                passed = total = pass_hits
            pass_line = alt.strip()
        else:
            passed = pass_hits
            total = pass_hits
            pass_line = None
    ok = proc.returncode == 0
    return {
        "script": script_name,
        "exit_code": proc.returncode,
        "passed": passed,
        "total": total,
        "pass_line": pass_line,
        "ok": ok,
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-8:]),
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-8:]),
    }


def _timezone_checks() -> dict:
    from datetime import timezone as tz

    evening_utc = datetime(2026, 9, 12, 2, 31, tzinfo=tz.utc)
    stamp = studio_date_stamp(evening_utc)
    ok = stamp == "20260911" and studio_now(evening_utc).tzinfo is not None
    return {
        "name": "timezone_inline",
        "ok": ok,
        "studio_date_stamp": stamp,
        "expected": "20260911",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Package 4.12.3 consolidated QA.")
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="JSON report path (default: logs/qa/package_4_12_3_latest.json under Drive or repo).",
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_file=Path(__file__))
    bundle = RegistryLoader(repo_root).load_all()

    default_report = bundle.path("drive_logs") / "qa" / "package_4_12_3_latest.json"
    repo_fallback = repo_root / "logs" / "qa" / "package_4_12_3_latest.json"
    report_path = args.report_path or default_report

    suites = [
        "simulate_package412_character_identity.py",
        "simulate_package411_generation_derivation.py",
        "simulate_package410_generation_reproduction.py",
        "simulate_output_autosync.py",
        "simulate_package4123_identity_architecture.py",
    ]
    results = [_run_suite(repo_root, name) for name in suites]
    tz_result = _timezone_checks()

    total_passed = sum(r["passed"] for r in results) + (1 if tz_result["ok"] else 0)
    total_tests = sum(r["total"] for r in results) + 1
    all_ok = all(r["ok"] for r in results) and tz_result["ok"]

    report = {
        "package": "4.12.3",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "generated_at_studio": studio_now().replace(microsecond=0).isoformat(),
        "repo_root": str(repo_root),
        "all_required_suites_pass": all_ok,
        "suites": results,
        "timezone_checks": tz_result,
        "totals": {
            "passed": total_passed,
            "total": total_tests,
            "failed": 0 if all_ok else 1,
        },
    }

    written_paths: list[str] = []
    for target in (report_path, repo_fallback):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            written_paths.append(str(target))
        except OSError:
            continue

    print("AUTOMATED QA SUMMARY")
    print("=" * 40)
    print(f"Package 4.12.3:           {'PASS' if results[-1]['ok'] else 'FAIL'}")
    print(f"4.12.2/4.12 regressions:  {'PASS' if results[0]['ok'] else 'FAIL'}")
    print(f"4.11 regressions:         {'PASS' if results[1]['ok'] else 'FAIL'}")
    print(f"4.10 regressions:         {'PASS' if results[2]['ok'] else 'FAIL'}")
    print(f"autosync:                 {'PASS' if results[3]['ok'] else 'FAIL'}")
    print(f"timezone inline:          {'PASS' if tz_result['ok'] else 'FAIL'}")
    print(f"Tests run:                {total_tests}")
    print(f"Passed:                   {total_passed}")
    print(f"Failed suites:            {sum(1 for r in results if not r['ok']) + (0 if tz_result['ok'] else 1)}")
    if written_paths:
        print(f"Report:                   {written_paths[0]}")
    print()
    print(f"OVERALL: {'PASS' if all_ok else 'FAIL'}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
