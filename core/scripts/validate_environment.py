#!/usr/bin/env python3
"""Report runtime environment details for AI Studio Colab.

Checks Python, Colab detection, paths, Drive mount, and GPU visibility.
Warnings are printed for missing optional capabilities; script exits 0 unless
a fatal detection error occurs.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def is_colab() -> bool:
    try:
        import google.colab  # noqa: F401, PLC0415

        return True
    except ImportError:
        return False


def drive_mounted(drive_root: Path | None = None) -> bool:
    root = drive_root or Path("/content/drive/MyDrive")
    return root.is_dir() and os.access(root, os.R_OK)


def check_nvidia_smi() -> tuple[bool, str]:
    if shutil.which("nvidia-smi") is None:
        return False, "nvidia-smi not found in PATH"

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"nvidia-smi failed: {exc}"

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        return False, stderr or f"nvidia-smi exited with code {result.returncode}"

    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    if not lines:
        return False, "nvidia-smi returned no GPU information"

    return True, "; ".join(lines)


def main() -> int:
    print("AI Studio Colab — Environment Validation")
    print("=" * 40)

    print(f"Python version:    {sys.version.split()[0]} ({platform.platform()})")
    print(f"Current directory: {Path.cwd()}")

    colab = is_colab()
    print(f"Google Colab:      {'yes' if colab else 'no (or google.colab not importable)'}")

    content_path = Path("/content")
    if content_path.is_dir():
        print(f"/content:          present ({content_path})")
    else:
        print("/content:          not present (expected on Colab, optional locally)")

    drive_root = Path("/content/drive/MyDrive/AI_Studio")
    if drive_mounted():
        print(f"Google Drive:      mounted ({drive_root.parent.parent})")
        if drive_root.is_dir():
            print(f"AI_Studio root:    present ({drive_root})")
        else:
            print(f"AI_Studio root:    not yet created ({drive_root})")
            print("  [warn] Drive is mounted but AI_Studio folder does not exist yet.")
    else:
        print("Google Drive:      not mounted or not readable")
        print("  [warn] Mount Drive in the control panel before using persistent storage.")

    gpu_ok, gpu_info = check_nvidia_smi()
    if gpu_ok:
        print(f"GPU:               {gpu_info}")
    else:
        print(f"GPU:               unavailable — {gpu_info}")
        print("  [warn] GPU not detected. Image generation will not work until a GPU runtime is selected.")

    print("\nRESULT: Environment report complete.")
    if not colab:
        print("  [info] Running outside Colab is supported for local validation only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
