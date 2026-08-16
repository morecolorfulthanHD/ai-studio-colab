#!/usr/bin/env python3
"""Package 4.10.1 — Full-launch custom-node clone resilience simulations."""

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

from core.comfyui import install_nodes
from core.comfyui.install_nodes import (
    InstallStep,
    build_git_clone_command,
    clone_with_retries,
    execute_plan,
    inspect_clone_target,
    is_transient_git_error,
    is_valid_git_checkout,
    recover_incomplete_clone,
)
from core.runtime.registry_loader import find_repo_root


class SimulationFailure(Exception):
    pass


def _pass(results: list[tuple[str, str]], name: str) -> None:
    results.append(("PASS", name))
    print(f"  [PASS] {name}")


def _assert_true(label: str, condition: bool) -> None:
    if not condition:
        raise SimulationFailure(label)


def _assert_equal(label: str, left, right) -> None:
    if left != right:
        raise SimulationFailure(f"{label}: {left!r} != {right!r}")


def _assert_false(label: str, value: bool) -> None:
    if value:
        raise SimulationFailure(f"{label}: expected False")


def _init_valid_repo(path: Path, *, marker: str = "ok") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text(f"{marker}\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "sim@example.com"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Sim"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(path),
        check=True,
        capture_output=True,
        text=True,
    )


def _make_incomplete_clone(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git_dir = path / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "config").write_text("[core]\n\trepositoryformatversion = 0\n", encoding="utf-8")
    # No HEAD / objects → not a valid checkout.


def _fake_clone_factory(outcomes: list[tuple[bool, str, bool]]):
    """Return a clone_fn that consumes scripted outcomes then creates a valid repo on success."""
    calls: list[dict] = []

    def _clone(repo_url: str, target: Path, *, force_http1: bool = False):
        idx = len(calls)
        calls.append({"url": repo_url, "target": str(target), "force_http1": force_http1})
        if idx >= len(outcomes):
            ok, err, transient = False, "unexpected extra clone call", False
        else:
            ok, err, transient = outcomes[idx]
        if ok:
            if target.exists():
                shutil.rmtree(target)
            _init_valid_repo(target, marker=f"cloned-{idx}")
            return True, "", False
        # Simulate interrupted clone leftover.
        _make_incomplete_clone(target)
        return False, err, transient

    return _clone, calls


TRANSIENT_ERR = (
    "error: RPC failed; curl 92 HTTP/2 stream 0 was not closed cleanly: CANCEL (err 8)\n"
    "fetch-pack: unexpected disconnect while reading sideband packet\n"
    "fatal: early EOF\n"
    "fatal: fetch-pack: invalid index-pack output"
)


def main() -> int:
    results: list[tuple[str, str]] = []
    temp_dirs: list[Path] = []
    print("Package 4.10.1 — Custom-node clone resilience")
    print("=" * 40)

    try:
        # Transient classifier
        _assert_true("curl 92 transient", is_transient_git_error(TRANSIENT_ERR))
        _assert_true("early EOF transient", is_transient_git_error("fatal: early EOF"))
        _assert_false("auth failure not transient", is_transient_git_error("Authentication failed"))
        _assert_false("not found not transient", is_transient_git_error("Repository not found"))
        _pass(results, "transient git error classification")

        # Exact subprocess argv construction (not merely an internal boolean).
        first_cmd = build_git_clone_command(
            "https://example.com/repo.git",
            "/tmp/target",
            force_http1=False,
        )
        _assert_equal(
            "first-attempt command",
            first_cmd,
            ["git", "clone", "--depth", "1", "https://example.com/repo.git", "/tmp/target"],
        )
        _assert_false("first attempt has no -c", "-c" in first_cmd)
        _assert_false(
            "first attempt has no http.version",
            any("http.version" in part for part in first_cmd),
        )

        retry_cmd = build_git_clone_command(
            "https://example.com/repo.git",
            "/tmp/target",
            force_http1=True,
        )
        _assert_equal(
            "retry command",
            retry_cmd,
            [
                "git",
                "-c",
                "http.version=HTTP/1.1",
                "clone",
                "--depth",
                "1",
                "https://example.com/repo.git",
                "/tmp/target",
            ],
        )
        _assert_true("retry has -c", "-c" in retry_cmd)
        _assert_true(
            "retry has scoped http.version=HTTP/1.1",
            "http.version=HTTP/1.1" in retry_cmd,
        )
        _assert_false(
            "no GIT_HTTP_VERSION in argv",
            any("GIT_HTTP_VERSION" in part for part in retry_cmd),
        )
        _pass(results, "normal first-attempt clone command")
        _pass(results, "retry clone command carries scoped http.version=HTTP/1.1")

        # Local Git accepts scoped -c http.version without global config mutation.
        before_global = subprocess.run(
            ["git", "config", "--global", "--get", "http.version"],
            capture_output=True,
            text=True,
            check=False,
        )
        scoped = subprocess.run(
            ["git", "-c", "http.version=HTTP/1.1", "config", "--get", "http.version"],
            capture_output=True,
            text=True,
            check=False,
        )
        after_global = subprocess.run(
            ["git", "config", "--global", "--get", "http.version"],
            capture_output=True,
            text=True,
            check=False,
        )
        _assert_equal("scoped http.version readable", scoped.stdout.strip(), "HTTP/1.1")
        _assert_equal(
            "global http.version unchanged",
            after_global.returncode,
            before_global.returncode,
        )
        _assert_equal(
            "global http.version value unchanged",
            after_global.stdout,
            before_global.stdout,
        )
        _pass(results, "no global Git config mutation")
        _pass(results, "local git accepts scoped http.version=HTTP/1.1")

        root = Path(tempfile.mkdtemp(prefix="pkg4101-nodes-"))
        temp_dirs.append(root)

        # Successful clone first attempt
        target = root / "ok_first"
        clone_fn, calls = _fake_clone_factory([(True, "", False)])
        result = clone_with_retries(
            "https://example.com/ok.git",
            target,
            max_attempts=3,
            backoff_seconds=(0.0, 0.0),
            sleep_fn=lambda _s: None,
            clone_fn=clone_fn,
        )
        _assert_true("first attempt ok", result.ok)
        _assert_equal("first attempt count", result.attempts, 1)
        _assert_equal("first attempt calls", len(calls), 1)
        _assert_false("first attempt no http1", result.used_http1)
        _assert_true("valid checkout", is_valid_git_checkout(target))
        _pass(results, "successful clone first attempt")

        # Transient then success
        target = root / "transient_then_ok"
        clone_fn, calls = _fake_clone_factory(
            [
                (False, TRANSIENT_ERR, True),
                (True, "", False),
            ]
        )
        result = clone_with_retries(
            "https://example.com/retry.git",
            target,
            max_attempts=3,
            backoff_seconds=(0.0, 0.0),
            sleep_fn=lambda _s: None,
            clone_fn=clone_fn,
        )
        _assert_true("retry ok", result.ok)
        _assert_equal("retry attempts", result.attempts, 2)
        _assert_equal("retry transient count", result.transient_retries, 1)
        _assert_true("retry used http1", result.used_http1)
        _assert_false("first call force_http1 false", calls[0]["force_http1"])
        _assert_true("retry force_http1 on 2nd", calls[1]["force_http1"])
        _assert_equal(
            "retry argv from builder",
            build_git_clone_command(
                "https://example.com/retry.git",
                target,
                force_http1=True,
            ),
            [
                "git",
                "-c",
                "http.version=HTTP/1.1",
                "clone",
                "--depth",
                "1",
                "https://example.com/retry.git",
                str(target),
            ],
        )
        _assert_true("retry recovered", result.recovered_incomplete)
        _pass(results, "transient failure then successful retry")

        # _run_git_clone feeds the exact builder argv into subprocess (no network).
        captured_cmds: list[list[str]] = []
        real_run = install_nodes.subprocess.run

        def _capture_run(cmd, *args, **kwargs):
            captured_cmds.append(list(cmd))
            class _Done:
                returncode = 1
                stdout = ""
                stderr = "fatal: early EOF"

            return _Done()

        install_nodes.subprocess.run = _capture_run  # type: ignore[assignment]
        try:
            probe = root / "argv_probe"
            ok, _err, transient = install_nodes._run_git_clone(
                "https://example.com/probe.git",
                probe,
                force_http1=False,
            )
            _assert_false("probe first not ok", ok)
            _assert_true("probe first transient", transient)
            _assert_equal(
                "_run_git_clone first argv",
                captured_cmds[-1],
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "https://example.com/probe.git",
                    str(probe),
                ],
            )
            ok, _err, transient = install_nodes._run_git_clone(
                "https://example.com/probe.git",
                probe,
                force_http1=True,
            )
            _assert_false("probe retry not ok", ok)
            _assert_equal(
                "_run_git_clone retry argv",
                captured_cmds[-1],
                [
                    "git",
                    "-c",
                    "http.version=HTTP/1.1",
                    "clone",
                    "--depth",
                    "1",
                    "https://example.com/probe.git",
                    str(probe),
                ],
            )
            _assert_true(
                "subprocess argv contains http.version=HTTP/1.1",
                "http.version=HTTP/1.1" in captured_cmds[-1],
            )
            _assert_false(
                "GIT_HTTP_VERSION not in argv",
                any("GIT_HTTP_VERSION" in part for part in captured_cmds[-1]),
            )
        finally:
            install_nodes.subprocess.run = real_run  # type: ignore[assignment]
        _pass(results, "test proving actual command contains http.version=HTTP/1.1")

        # Multiple transient then success
        target = root / "multi_transient"
        clone_fn, calls = _fake_clone_factory(
            [
                (False, TRANSIENT_ERR, True),
                (False, TRANSIENT_ERR, True),
                (True, "", False),
            ]
        )
        result = clone_with_retries(
            "https://example.com/multi.git",
            target,
            max_attempts=3,
            backoff_seconds=(0.0, 0.0),
            sleep_fn=lambda _s: None,
            clone_fn=clone_fn,
        )
        _assert_true("multi ok", result.ok)
        _assert_equal("multi attempts", result.attempts, 3)
        _assert_equal("multi calls", len(calls), 3)
        _pass(results, "multiple transient failures then success")

        # Retries exhausted
        target = root / "exhausted"
        clone_fn, calls = _fake_clone_factory(
            [
                (False, TRANSIENT_ERR, True),
                (False, TRANSIENT_ERR, True),
                (False, TRANSIENT_ERR, True),
            ]
        )
        result = clone_with_retries(
            "https://example.com/fail.git",
            target,
            max_attempts=3,
            backoff_seconds=(0.0, 0.0),
            sleep_fn=lambda _s: None,
            clone_fn=clone_fn,
        )
        _assert_false("exhausted not ok", result.ok)
        _assert_equal("exhausted attempts", result.attempts, 3)
        _assert_equal("exhausted calls", len(calls), 3)
        _assert_true("exhausted still recovered leftovers", not target.exists() or inspect_clone_target(target) != "installed")
        _pass(results, "retries exhausted after transient failures")

        # Required node fail-closed via execute_plan
        req_target = root / "custom_nodes" / "ComfyUI-Manager"
        clone_fn, _calls = _fake_clone_factory(
            [
                (False, TRANSIENT_ERR, True),
                (False, TRANSIENT_ERR, True),
                (False, TRANSIENT_ERR, True),
            ]
        )
        original_clone = install_nodes.clone_with_retries

        def _patched_clone(url, target, **kwargs):
            kwargs.setdefault("max_attempts", 3)
            kwargs.setdefault("backoff_seconds", (0.0, 0.0))
            kwargs.setdefault("sleep_fn", lambda _s: None)
            kwargs["clone_fn"] = clone_fn
            return original_clone(url, target, **kwargs)

        install_nodes.clone_with_retries = _patched_clone  # type: ignore[assignment]
        try:
            steps = [
                InstallStep(
                    action="git_clone",
                    name="ComfyUI-Manager",
                    target_path=str(req_target),
                    source="https://example.com/manager.git",
                    status="missing",
                    required=True,
                )
            ]
            raised = False
            try:
                execute_plan(steps, dry_run=False, clone_attempts=3)
            except RuntimeError as exc:
                raised = True
                _assert_true("required error names node", "ComfyUI-Manager" in str(exc))
            _assert_true("required fails closed", raised)
        finally:
            install_nodes.clone_with_retries = original_clone  # type: ignore[assignment]
        _pass(results, "retries exhausted for required node -> fail")

        # Optional node tolerated
        opt_target = root / "custom_nodes" / "Optional-Node"
        clone_fn, _calls = _fake_clone_factory(
            [
                (False, TRANSIENT_ERR, True),
                (False, TRANSIENT_ERR, True),
                (False, TRANSIENT_ERR, True),
            ]
        )

        def _patched_clone_opt(url, target, **kwargs):
            kwargs.setdefault("max_attempts", 3)
            kwargs.setdefault("backoff_seconds", (0.0, 0.0))
            kwargs.setdefault("sleep_fn", lambda _s: None)
            kwargs["clone_fn"] = clone_fn
            return original_clone(url, target, **kwargs)

        install_nodes.clone_with_retries = _patched_clone_opt  # type: ignore[assignment]
        try:
            steps = [
                InstallStep(
                    action="git_clone",
                    name="Optional-Node",
                    target_path=str(opt_target),
                    source="https://example.com/optional.git",
                    status="missing",
                    required=False,
                )
            ]
            installed, skipped, failed = execute_plan(steps, dry_run=False, clone_attempts=3)
            _assert_equal("optional failed count", failed, 1)
            _assert_equal("optional installed count", installed, 0)
        finally:
            install_nodes.clone_with_retries = original_clone  # type: ignore[assignment]
        _pass(results, "retries exhausted for optional node -> tolerated")

        # Partial target left by failed clone is classified incomplete
        partial = root / "partial_manager"
        _make_incomplete_clone(partial)
        _assert_equal("partial class", inspect_clone_target(partial), "incomplete_clone")
        _assert_false("partial not valid", is_valid_git_checkout(partial))
        recovered, msg = recover_incomplete_clone(partial)
        _assert_true("partial recovered", recovered)
        _assert_false("partial removed", partial.exists())
        _pass(results, "partial target left by failed clone")

        # Valid existing checkout never deleted
        valid = root / "valid_keep"
        _init_valid_repo(valid, marker="keep-me")
        marker_before = (valid / "README.md").read_text(encoding="utf-8")
        recovered, msg = recover_incomplete_clone(valid)
        _assert_false("valid not recovered/deleted", recovered)
        _assert_true("valid preserved message", "preserved" in msg.lower())
        _assert_true("valid still exists", valid.exists())
        _assert_equal("valid marker unchanged", (valid / "README.md").read_text(encoding="utf-8"), marker_before)

        clone_fn, calls = _fake_clone_factory([(False, TRANSIENT_ERR, True)])
        result = clone_with_retries(
            "https://example.com/should-not-run.git",
            valid,
            max_attempts=3,
            backoff_seconds=(0.0, 0.0),
            sleep_fn=lambda _s: None,
            clone_fn=clone_fn,
        )
        _assert_true("valid skip ok", result.ok)
        _assert_true("valid skipped_valid", result.skipped_valid)
        _assert_equal("valid no clone calls", len(calls), 0)
        _assert_equal(
            "valid marker still unchanged",
            (valid / "README.md").read_text(encoding="utf-8"),
            marker_before,
        )
        _pass(results, "valid existing checkout is never deleted as retry cleanup")

        # Malformed/incomplete existing checkout handled safely then cloned
        malformed = root / "malformed"
        _make_incomplete_clone(malformed)
        clone_fn, calls = _fake_clone_factory([(True, "", False)])
        result = clone_with_retries(
            "https://example.com/repair.git",
            malformed,
            max_attempts=3,
            backoff_seconds=(0.0, 0.0),
            sleep_fn=lambda _s: None,
            clone_fn=clone_fn,
        )
        _assert_true("malformed repaired", result.ok)
        _assert_true("malformed recovered flag", result.recovered_incomplete)
        _assert_true("malformed now valid", is_valid_git_checkout(malformed))
        _pass(results, "malformed/incomplete existing checkout is handled safely")

        # Non-git present directory not overwritten
        nongit = root / "nongit_manual"
        nongit.mkdir(parents=True)
        (nongit / "manual.py").write_text("x=1\n", encoding="utf-8")
        _assert_equal("nongit class", inspect_clone_target(nongit), "present_non_git")
        recovered, msg = recover_incomplete_clone(nongit)
        _assert_false("nongit not deleted", recovered)
        _assert_true("nongit file remains", (nongit / "manual.py").is_file())
        clone_fn, calls = _fake_clone_factory([(True, "", False)])
        result = clone_with_retries(
            "https://example.com/nongit.git",
            nongit,
            max_attempts=3,
            backoff_seconds=(0.0, 0.0),
            sleep_fn=lambda _s: None,
            clone_fn=clone_fn,
        )
        _assert_false("nongit clone refused", result.ok)
        _assert_equal("nongit no clone", len(calls), 0)
        _pass(results, "non-git directory is not overwritten")

        # Idempotent subsequent Full launch (valid Manager remains)
        manager = root / "custom_nodes" / "ComfyUI-Manager"
        _init_valid_repo(manager, marker="manager-v1")
        clone_fn, calls = _fake_clone_factory([(True, "", False)])
        result = clone_with_retries(
            "https://example.com/manager.git",
            manager,
            max_attempts=3,
            backoff_seconds=(0.0, 0.0),
            sleep_fn=lambda _s: None,
            clone_fn=clone_fn,
        )
        _assert_true("idempotent ok", result.ok)
        _assert_true("idempotent skipped", result.skipped_valid)
        _assert_equal("idempotent no recloning", len(calls), 0)
        _assert_equal("idempotent marker", (manager / "README.md").read_text(encoding="utf-8"), "manager-v1\n")
        _pass(results, "idempotent subsequent Full launch")

        # After a failed attempt: if the target unexpectedly validates as a real
        # checkout, preserve it and treat the next loop iteration idempotently.
        become_valid = root / "failed_then_valid"
        calls_bv: list[dict] = []

        def _clone_fail_leave_valid(repo_url: str, target: Path, *, force_http1: bool = False):
            calls_bv.append({"force_http1": force_http1})
            if len(calls_bv) == 1:
                _init_valid_repo(target, marker="surprise-valid")
                return False, TRANSIENT_ERR, True
            raise SimulationFailure("should not clone after valid checkout appears")

        result = clone_with_retries(
            "https://example.com/become-valid.git",
            become_valid,
            max_attempts=3,
            backoff_seconds=(0.0, 0.0),
            sleep_fn=lambda _s: None,
            clone_fn=_clone_fail_leave_valid,
        )
        _assert_true("failed-then-valid ok", result.ok)
        _assert_true("failed-then-valid skipped_valid", result.skipped_valid)
        _assert_equal("failed-then-valid only one clone call", len(calls_bv), 1)
        _assert_true(
            "failed-then-valid preserved",
            (become_valid / "README.md").read_text(encoding="utf-8") == "surprise-valid\n",
        )
        _assert_true("failed-then-valid still valid", is_valid_git_checkout(become_valid))
        _pass(results, "incomplete cleanup; newly valid checkout preserved idempotently")

        # Standard incomplete leftover after failure is removed before retry.
        cleaned = root / "cleanup_before_retry"
        calls_cu: list[dict] = []

        def _clone_incomplete_then_ok(repo_url: str, target: Path, *, force_http1: bool = False):
            calls_cu.append(
                {
                    "force_http1": force_http1,
                    "existed_before": target.exists(),
                    "state_before": inspect_clone_target(target) if target.exists() else "missing",
                }
            )
            if len(calls_cu) == 1:
                _make_incomplete_clone(target)
                return False, TRANSIENT_ERR, True
            _assert_equal("second attempt starts clean", calls_cu[-1]["state_before"], "missing")
            if target.exists():
                shutil.rmtree(target)
            _init_valid_repo(target, marker="after-cleanup")
            return True, "", False

        result = clone_with_retries(
            "https://example.com/cleanup.git",
            cleaned,
            max_attempts=3,
            backoff_seconds=(0.0, 0.0),
            sleep_fn=lambda _s: None,
            clone_fn=_clone_incomplete_then_ok,
        )
        _assert_true("cleanup-before-retry ok", result.ok)
        _assert_true("cleanup recovered incomplete", result.recovered_incomplete)
        _assert_false("first force_http1 false", calls_cu[0]["force_http1"])
        _assert_true("second force_http1 true", calls_cu[1]["force_http1"])
        _pass(results, "incomplete clone cleaned before retry")

        # Empty dir treated as incomplete
        empty = root / "empty_dir"
        empty.mkdir()
        _assert_equal("empty incomplete", inspect_clone_target(empty), "incomplete_clone")
        _pass(results, "empty target classified incomplete")

        # Manager required classification intentional
        repo_root = find_repo_root(script_file=Path(__file__))
        registry = json.loads(
            (repo_root / "configs" / "nodes" / "node_registry.json").read_text(encoding="utf-8")
        )
        manager_entry = next(n for n in registry["nodes"] if n["name"] == "ComfyUI-Manager")
        _assert_true("manager required_for all", "all" in manager_entry.get("required_for", []))
        _pass(results, "ComfyUI-Manager remains required")

        # install_nodes source has no /prompt and review package wiring
        src = (repo_root / "core" / "comfyui" / "install_nodes.py").read_text(encoding="utf-8")
        _assert_false("no /prompt", "/prompt" in src)
        _assert_false("GIT_HTTP_VERSION reliance removed", "GIT_HTTP_VERSION" in src)
        _assert_true(
            "uses git -c http.version via builder",
            "build_git_clone_command" in src
            and "http.version=HTTP/1.1" in src
            and '"-c"' in src,
        )
        _assert_true("bounded attempts present", "DEFAULT_CLONE_ATTEMPTS" in src)
        build_src = (repo_root / "core" / "scripts" / "build_review_package.py").read_text(encoding="utf-8")
        _assert_true(
            "review package lists install_nodes or simulate",
            "install_nodes.py" in build_src or "simulate_package4101" in build_src,
        )
        _pass(results, "installer resilience markers present")

        # CLI help
        proc = subprocess.run(
            [sys.executable, str(repo_root / "core" / "comfyui" / "install_nodes.py"), "--help"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        _assert_equal("install_nodes --help", proc.returncode, 0)
        _assert_true("help mentions clone-attempts", "--clone-attempts" in proc.stdout)
        _pass(results, "install_nodes --help succeeds")

        # No Package 4.10 reproduction semantic churn in this fix
        repro = repo_root / "core" / "runtime" / "generation_reproduction.py"
        _assert_true("4.10 module untouched path exists", repro.is_file())
        _pass(results, "Package 4.10 reproduction module remains present")

    except SimulationFailure as exc:
        results.append(("FAIL", str(exc)))
        print(f"  [FAIL] {exc}")
    except Exception as exc:  # noqa: BLE001
        results.append(("FAIL", f"unexpected: {exc}"))
        print(f"  [FAIL] unexpected: {exc}")
        raise
    finally:
        for path in temp_dirs:
            shutil.rmtree(path, ignore_errors=True)

    passed = sum(1 for status, _ in results if status == "PASS")
    failed = sum(1 for status, _ in results if status == "FAIL")
    print()
    print(f"Package 4.10.1 results: {passed} passed, {failed} failed, {len(results)} total")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
