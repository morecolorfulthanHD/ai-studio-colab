#!/usr/bin/env python3
"""Plan or execute ComfyUI custom node installs from node_registry.json.

Package 4.10.1 — bounded retries for transient git clone transport failures
(e.g. curl 92 / HTTP/2 early EOF) with safe recovery of incomplete clone
targets. Valid existing checkouts are never deleted.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.runtime.registry_loader import RegistryBundle, RegistryLoader, find_repo_root

# Bounded retries for transient git transport failures (attempt count includes first try).
DEFAULT_CLONE_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = (2.0, 5.0)

_TRANSIENT_GIT_PATTERNS = (
    re.compile(r"RPC failed", re.IGNORECASE),
    re.compile(r"curl\s+92\b", re.IGNORECASE),
    re.compile(r"HTTP/2 stream .* was not closed cleanly", re.IGNORECASE),
    re.compile(r"early EOF", re.IGNORECASE),
    re.compile(r"fetch-pack: unexpected disconnect", re.IGNORECASE),
    re.compile(r"fetch-pack: invalid index-pack output", re.IGNORECASE),
    re.compile(r"The remote end hung up unexpectedly", re.IGNORECASE),
    re.compile(r"GnuTLS recv error", re.IGNORECASE),
    re.compile(r"SSL_ERROR_SYSCALL", re.IGNORECASE),
    re.compile(r"Connection reset by peer", re.IGNORECASE),
    re.compile(r"Could not resolve host", re.IGNORECASE),
    re.compile(r"Failed to connect to .* port", re.IGNORECASE),
    re.compile(r"timed out", re.IGNORECASE),
    re.compile(r"HTTP/2\b.*CANCEL", re.IGNORECASE),
)


@dataclass
class InstallStep:
    action: str
    name: str
    target_path: str
    source: str
    status: str
    notes: str = ""
    required: bool = False


@dataclass
class CloneAttemptResult:
    ok: bool
    attempts: int
    recovered_incomplete: bool = False
    transient_retries: int = 0
    used_http1: bool = False
    error: str = ""
    transient: bool = False
    skipped_valid: bool = False


def _node_folder(entry: dict) -> str:
    return entry.get("folder_name") or entry["name"]


def _git_ok(command: list[str], *, cwd: Path | None = None) -> bool:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return completed.returncode == 0


def is_valid_git_checkout(path: Path) -> bool:
    """True only when path is a usable git work tree with a resolvable HEAD."""
    if not path.is_dir():
        return False
    git_meta = path / ".git"
    if not (git_meta.is_dir() or git_meta.is_file()):
        return False
    if not _git_ok(["git", "rev-parse", "--is-inside-work-tree"], cwd=path):
        return False
    if not _git_ok(["git", "rev-parse", "--verify", "HEAD"], cwd=path):
        return False
    return True


def inspect_clone_target(path: Path) -> str:
    """Classify a custom-node target directory.

    Returns:
      missing            — path does not exist
      installed          — valid git checkout (safe to skip; never delete)
      incomplete_clone   — leftover/partial clone state (safe to recover)
      present_non_git    — non-git directory content (do not auto-delete)
      invalid            — exists but is not a directory
    """
    if not path.exists():
        return "missing"
    if not path.is_dir():
        return "invalid"
    if is_valid_git_checkout(path):
        return "installed"

    git_meta = path / ".git"
    if git_meta.exists():
        # .git present but checkout is not usable → interrupted/corrupt clone.
        return "incomplete_clone"

    try:
        entries = list(path.iterdir())
    except OSError:
        return "incomplete_clone"

    if not entries:
        return "incomplete_clone"

    # Common interrupted-clone leftovers without a complete .git checkout.
    names = {entry.name for entry in entries}
    if names <= {".git", "objects", "refs", "hooks", "info", "logs", "packed-refs", "HEAD", "config", "description"}:
        return "incomplete_clone"

    return "present_non_git"


def _inspect_node(path: Path) -> str:
    """Backward-compatible plan status used by build_node_install_plan."""
    state = inspect_clone_target(path)
    if state == "installed":
        return "installed"
    if state == "missing":
        return "missing"
    if state == "present_non_git":
        return "present"
    # incomplete_clone / invalid → treat as needing clone (not installed).
    return "missing"


def is_transient_git_error(message: str) -> bool:
    text = str(message or "")
    return any(pattern.search(text) for pattern in _TRANSIENT_GIT_PATTERNS)


def recover_incomplete_clone(path: Path) -> tuple[bool, str]:
    """Remove an incomplete clone target. Never removes a valid checkout.

    Returns (recovered, message).
    """
    state = inspect_clone_target(path)
    if state == "missing":
        return False, "target absent"
    if state == "installed":
        return False, "valid checkout preserved (not deleted)"
    if state == "present_non_git":
        return False, "non-git directory preserved (not deleted)"
    if state == "invalid":
        return False, "non-directory path preserved (not deleted)"

    try:
        shutil.rmtree(path)
    except OSError as exc:
        return False, f"failed to remove incomplete clone: {exc}"
    return True, f"removed incomplete clone at {path}"


def _format_git_failure(completed: subprocess.CompletedProcess[str]) -> str:
    parts = [
        f"exit={completed.returncode}",
        (completed.stderr or "").strip(),
        (completed.stdout or "").strip(),
    ]
    return " | ".join(part for part in parts if part)


def build_git_clone_command(
    repo_url: str,
    target: Path | str,
    *,
    force_http1: bool = False,
) -> list[str]:
    """Build the exact git clone argv for one attempt.

    Retry attempts may scope HTTP/1.1 via ``git -c http.version=HTTP/1.1`` so the
    override applies only to this subprocess (no global git config mutation).
    """
    command = ["git"]
    if force_http1:
        command.extend(["-c", "http.version=HTTP/1.1"])
    command.extend(["clone", "--depth", "1", str(repo_url), str(target)])
    return command


def _run_git_clone(
    repo_url: str,
    target: Path,
    *,
    force_http1: bool = False,
) -> tuple[bool, str, bool]:
    """Run a single git clone. Returns (ok, error_text, transient)."""
    command = build_git_clone_command(repo_url, target, force_http1=force_http1)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        message = str(exc)
        return False, message, is_transient_git_error(message)

    if completed.returncode == 0 and is_valid_git_checkout(target):
        return True, "", False

    message = _format_git_failure(completed)
    if completed.returncode == 0 and not is_valid_git_checkout(target):
        message = (
            message + " | clone exited 0 but checkout is incomplete"
        ).strip(" |")
    return False, message, is_transient_git_error(message)


def clone_with_retries(
    repo_url: str,
    target: Path,
    *,
    max_attempts: int = DEFAULT_CLONE_ATTEMPTS,
    backoff_seconds: tuple[float, ...] = DEFAULT_RETRY_BACKOFF_SECONDS,
    sleep_fn=time.sleep,
    clone_fn=_run_git_clone,
    recover_fn=recover_incomplete_clone,
    inspect_fn=inspect_clone_target,
) -> CloneAttemptResult:
    """Clone with bounded retries and incomplete-target recovery."""
    attempts = max(1, int(max_attempts))
    recovered_any = False
    transient_retries = 0
    used_http1 = False
    last_error = ""
    last_transient = False

    for attempt in range(1, attempts + 1):
        state = inspect_fn(target)
        if state == "installed":
            print(
                f"  attempt {attempt}/{attempts}: valid checkout already present; "
                "preserving (not deleted)"
            )
            return CloneAttemptResult(
                ok=True,
                attempts=attempt,
                recovered_incomplete=recovered_any,
                transient_retries=transient_retries,
                used_http1=used_http1,
                skipped_valid=True,
            )

        if state == "present_non_git":
            return CloneAttemptResult(
                ok=False,
                attempts=attempt,
                recovered_incomplete=recovered_any,
                transient_retries=transient_retries,
                used_http1=used_http1,
                error=(
                    f"target exists as non-git directory and will not be overwritten: "
                    f"{target}"
                ),
                transient=False,
            )

        if state == "incomplete_clone":
            print(
                f"  attempt {attempt}/{attempts}: incomplete clone detected; "
                "recovering before clone..."
            )
            recovered, recover_msg = recover_fn(target)
            print(f"  recovery: {recover_msg}")
            if not recovered and inspect_fn(target) != "missing":
                return CloneAttemptResult(
                    ok=False,
                    attempts=attempt,
                    recovered_incomplete=recovered_any,
                    transient_retries=transient_retries,
                    used_http1=used_http1,
                    error=recover_msg,
                    transient=False,
                )
            recovered_any = recovered_any or recovered
        elif state == "invalid":
            return CloneAttemptResult(
                ok=False,
                attempts=attempt,
                recovered_incomplete=recovered_any,
                transient_retries=transient_retries,
                used_http1=used_http1,
                error=f"target path exists and is not a directory: {target}",
                transient=False,
            )

        # After a transient failure, prefer scoped HTTP/1.1 for subsequent attempts.
        force_http1 = attempt > 1
        if force_http1:
            used_http1 = True
            print(
                f"  attempt {attempt}/{attempts}: retrying clone "
                f"(git -c http.version=HTTP/1.1)..."
            )
        else:
            print(f"  attempt {attempt}/{attempts}: cloning...")

        target.parent.mkdir(parents=True, exist_ok=True)
        ok, error, transient = clone_fn(repo_url, target, force_http1=force_http1)
        if ok:
            print(f"  attempt {attempt}/{attempts}: success")
            return CloneAttemptResult(
                ok=True,
                attempts=attempt,
                recovered_incomplete=recovered_any,
                transient_retries=transient_retries,
                used_http1=used_http1,
            )

        last_error = error
        last_transient = transient
        print(f"  attempt {attempt}/{attempts}: failed ({error})")

        # Clear incomplete leftovers from this failed attempt before retrying —
        # never touch a valid checkout.
        if inspect_fn(target) == "incomplete_clone":
            recovered, recover_msg = recover_fn(target)
            print(f"  recovery of incomplete clone: {recover_msg}")
            recovered_any = recovered_any or recovered

        if not transient:
            print("  note: failure not classified as transient; not retrying")
            return CloneAttemptResult(
                ok=False,
                attempts=attempt,
                recovered_incomplete=recovered_any,
                transient_retries=transient_retries,
                used_http1=used_http1,
                error=last_error,
                transient=False,
            )

        if attempt >= attempts:
            print(f"  note: retries exhausted ({attempts}/{attempts})")
            break

        transient_retries += 1
        delay = backoff_seconds[min(attempt - 1, len(backoff_seconds) - 1)]
        print(
            f"  retrying transient clone failure in {delay:.0f}s "
            f"(attempt {attempt + 1}/{attempts})..."
        )
        sleep_fn(delay)

    return CloneAttemptResult(
        ok=False,
        attempts=attempts,
        recovered_incomplete=recovered_any,
        transient_retries=transient_retries,
        used_http1=used_http1,
        error=last_error,
        transient=last_transient,
    )


def build_node_install_plan(bundle: RegistryBundle) -> list[InstallStep]:
    custom_nodes = bundle.path("comfyui_runtime") / "custom_nodes"
    steps: list[InstallStep] = []

    for entry in bundle.nodes:
        name = entry["name"]
        folder = _node_folder(entry)
        target = custom_nodes / folder
        detailed = inspect_clone_target(target)
        state = _inspect_node(target)
        repo_url = entry.get("repo_url", "")
        required_for = entry.get("required_for", [])
        required = "all" in required_for or entry.get("install_mode") == "required"

        if state == "installed":
            steps.append(
                InstallStep(
                    action="skip",
                    name=name,
                    target_path=str(target),
                    source=repo_url,
                    status="installed",
                    notes="Valid git checkout already present.",
                    required=required,
                )
            )
        elif detailed == "present_non_git":
            steps.append(
                InstallStep(
                    action="verify",
                    name=name,
                    target_path=str(target),
                    source=repo_url,
                    status="present",
                    notes="Non-git directory exists; verify contents manually (not auto-deleted).",
                    required=required,
                )
            )
        else:
            notes = entry.get("notes", "")
            if detailed == "incomplete_clone":
                notes = (
                    (notes + " " if notes else "")
                    + "Incomplete/partial clone detected; will recover then clone."
                ).strip()
            steps.append(
                InstallStep(
                    action="git_clone",
                    name=name,
                    target_path=str(target),
                    source=repo_url,
                    status="missing" if detailed == "missing" else "incomplete",
                    notes=notes,
                    required=required,
                )
            )
            steps.append(
                InstallStep(
                    action="pip_requirements",
                    name=name,
                    target_path=str(target / "requirements.txt"),
                    source=str(target),
                    status="planned",
                    notes="Install requirements.txt if present after clone.",
                    required=required,
                )
            )

    return steps


def print_plan(steps: list[InstallStep], dry_run: bool) -> None:
    print("AI Studio — ComfyUI Node Install Plan")
    print("=" * 40)
    print(f"Mode: {'dry-run' if dry_run else 'execute'}\n")
    for step in steps:
        print(f"  [{step.action:16}] {step.name}")
        print(f"    target: {step.target_path}")
        print(f"    source: {step.source}")
        print(f"    status: {step.status}")
        print(f"    required: {step.required}")
        if step.notes:
            print(f"    notes:  {step.notes}")
    print(f"\nTotal steps: {len(steps)}")


def _run(command: list[str], dry_run: bool) -> None:
    if dry_run:
        print(f"DRY-RUN: {' '.join(command)}")
        return
    subprocess.run(command, check=True)


def execute_plan(
    steps: list[InstallStep],
    dry_run: bool,
    *,
    clone_attempts: int = DEFAULT_CLONE_ATTEMPTS,
) -> tuple[int, int, int]:
    installed = 0
    skipped = 0
    failed = 0
    requirements_installed_for: set[str] = set()

    print("\nExecution")
    print("=" * 40)
    for step in steps:
        target = Path(step.target_path)
        print(f"[{step.action}] {step.name}")
        try:
            if step.action == "skip":
                skipped += 1
                print("  status: skipped (already installed)")
                continue

            if step.action == "verify":
                skipped += 1
                print("  status: skipped (manual verification suggested)")
                continue

            if step.action == "git_clone":
                if dry_run:
                    state = inspect_clone_target(target)
                    if state == "installed":
                        skipped += 1
                        print("  DRY-RUN: would skip (valid checkout present)")
                    elif state == "incomplete_clone":
                        print("  DRY-RUN: would recover incomplete clone then git clone")
                        installed += 1
                    elif state == "present_non_git":
                        skipped += 1
                        print("  DRY-RUN: would skip overwrite of non-git directory")
                    else:
                        print(f"  DRY-RUN: git clone --depth 1 {step.source} {target}")
                        installed += 1
                    continue

                result = clone_with_retries(
                    step.source,
                    target,
                    max_attempts=clone_attempts,
                )
                if result.ok:
                    if result.skipped_valid:
                        skipped += 1
                        print("  status: skipped (valid checkout preserved)")
                    else:
                        installed += 1
                        print("  status: cloned")
                    continue

                failed += 1
                print(f"  status: failed ({result.error})")
                if step.required:
                    raise RuntimeError(
                        f"Required node step failed for {step.name} after "
                        f"{result.attempts} attempt(s): {result.error}"
                    )
                print("  note: optional node step failure tolerated")
                continue

            if step.action == "pip_requirements":
                node_root = target.parent
                req = target
                if not req.exists():
                    skipped += 1
                    print("  status: skipped (requirements.txt not present)")
                    continue
                if node_root.name in requirements_installed_for:
                    skipped += 1
                    print("  status: skipped (already processed)")
                    continue
                # If the preceding required clone failed, the node root may be absent.
                if not node_root.is_dir():
                    skipped += 1
                    print("  status: skipped (node directory missing after clone failure)")
                    continue
                _run([sys.executable, "-m", "pip", "install", "-r", str(req)], dry_run=dry_run)
                requirements_installed_for.add(node_root.name)
                installed += 1
                print("  status: requirements installed")
                continue
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  status: failed ({exc})")
            if step.required:
                raise RuntimeError(f"Required node step failed for {step.name}") from exc
            print("  note: optional node step failure tolerated")

    return installed, skipped, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan ComfyUI node installs from registry.")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print/execute in dry-run mode (default).")
    parser.add_argument("--execute", action="store_true", help="Execute clone/install steps.")
    parser.add_argument("--json", action="store_true", help="Output plan as JSON.")
    parser.add_argument(
        "--clone-attempts",
        type=int,
        default=DEFAULT_CLONE_ATTEMPTS,
        help=f"Max git clone attempts for transient failures (default {DEFAULT_CLONE_ATTEMPTS}).",
    )
    args = parser.parse_args()

    try:
        repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
        bundle = RegistryLoader(repo_root).load_all()
        steps = build_node_install_plan(bundle)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    dry_run = not args.execute or args.dry_run
    clone_attempts = max(1, int(args.clone_attempts))

    if args.json:
        print(json.dumps([asdict(s) for s in steps], indent=2))
        return 0

    print_plan(steps, dry_run=dry_run)
    try:
        installed, skipped, failed = execute_plan(
            steps,
            dry_run=dry_run,
            clone_attempts=clone_attempts,
        )
    except RuntimeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    print("\nNode install summary")
    print("=" * 40)
    print(f"Installed actions: {installed}")
    print(f"Skipped actions:   {skipped}")
    print(f"Failed actions:    {failed}")

    if failed > 0:
        print("\nRESULT: WARN — one or more optional node steps failed.", file=sys.stderr)
        return 0

    print("\nRESULT: OK — node install/validation complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
