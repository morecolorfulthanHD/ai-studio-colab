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
_FAIL_RE = re.compile(r"(?:^|\s)(?:FAIL|FAILED|\[FAIL\])", re.MULTILINE)
_SKIP_RE = re.compile(r"(?:^|\s)(?:SKIP|SKIPPED|\[SKIP\])", re.MULTILINE)
_WARN_RE = re.compile(r"(?:^|\s)(?:WARN(?:ING)?|\[WARN\])", re.MULTILINE | re.IGNORECASE)
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
    fail_hits = len(_FAIL_RE.findall(combined))
    skip_hits = len(_SKIP_RE.findall(combined))
    warn_hits = len(_WARN_RE.findall(combined))

    passed = 0
    total = 0
    failed = 0
    pass_line = None
    match = _PASS_RE.search(combined)
    if match:
        passed = int(match.group(1))
        total = int(match.group(2))
        failed = max(0, total - passed)
        pass_line = match.group(0)
    else:
        alt = None
        for line in combined.splitlines()[::-1]:
            if "passed" in line.lower() and ("total" in line.lower() or "/" in line):
                alt = line
                break
        if alt and "results:" in alt.lower():
            m_res = re.search(
                r"results:\s*(\d+)\s+passed,\s*(\d+)\s+failed,\s*(\d+)\s+total",
                alt,
                re.IGNORECASE,
            )
            if m_res:
                passed = int(m_res.group(1))
                failed = int(m_res.group(2))
                total = int(m_res.group(3))
            else:
                passed = total = pass_hits
                failed = fail_hits
            pass_line = alt.strip()
        elif alt and "Summary:" in alt:
            m2 = re.search(r"(\d+)/(\d+)", alt)
            if m2:
                passed, total = int(m2.group(1)), int(m2.group(2))
                failed = max(0, total - passed)
            else:
                passed = total = pass_hits
                failed = fail_hits
            pass_line = alt.strip()
        else:
            passed = pass_hits
            total = pass_hits
            failed = fail_hits

    tests_discovered = int(total)
    # Required suite: exit 0 with zero tests discovered must FAIL.
    zero_tests_fail = tests_discovered == 0
    ok = proc.returncode == 0 and not zero_tests_fail and failed == 0 and passed == tests_discovered
    return {
        "name": script_name,
        "script": script_name,
        "exit_code": proc.returncode,
        "tests_discovered": tests_discovered,
        "passed": passed,
        "failed": failed if not zero_tests_fail else max(failed, 1),
        "skipped": skip_hits,
        "warnings": warn_hits,
        "pass_line": pass_line,
        "ok": ok,
        "zero_tests_discovered": zero_tests_fail,
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-8:]),
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-8:]),
    }


def _timezone_checks() -> dict:
    from datetime import timezone as tz
    import os

    from core.runtime.studio_timezone import get_studio_timezone_name, studio_now as sn

    evening_utc = datetime(2026, 9, 12, 2, 31, tzinfo=tz.utc)
    stamp = studio_date_stamp(evening_utc)
    # PDT: mid-summer
    pdt_utc = datetime(2026, 7, 15, 19, 0, tzinfo=tz.utc)  # 12:00 PDT
    pdt_local = sn(pdt_utc)
    # PST: mid-winter
    pst_utc = datetime(2026, 1, 15, 20, 0, tzinfo=tz.utc)  # 12:00 PST
    pst_local = sn(pst_utc)
    # Date rollover: UTC already next calendar day, Pacific still previous evening
    rollover_ok = stamp == "20260911"
    pdt_ok = pdt_local.utcoffset() == __import__("datetime").timedelta(hours=-7)
    pst_ok = pst_local.utcoffset() == __import__("datetime").timedelta(hours=-8)
    # Invalid timezone must raise
    prev = os.environ.get("AI_STUDIO_TIMEZONE")
    invalid_ok = False
    try:
        os.environ["AI_STUDIO_TIMEZONE"] = "Not/A_Real_Zone"
        try:
            from core.runtime import studio_timezone as stz

            stz.get_studio_tzinfo()
        except ValueError:
            invalid_ok = True
        finally:
            if prev is None:
                os.environ.pop("AI_STUDIO_TIMEZONE", None)
            else:
                os.environ["AI_STUDIO_TIMEZONE"] = prev
    except Exception:  # noqa: BLE001
        if prev is None:
            os.environ.pop("AI_STUDIO_TIMEZONE", None)
        else:
            os.environ["AI_STUDIO_TIMEZONE"] = prev
        invalid_ok = False

    ok = (
        stamp == "20260911"
        and get_studio_timezone_name() == "America/Los_Angeles"
        and rollover_ok
        and pdt_ok
        and pst_ok
        and invalid_ok
        and studio_now(evening_utc).tzinfo is not None
    )
    return {
        "name": "timezone_inline",
        "ok": ok,
        "tests_discovered": 4,
        "passed": sum([rollover_ok, pdt_ok, pst_ok, invalid_ok]),
        "failed": 4 - sum([rollover_ok, pdt_ok, pst_ok, invalid_ok]),
        "skipped": 0,
        "warnings": 0,
        "studio_date_stamp": stamp,
        "expected": "20260911",
        "pdt_offset_hours": (
            pdt_local.utcoffset().total_seconds() / 3600 if pdt_local.utcoffset() else None
        ),
        "pst_offset_hours": (
            pst_local.utcoffset().total_seconds() / 3600 if pst_local.utcoffset() else None
        ),
        "invalid_timezone_raises": invalid_ok,
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
        "simulate_colab_operator.py",
    ]
    results = [_run_suite(repo_root, name) for name in suites]
    tz_result = _timezone_checks()

    total_passed = sum(r["passed"] for r in results) + int(tz_result["passed"])
    total_tests = sum(r["tests_discovered"] for r in results) + int(tz_result["tests_discovered"])
    total_failed = sum(r["failed"] for r in results) + int(tz_result["failed"])
    all_ok = all(r["ok"] for r in results) and tz_result["ok"]
    # Extra: any required suite with zero tests → overall fail
    if any(r.get("zero_tests_discovered") for r in results):
        all_ok = False

    report = {
        "package": "4.12.3",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "generated_at_studio": studio_now().replace(microsecond=0).isoformat(),
        "repo_root": str(repo_root),
        "all_required_suites_pass": all_ok,
        "suites": results,
        "timezone_checks": tz_result,
        "totals": {
            "tests_discovered": total_tests,
            "passed": total_passed,
            "failed": total_failed,
            "skipped": sum(r.get("skipped", 0) for r in results),
            "warnings": sum(r.get("warnings", 0) for r in results),
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
    for r in results:
        status = "PASS" if r["ok"] else "FAIL"
        print(
            f"{r['name']}: {status} "
            f"(exit={r['exit_code']} discovered={r['tests_discovered']} "
            f"passed={r['passed']} failed={r['failed']} skipped={r['skipped']})"
        )
    print(
        f"timezone_inline: {'PASS' if tz_result['ok'] else 'FAIL'} "
        f"(passed={tz_result['passed']}/{tz_result['tests_discovered']})"
    )
    print(f"Tests discovered:         {total_tests}")
    print(f"Passed:                   {total_passed}")
    print(f"Failed:                   {total_failed}")
    if written_paths:
        print(f"Report:                   {written_paths[0]}")
    print()
    print(f"OVERALL: {'PASS' if all_ok else 'FAIL'}")
    print(f"RESULT: {total_passed}/{total_tests}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
