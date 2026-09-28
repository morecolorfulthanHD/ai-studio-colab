#!/usr/bin/env python3
"""Durable ComfyUI core launch CLI (background / kernel.execute safe).

Starts ComfyUI, waits for local HTTP 200 on /system_stats, writes process state.
Proxy/eval_js is optional and never required for core readiness.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
import cli_activate  # noqa: E402

cli_activate.activate(__file__)

from core.runtime.comfyui_process import (  # noqa: E402
    DEFAULT_COMFY_PORT,
    DEFAULT_HEALTH_TIMEOUT_S,
    core_readiness_ok,
    start_comfyui_core,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start ComfyUI core (local HTTP readiness).")
    parser.add_argument("--comfyui-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_COMFY_PORT)
    parser.add_argument("--runtime-dir", type=Path, default=None)
    parser.add_argument("--log-path", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--health-timeout", type=float, default=DEFAULT_HEALTH_TIMEOUT_S)
    parser.add_argument("--obtain-proxy", action="store_true", help="Best-effort Colab proxy URL")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--watcher-status-json",
        type=str,
        default=None,
        help="Optional OutputWatcher status JSON for combined readiness check",
    )
    args = parser.parse_args()

    eval_js_fn = None
    if args.obtain_proxy:
        try:
            from google.colab.output import eval_js as _eval_js  # type: ignore

            eval_js_fn = _eval_js
        except Exception:
            eval_js_fn = None

    result = start_comfyui_core(
        comfyui_dir=args.comfyui_dir,
        port=int(args.port),
        log_path=args.log_path,
        runtime_dir=args.runtime_dir,
        repo_root=args.repo_root,
        health_timeout_s=float(args.health_timeout),
        obtain_proxy=bool(args.obtain_proxy),
        eval_js_fn=eval_js_fn,
        start_new_session=True,
    )
    payload = result.to_dict()
    if args.watcher_status_json:
        try:
            watcher = json.loads(args.watcher_status_json)
        except json.JSONDecodeError:
            watcher = None
        payload["core_readiness_ok"] = core_readiness_ok(
            comfy_http_status=result.http_status,
            watcher_status=watcher if isinstance(watcher, dict) else None,
        )

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for msg in result.messages:
            print(msg)
        for err in result.errors:
            print(f"ERROR: {err}", file=sys.stderr)
        print(
            f"ok={result.ok} pid={result.pid} http={result.http_status} "
            f"proxy={result.proxy_url!r} proxy_error={result.proxy_error!r}"
        )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
