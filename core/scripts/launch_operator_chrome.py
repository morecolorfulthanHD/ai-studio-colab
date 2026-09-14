#!/usr/bin/env python3
"""Launch dedicated AI Studio operator Chrome only if an active RUNNING run allows it.

Gates relaunch after cancellation. Does not use the normal Chrome profile.
"""

from __future__ import annotations

import argparse
import os
import subprocess
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
    OperatorLifecycle,
    default_chrome_user_data_dir,
    launch_operator_chrome_allowed,
)


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
    args = parser.parse_args(argv)

    life = OperatorLifecycle()
    if not args.force and not launch_operator_chrome_allowed(life, args.run_id):
        print(
            "REFUSED: Chrome launch blocked — run cancelled, stale, or not RUNNING. "
            f"run_id={args.run_id}"
        )
        return 3

    chrome = Path(os.environ.get("CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe"))
    if not chrome.is_file():
        # portable fallbacks
        for cand in (
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/chromium"),
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ):
            if cand.is_file():
                chrome = cand
                break
    if not chrome.is_file():
        print(f"Chrome not found: {chrome}")
        return 2

    profile = default_chrome_user_data_dir()
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(chrome),
        f"--remote-debugging-port={args.cdp_port}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        args.colab_url,
    ]
    proc = subprocess.Popen(cmd)  # noqa: S603 — intentional launcher
    try:
        life.register_child(args.run_id, proc.pid, kind="chrome", argv0=str(chrome))
    except Exception as exc:
        print(f"WARN: registered chrome pid failed: {exc}")
    print(f"LAUNCHED pid={proc.pid} profile={profile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
