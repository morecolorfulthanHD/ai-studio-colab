#!/usr/bin/env python3
"""Package 4.6.1 — notebook-safe project delete/archive confirmation simulations."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.project_workspace import ProjectWorkspace


class SimulationFailure(Exception):
    pass


def _pass(results: list[tuple[str, str]], name: str) -> None:
    results.append((name, "PASS"))


def _assert_true(label: str, value: bool) -> None:
    if not value:
        raise SimulationFailure(f"{label}: expected True")


def _assert_equal(label: str, actual, expected) -> None:
    if actual != expected:
        raise SimulationFailure(f"{label}: expected {expected!r}, got {actual!r}")


def _make_temp_repo(real_repo: Path, drive_root: Path) -> Path:
    """Isolated repo root with configs pointed at a temp Drive workspace."""
    temp_repo = Path(tempfile.mkdtemp(prefix="ai-studio-pkg461-"))
    shutil.copytree(real_repo / "configs", temp_repo / "configs")
    paths_file = temp_repo / "configs" / "paths" / "colab_paths.json"
    data = json.loads(paths_file.read_text(encoding="utf-8"))
    root = str(drive_root).replace("\\", "/")
    path_map = data.setdefault("paths", {})
    path_map["drive_root"] = root
    path_map["drive_outputs"] = f"{root}/outputs"
    path_map["drive_logs"] = f"{root}/logs"
    path_map["drive_inputs"] = f"{root}/inputs"
    path_map["drive_masks"] = f"{root}/masks"
    path_map["drive_workflows"] = f"{root}/workflows"
    path_map["drive_models"] = f"{root}/models"
    paths_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return temp_repo


def _run_cli(real_repo: Path, temp_repo: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(real_repo / "core" / "scripts" / script),
        *args,
        "--repo-root",
        str(temp_repo),
    ]
    return subprocess.run(
        cmd,
        cwd=str(real_repo),
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def run_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    repo = Path(__file__).resolve().parents[2]
    notebook = repo / "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb"
    nb_text = notebook.read_text(encoding="utf-8")
    json.loads(nb_text)

    _assert_true("notebook delete passes --confirm-slug", "--confirm-slug" in nb_text)
    _assert_true(
        "notebook collects exact slug before delete CLI",
        "Type the exact project slug to confirm deletion" in nb_text,
    )
    _pass(results, "Notebook delete menu passes --confirm-slug")

    _assert_true("notebook archive passes --yes", "--yes" in nb_text)
    _assert_true("notebook archive asks YES in notebook", "Type YES to archive" in nb_text)
    _pass(results, "Notebook archive menu passes --yes after notebook confirmation")

    # Direct unit check: noninteractive prompt helper refuses without EOFError.
    from unittest import mock

    delete_mod_path = repo / "core/scripts/delete_project.py"
    dspec = importlib.util.spec_from_file_location("ai_studio_delete_project_mod", delete_mod_path)
    delete_mod = importlib.util.module_from_spec(dspec)
    assert dspec is not None and dspec.loader is not None
    dspec.loader.exec_module(delete_mod)
    with mock.patch.object(delete_mod.sys, "stdin", mock.Mock(isatty=lambda: False)):
        prompted = delete_mod._prompt_exact_slug("demo", Path("/tmp/demo"))
    _assert_true("prompt helper returns None noninteractively", prompted is None)
    _pass(results, "Delete prompt helper requires --confirm-slug when stdin is noninteractive")

    with tempfile.TemporaryDirectory() as tmp_name:
        drive = Path(tmp_name) / "AI_Studio"
        (drive / "outputs").mkdir(parents=True)
        (drive / "logs").mkdir(parents=True)
        workspace = ProjectWorkspace(drive)
        workspace.create_project(display_name="Delete Me", slug="delete-me", set_active=True)
        workspace.create_project(display_name="Keep Me", slug="keep-me")
        temp_repo = _make_temp_repo(repo, drive)
        try:
            missing = _run_cli(repo, temp_repo, "delete_project.py", "--project", "delete-me")
            _assert_equal("noninteractive delete exit", missing.returncode, 1)
            combined = (missing.stdout or "") + (missing.stderr or "")
            _assert_true("mentions --confirm-slug", "--confirm-slug" in combined)
            _assert_true("no uncaught EOFError", "EOFError" not in combined)
            _assert_true("project still present", (drive / "projects" / "delete-me").is_dir())
            _pass(results, "Noninteractive delete without --confirm-slug fails cleanly")

            dry = _run_cli(repo, temp_repo, "delete_project.py", "--project", "delete-me", "--dry-run")
            _assert_equal("dry-run exit", dry.returncode, 0)
            _assert_true("dry-run keeps folder", (drive / "projects" / "delete-me").is_dir())
            _pass(results, "Noninteractive dry-run succeeds without confirmation")

            wrong = _run_cli(
                repo,
                temp_repo,
                "delete_project.py",
                "--project",
                "delete-me",
                "--confirm-slug",
                "wrong-slug",
            )
            _assert_equal("wrong confirm exit", wrong.returncode, 1)
            _assert_true("wrong confirm keeps folder", (drive / "projects" / "delete-me").is_dir())
            _pass(results, "Wrong --confirm-slug makes no changes")

            ok = _run_cli(
                repo,
                temp_repo,
                "delete_project.py",
                "--project",
                "delete-me",
                "--confirm-slug",
                "delete-me",
            )
            _assert_equal("confirm delete exit", ok.returncode, 0)
            _assert_true("deleted folder gone", not (drive / "projects" / "delete-me").exists())
            _assert_true("sibling preserved", (drive / "projects" / "keep-me").is_dir())
            _assert_true("active cleared", workspace.get_active_project() is None)
            _pass(results, "Noninteractive delete with --confirm-slug succeeds")

            workspace.create_project(display_name="Archive Me", slug="archive-me", set_active=True)
            archive_fail = _run_cli(repo, temp_repo, "archive_project.py", "--project", "archive-me")
            _assert_equal("archive without --yes exit", archive_fail.returncode, 1)
            archive_text = (archive_fail.stdout or "") + (archive_fail.stderr or "")
            _assert_true("archive mentions --yes", "--yes" in archive_text)
            _assert_true("no archive EOFError", "EOFError" not in archive_text)
            active = workspace.get_active_project()
            _assert_true(
                "active still active without --yes",
                active is not None and active.slug == "archive-me",
            )
            _pass(results, "Noninteractive active archive without --yes fails cleanly")

            archive_ok = _run_cli(
                repo, temp_repo, "archive_project.py", "--project", "archive-me", "--yes"
            )
            _assert_equal("archive --yes exit", archive_ok.returncode, 0)
            restored = workspace.load_project("archive-me")
            _assert_true("archived", restored is not None and restored.is_archived())
            _assert_true("deactivated after archive", workspace.get_active_project() is None)
            _pass(results, "Noninteractive active archive with --yes succeeds")
        finally:
            shutil.rmtree(temp_repo, ignore_errors=True)

    _pass(results, "Package 4.6.1 confirmation hotfix simulations complete")
    return results


def main() -> int:
    print("AI Studio — Package 4.6.1 Delete Confirmation Simulations")
    print("=" * 50)
    try:
        results = run_simulations()
    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        print("\nRESULT: FAIL — package 4.6.1 simulations failed.")
        return 1
    for name, status in results:
        print(f"  [{status}] {name}")
    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: OK — package 4.6.1 confirmation simulations passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
