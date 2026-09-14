#!/usr/bin/env python3
"""Launch dedicated AI Studio operator Chrome only if an active RUNNING run allows it.

Uses the central owned-spawn API. The Chrome *browser* is registered as kind=chrome
with contain=False so Job Object kill-on-parent-close does NOT terminate an
already-open dedicated browser (default stop policy). Relaunch is still blocked
after cancellation via lifecycle state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.colab_operator_lifecycle import (
    OperatorCancelled,
    OperatorLifecycle,
    launch_operator_chrome_allowed,
)


def resolve_chrome_executable() -> Path | None:
    chrome = Path(os.environ.get("CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe"))
    if chrome.is_file():
        return chrome
    for cand in (
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ):
        if cand.is_file():
            return cand
    return None


def build_chrome_argv(
    *,
    chrome: Path,
    profile: Path,
    colab_url: str,
    cdp_port: int,
) -> list[str]:
    return [
        str(chrome),
        f"--remote-debugging-port={cdp_port}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        colab_url,
    ]


def launch_chrome_for_run(
    life: OperatorLifecycle,
    run_id: str,
    *,
    colab_url: str,
    cdp_port: int = 9222,
    force: bool = False,
) -> dict:
    """Gate + owned spawn (kind=chrome, not job-contained)."""
    if not force and not launch_operator_chrome_allowed(life, run_id):
        return {
            "ok": False,
            "refused": True,
            "code": 3,
            "message": (
                "REFUSED: Chrome launch blocked — run cancelled, stale, or not RUNNING. "
                f"run_id={run_id}"
            ),
        }
    chrome = resolve_chrome_executable()
    if chrome is None:
        return {"ok": False, "refused": False, "code": 2, "message": "Chrome not found"}
    profile = life.chrome_user_data_dir
    profile.mkdir(parents=True, exist_ok=True)
    argv = build_chrome_argv(
        chrome=chrome, profile=profile, colab_url=colab_url, cdp_port=cdp_port
    )
    try:
        # kind=chrome forces contain=False inside spawn_owned_helper
        result = life.spawn_owned_helper(run_id, argv, kind="chrome", contain=False)
    except OperatorCancelled as exc:
        return {
            "ok": False,
            "refused": True,
            "code": 3,
            "message": str(exc),
        }
    return {
        "ok": True,
        "refused": False,
        "code": 0,
        "pid": result.pid,
        "contained": result.contained,
        "profile": str(profile),
        "spawn": result.to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gated operator Chrome launcher")
    parser.add_argument("--run-id", required=True, help="Active operator_run_id")
    parser.add_argument(
        "--colab-url",
        default=(
            "https://colab.research.google.com/github/morecolorfulthanHD/ai-studio-colab/"
            "blob/main/colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb"
        ),
    )
    parser.add_argument("--cdp-port", type=int, default=9222)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Unsafe: skip lifecycle gate (tests / emergency only)",
    )
    parser.add_argument("--state-dir", default=None, help="Override state dir (tests)")
    args = parser.parse_args(argv)

    life = OperatorLifecycle(state_dir=Path(args.state_dir) if args.state_dir else None)
    out = launch_chrome_for_run(
        life,
        args.run_id,
        colab_url=args.colab_url,
        cdp_port=args.cdp_port,
        force=bool(args.force),
    )
    if not out.get("ok"):
        print(out.get("message") or "REFUSED")
        return int(out.get("code") or 3)
    print(json.dumps({"LAUNCHED": out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
