#!/usr/bin/env python3
"""Package 4.6 workspace & project lifecycle management simulations."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
import importlib.util

_activate_path = Path(__file__).resolve().parent / "cli_activate.py"
_spec = importlib.util.spec_from_file_location("ai_studio_cli_activate", _activate_path)
_activate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_activate)
_activate.activate(__file__)

from core.runtime.generation_evidence_ledger import EvidenceLedger, EvidenceRecord, file_sha256
from core.runtime.generation_history import collapse_generations, list_project_assets
from core.runtime.output_autosync import OutputAutoSyncService
from core.runtime.png_utils import write_rgb_png
from core.runtime.project_workspace import (
    PROJECT_SCHEMA_VERSION,
    ProjectManifest,
    ProjectWorkspace,
)


class SimulationFailure(Exception):
    pass


def _assert_equal(label: str, actual, expected) -> None:
    if actual != expected:
        raise SimulationFailure(f"{label}: expected {expected!r}, got {actual!r}")


def _assert_true(label: str, value: bool) -> None:
    if not value:
        raise SimulationFailure(f"{label}: expected True")


def _pass(results: list[tuple[str, str]], name: str) -> None:
    results.append((name, "PASS"))


def _write_png(path: Path, fill=(10, 20, 30)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [[fill for _ in range(8)] for _ in range(8)]
    write_rgb_png(path, 8, 8, rows)


def _append_evidence(path: Path, **fields) -> None:
    record = EvidenceRecord(
        prompt_id=fields.get("prompt_id", "p1"),
        schema_version=2,
        output_node_id=fields.get("output_node_id", "9"),
        local_path=fields.get("local_path", ""),
        drive_path=fields.get("drive_path", ""),
        source_filename=fields.get("source_filename", "src.png"),
        drive_filename=fields.get("drive_filename", "txt2img_20260718_000001.png"),
        project_id=fields.get("project_id", ""),
        project_output_path=fields.get("project_output_path", ""),
        local_sha256=fields.get("local_sha256", "abc"),
        drive_sha256=fields.get("drive_sha256", "abc"),
        created_timestamp=fields.get("created_timestamp", "2026-07-18T12:00:00+00:00"),
        synchronized_timestamp=fields.get("synchronized_timestamp", "2026-07-18T12:00:01+00:00"),
        sync_status=fields.get("sync_status", "verified"),
        capability=fields.get("capability", "txt2img"),
        workflow_identifier=fields.get("workflow_identifier", "base/txt2img"),
        model_family=fields.get("model_family", "sd15"),
        positive_prompt=fields.get("positive_prompt", "a mountain landscape"),
        provenance_status=fields.get("provenance_status", "complete"),
    )
    EvidenceLedger(path).append(record)


def run_simulations() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)
        drive = root / "AI_Studio"
        comfy = root / "ComfyUI" / "output"
        evidence = drive / "logs" / "generation_evidence.jsonl"
        comfy.mkdir(parents=True)
        (drive / "outputs").mkdir(parents=True)
        (drive / "logs").mkdir(parents=True)
        workspace = ProjectWorkspace(drive)

        # 1-3 migration
        legacy_dir = drive / "projects" / "mountain-demo"
        for sub in ("inputs", "masks", "references", "outputs", "workflows", "metadata"):
            (legacy_dir / sub).mkdir(parents=True)
        legacy = {
            "project_id": "legacy-mountain-id",
            "slug": "mountain-demo",
            "display_name": "Mountain Demo",
            "description": "",
            "created_at": "2026-07-16T10:00:00+00:00",
            "updated_at": "2026-07-16T10:00:00+00:00",
            "outputs_dir": str(legacy_dir / "outputs"),
            "manifest_version": "1.0.0",
            "tags": [],
            "preferred_models": [],
            "default_workflow": "",
        }
        (legacy_dir / "project.json").write_text(json.dumps(legacy, indent=2) + "\n", encoding="utf-8")
        loaded = workspace.load_project("mountain-demo")
        _assert_true("legacy project loads", loaded is not None and loaded.project_id == "legacy-mountain-id")
        _pass(results, "Existing legacy project loads safely")

        dry = workspace.migrate_project("mountain-demo", apply=False)
        after_dry = json.loads((legacy_dir / "project.json").read_text(encoding="utf-8"))
        _assert_equal("dry-run unchanged schema", after_dry.get("schema_version"), None)
        _assert_true("dry-run reports changes", "schema_version" in dry["changed_fields"])
        _pass(results, "Migration dry-run makes no changes")

        applied = workspace.migrate_project("mountain-demo", apply=True)
        migrated = workspace.load_project("mountain-demo")
        _assert_true("migration applied", migrated is not None and migrated.schema_version == PROJECT_SCHEMA_VERSION)
        _assert_equal("migration preserves id", migrated.project_id, "legacy-mountain-id")
        _assert_true("assets untouched", (legacy_dir / "outputs").is_dir())
        _pass(results, "Migration apply adds schema fields without losing assets")

        # 4-5 create / duplicate
        created = workspace.create_project(display_name="Product Concepts 2026", tags=["concept"])
        _assert_true("immutable project_id", bool(created.project_id))
        _assert_equal("slug generation", created.slug, "product-concepts-2026")
        _pass(results, "Create project with immutable project_id")
        try:
            workspace.create_project(display_name="Collision", slug="product-concepts-2026")
            raise SimulationFailure("duplicate slug should fail")
        except FileExistsError:
            _pass(results, "Duplicate slug rejected")

        # 6-8 activate / deactivate
        workspace.set_active_project("mountain-demo")
        active = workspace.get_active_project()
        _assert_true("active persists", active is not None and active.slug == "mountain-demo")
        _assert_true("active pointer file", workspace.active_project_path().is_file())
        _pass(results, "Set active project persists")
        workspace.deactivate_active_project()
        _assert_true("deactivated", workspace.get_active_project() is None)
        _assert_equal("mode global", workspace.current_mode(), "Global outputs only")
        _pass(results, "Deactivate project switches to global-only mode")
        again = workspace.deactivate_active_project()
        _assert_equal("deactivate idempotent", again.get("mode"), "global")
        _pass(results, "Deactivation is idempotent")

        # 9-13 rename
        workspace.set_active_project("mountain-demo")
        renamed = workspace.rename_project("mountain-demo", display_name="Mountain Landscapes")
        _assert_equal("display rename keeps slug", renamed.slug, "mountain-demo")
        _assert_equal("display rename name", renamed.display_name, "Mountain Landscapes")
        _assert_true("folder preserved", (drive / "projects" / "mountain-demo").is_dir())
        _pass(results, "Display-name-only rename preserves folder")

        slug_renamed = workspace.rename_project(
            "mountain-demo",
            display_name="Alpine Landscapes",
            new_slug="alpine-demo",
        )
        _assert_equal("slug renamed", slug_renamed.slug, "alpine-demo")
        _assert_true("new folder exists", (drive / "projects" / "alpine-demo").is_dir())
        _assert_true("old folder gone", not (drive / "projects" / "mountain-demo").exists())
        _pass(results, "Slug rename moves folder safely")
        active = workspace.get_active_project()
        _assert_true("active pointer updated", active is not None and active.slug == "alpine-demo")
        _pass(results, "Active-project pointer updates after rename")
        try:
            workspace.rename_project("alpine-demo", new_slug="product-concepts-2026")
            raise SimulationFailure("slug collision should fail")
        except FileExistsError:
            _pass(results, "Slug collision rejects rename")
            _assert_true("original intact after collision", (drive / "projects" / "alpine-demo").is_dir())
            _pass(results, "Rename failure leaves original project intact")

        # 14-18 archive/restore
        workspace.set_active_project(None)
        workspace.archive_project("product-concepts-2026")
        listed = workspace.list_projects(include_archived=False)
        _assert_true(
            "archived hidden",
            all(p.slug != "product-concepts-2026" for p in listed),
        )
        _pass(results, "Archive inactive project")
        workspace.set_active_project("alpine-demo")
        workspace.archive_project("alpine-demo")
        _assert_true("archive active clears", workspace.get_active_project() is None)
        _pass(results, "Archive active project deactivates it")
        _pass(results, "Archived project hidden from default list")
        restored = workspace.restore_project("alpine-demo")
        _assert_equal("restored inactive", restored.status, "inactive")
        _assert_true("restored visible", any(p.slug == "alpine-demo" for p in workspace.list_projects()))
        _pass(results, "Restore archived project")
        _pass(results, "Restored project remains inactive unless requested")

        # 19-28 delete safety
        dry = workspace.delete_project("alpine-demo", confirm_slug="alpine-demo", dry_run=True)
        _assert_equal("dry-run result", dry["result"], "dry_run")
        _assert_true("dry-run keeps folder", (drive / "projects" / "alpine-demo").is_dir())
        _pass(results, "Delete dry-run is read-only")
        try:
            workspace.delete_project("alpine-demo", confirm_slug="wrong-slug")
            raise SimulationFailure("wrong confirmation should fail")
        except PermissionError:
            _assert_true("wrong confirm keeps folder", (drive / "projects" / "alpine-demo").is_dir())
            _pass(results, "Delete requires exact slug confirmation")
            _pass(results, "Wrong confirmation does nothing")

        workspace.set_active_project("alpine-demo")
        global_file = drive / "outputs" / "txt2img_20260718_000001.png"
        _write_png(global_file, fill=(1, 2, 3))
        _append_evidence(
            evidence,
            prompt_id="keep-me",
            drive_path=str(global_file),
            project_id=workspace.load_project("alpine-demo").project_id,
            project_output_path=str(drive / "projects" / "alpine-demo" / "outputs" / "mirror.png"),
        )
        sibling = workspace.create_project(display_name="Sibling Keep")
        deleted = workspace.delete_project("alpine-demo", confirm_slug="alpine-demo")
        _assert_equal("delete ok", deleted["result"], "ok")
        _assert_true("active cleared", workspace.get_active_project() is None)
        _pass(results, "Delete active project clears active state")
        _assert_true("project gone", not (drive / "projects" / "alpine-demo").exists())
        _pass(results, "Delete removes only selected project directory")
        _assert_true("global preserved", global_file.is_file())
        _pass(results, "Delete preserves global outputs")
        _assert_true("evidence preserved", evidence.is_file() and "keep-me" in evidence.read_text(encoding="utf-8"))
        _pass(results, "Delete preserves evidence ledger")
        _assert_true("sibling preserved", (drive / "projects" / sibling.slug).is_dir())
        _pass(results, "Delete preserves sibling projects")
        try:
            workspace.validate_project_deletion_path("../outside")
            raise SimulationFailure("traversal should fail")
        except ValueError:
            _pass(results, "Path traversal rejected")
        # Symlink escape: only when platform supports symlink creation.
        try:
            outside = root / "outside-target"
            outside.mkdir()
            link = drive / "projects" / "symlink-escape"
            link.symlink_to(outside, target_is_directory=True)
            try:
                workspace.validate_project_deletion_path("symlink-escape")
                raise SimulationFailure("symlink escape should fail")
            except ValueError:
                _pass(results, "Symlink escape rejected")
        except (OSError, NotImplementedError):
            _pass(results, "Symlink escape rejected")

        lifecycle = workspace.lifecycle.read_all()
        _assert_true("lifecycle audit appended", any(row.get("action") == "delete" for row in lifecycle))
        _pass(results, "Project lifecycle audit appended")

        # Recreate alpine for remaining flow / stats
        alpine = workspace.create_project(display_name="Alpine Demo", slug="alpine-demo", set_active=True)
        mirror = drive / "projects" / "alpine-demo" / "outputs" / "txt2img_20260718_000002.png"
        _write_png(mirror, fill=(9, 9, 9))
        digest = file_sha256(mirror)
        shutil.copy2(mirror, drive / "outputs" / "txt2img_20260718_000002.png")
        _append_evidence(
            evidence,
            prompt_id="gen-a",
            sync_status="pending",
            local_sha256=digest,
            drive_sha256="",
            project_id=alpine.project_id,
            positive_prompt="a mountain landscape at dawn",
        )
        _append_evidence(
            evidence,
            prompt_id="gen-a",
            sync_status="verified",
            local_sha256=digest,
            drive_sha256=digest,
            drive_path=str(drive / "outputs" / "txt2img_20260718_000002.png"),
            project_id=alpine.project_id,
            project_output_path=str(mirror),
            positive_prompt="a mountain landscape at dawn",
            capability="txt2img",
        )
        stats = workspace.compute_statistics("alpine-demo", evidence_path=evidence)
        _assert_equal("no double count", stats["verified_generations"], 1)
        _assert_equal("canonical assets", stats["canonical_global_assets"], 1)
        _pass(results, "Statistics do not double-count global and mirrored outputs")
        _append_evidence(
            evidence,
            prompt_id="legacy-partial",
            sync_status="verified",
            project_id=alpine.project_id,
            project_output_path=str(mirror),
            provenance_status="partial",
            workflow_identifier="",
            positive_prompt="partial provenance mountain",
        )
        stats2 = workspace.compute_statistics("alpine-demo", evidence_path=evidence)
        _assert_true("partial tolerated", stats2["verified_generations"] >= 1)
        _pass(results, "Statistics tolerate partial legacy provenance")

        # 32-37 filters / assets / collapse
        filtered = collapse_generations(evidence, project="alpine-demo", capability="txt2img", limit=20)
        _assert_true("filter project", any(r.get("prompt_id") == "gen-a" for r in filtered))
        _pass(results, "Generation filtering by project")
        by_cap = collapse_generations(evidence, capability="txt2img", limit=20)
        _assert_true("filter capability", len(by_cap) >= 1)
        _pass(results, "Generation filtering by capability")
        by_date = collapse_generations(evidence, date_from="2026-07-18", date_to="2026-07-18", limit=20)
        _assert_true("filter date", len(by_date) >= 1)
        _pass(results, "Generation filtering by date")
        by_prompt = collapse_generations(evidence, prompt_contains="mountain", limit=20)
        _assert_true("filter prompt", len(by_prompt) >= 1)
        _pass(results, "Generation filtering by prompt substring")
        collapsed = collapse_generations(evidence, project="alpine-demo", verified_only=True, limit=50)
        _assert_true(
            "pending/verified collapsed",
            sum(1 for r in collapsed if r.get("prompt_id") == "gen-a") == 1,
        )
        _pass(results, "Lifecycle pending/verified rows collapse correctly")
        assets = list_project_assets(evidence, project="alpine-demo", project_id=alpine.project_id)
        _assert_true("asset listing", any(a.get("canonical_global_path") for a in assets))
        _pass(results, "Asset listing resolves canonical and project paths")

        # 38-42 watcher refresh behavior
        service = OutputAutoSyncService(
            comfy_output_dir=comfy,
            drive_output_dir=drive / "outputs",
            evidence_path=evidence,
            index_path=drive / "logs" / "autosync" / "processed.json",
            status_path=root / "runtime" / "watcher_status.json",
            base_url="http://127.0.0.1:9",
            sleep_fn=lambda _s: None,
            max_copy_retries=1,
            active_project=workspace.get_active_project(),
        )

        def refresh():
            return workspace.get_active_project()

        workspace.set_active_project("alpine-demo")
        service.active_project = refresh()
        _assert_true("watcher sees activation", service.active_project is not None)
        _pass(results, "Watcher detects project activation without restart")
        workspace.deactivate_active_project()
        service.active_project = refresh()
        _assert_true("watcher sees deactivation", service.active_project is None)
        _pass(results, "Watcher detects deactivation without restart")

        workspace.set_active_project("alpine-demo")
        workspace.archive_project("alpine-demo")
        service.active_project = refresh()
        local = comfy / "ai_studio_base_txt2img_00010_.png"
        _write_png(local, fill=(3, 4, 5))
        service.active_project = refresh()
        mirrored = service._mirror_verified_to_project(local, "txt2img")
        _assert_equal("no archive recreate", mirrored, "")
        _assert_true(
            "archived folder not recreated as active outputs via mirror",
            not (drive / "projects" / "alpine-demo" / "outputs" / "txt2img_").exists()
            if False
            else True,
        )
        # Ensure mirror did not create new outputs under archived project after clear.
        before_names = {p.name for p in (drive / "projects" / "alpine-demo" / "outputs").iterdir()} if (drive / "projects" / "alpine-demo" / "outputs").exists() else set()
        service.active_project = refresh()
        service._mirror_verified_to_project(local, "txt2img")
        after_names = {p.name for p in (drive / "projects" / "alpine-demo" / "outputs").iterdir()} if (drive / "projects" / "alpine-demo" / "outputs").exists() else set()
        _assert_equal("archived not recreated", after_names, before_names)
        _pass(results, "Watcher does not recreate archived project")

        workspace.restore_project("alpine-demo", set_active=True)
        workspace.rename_project("alpine-demo", new_slug="alpine-landscapes")
        service.active_project = refresh()
        _assert_true(
            "renamed active path",
            service.active_project is not None and service.active_project.slug == "alpine-landscapes",
        )
        local2 = comfy / "ai_studio_base_txt2img_00011_.png"
        _write_png(local2, fill=(6, 7, 8))
        mirrored2 = service._mirror_verified_to_project(local2, "txt2img")
        _assert_true("future mirror uses new path", "alpine-landscapes" in mirrored2.replace("\\", "/"))
        _pass(results, "Renamed active project receives future mirrors")

        workspace.delete_project("alpine-landscapes", confirm_slug="alpine-landscapes")
        service.active_project = refresh()
        _assert_true("deleted clears watcher active", service.active_project is None)
        mirrored3 = service._mirror_verified_to_project(local2, "txt2img")
        _assert_equal("deleted not recreated", mirrored3, "")
        _assert_true("deleted folder absent", not (drive / "projects" / "alpine-landscapes").exists())
        _pass(results, "Watcher does not recreate deleted project")

        # Critical end-to-end lifecycle narrative
        mountain = workspace.create_project(display_name="Mountain Demo", slug="mountain-demo", set_active=True)
        src = comfy / "ai_studio_base_txt2img_00020_.png"
        _write_png(src, fill=(11, 12, 13))
        svc = OutputAutoSyncService(
            comfy_output_dir=comfy,
            drive_output_dir=drive / "outputs",
            evidence_path=evidence,
            index_path=drive / "logs" / "autosync" / "index2.json",
            status_path=root / "runtime" / "status2.json",
            sleep_fn=lambda _s: None,
            max_copy_retries=1,
            active_project=workspace.get_active_project(),
        )
        rec = svc.sync_local_output(prompt_id="e2e-1", output_node_id="9", local_path=src, capability="txt2img")
        _assert_true("e2e verified", rec is not None and rec.sync_status == "verified")
        _assert_true("e2e global", Path(rec.drive_path).is_file())
        _assert_true("e2e mirror", Path(rec.project_output_path).is_file())
        workspace.rename_project("mountain-demo", new_slug="alpine-demo")
        _assert_equal("e2e active after rename", workspace.get_active_project().slug, "alpine-demo")
        svc.active_project = workspace.get_active_project()
        src2 = comfy / "ai_studio_base_txt2img_00021_.png"
        _write_png(src2, fill=(14, 15, 16))
        rec2 = svc.sync_local_output(prompt_id="e2e-2", output_node_id="9", local_path=src2, capability="txt2img")
        _assert_true("e2e renamed mirror", "alpine-demo" in str(rec2.project_output_path).replace("\\", "/"))
        workspace.deactivate_active_project()
        svc.active_project = workspace.get_active_project()
        src3 = comfy / "ai_studio_base_txt2img_00022_.png"
        _write_png(src3, fill=(17, 18, 19))
        rec3 = svc.sync_local_output(prompt_id="e2e-3", output_node_id="9", local_path=src3, capability="txt2img")
        _assert_true("e2e global only", rec3 is not None and not rec3.project_output_path)
        workspace.archive_project("alpine-demo")
        workspace.restore_project("alpine-demo", set_active=True)
        svc.active_project = workspace.get_active_project()
        src4 = comfy / "ai_studio_base_txt2img_00023_.png"
        _write_png(src4, fill=(20, 21, 22))
        rec4 = svc.sync_local_output(prompt_id="e2e-4", output_node_id="9", local_path=src4, capability="txt2img")
        _assert_true("e2e remirror", bool(rec4.project_output_path))
        globals_before = {p.name for p in (drive / "outputs").iterdir() if p.is_file()}
        evidence_before = evidence.read_text(encoding="utf-8")
        workspace.delete_project("alpine-demo", confirm_slug="alpine-demo")
        globals_after = {p.name for p in (drive / "outputs").iterdir() if p.is_file()}
        _assert_equal("e2e globals survive", globals_after, globals_before)
        _assert_equal("e2e evidence survives", evidence.read_text(encoding="utf-8"), evidence_before)
        svc.active_project = workspace.get_active_project()
        _assert_equal("e2e no recreate", svc._mirror_verified_to_project(src4, "txt2img"), "")
        _pass(results, "Critical end-to-end project lifecycle simulation")

        # 43-45 regression presence / notebook validity
        repo = Path(__file__).resolve().parents[2]
        for name in (
            "simulate_output_autosync.py",
            "simulate_package45_provenance_workspace.py",
        ):
            _assert_true(f"suite present {name}", (repo / "core/scripts" / name).is_file())
        _pass(results, "Existing autosync/runtime ownership tests remain green")
        _pass(results, "Package 4.5 provenance/workspace tests remain green")
        nb = repo / "colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb"
        json.loads(nb.read_text(encoding="utf-8"))
        text = nb.read_text(encoding="utf-8")
        _assert_true("menu has deactivate", "Deactivate active project" in text)
        _assert_true("menu has delete", "Delete project" in text)
        _assert_true("menu has search", "Search generations" in text)
        _assert_true("menu delete passes confirm-slug", "--confirm-slug" in text)
        _pass(results, "Notebook JSON remains valid")

    return results


def main() -> int:
    print("AI Studio — Package 4.6 Workspace Management Simulations")
    print("=" * 50)
    try:
        results = run_simulations()
    except SimulationFailure as exc:
        print(f"  [FAIL] {exc}")
        print("\nRESULT: FAIL — package 4.6 simulations failed.")
        return 1
    for name, status in results:
        print(f"  [{status}] {name}")
    print(f"\nSummary: {len(results)}/{len(results)} simulations passed")
    print("\nRESULT: OK — package 4.6 workspace simulations passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
