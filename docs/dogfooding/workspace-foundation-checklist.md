# Dogfooding Checklist — Workspace & Asset Management (Package 4.6)

## Operating model

**Global mode** (no active project):

- verified outputs go only to `AI_Studio/outputs/`

**Project mode** (active project selected):

- verified outputs go to `AI_Studio/outputs/` (canonical archive)
- a managed mirror is written to `AI_Studio/projects/<slug>/outputs/`

Active project selection persists across fresh Colab runtimes via
`AI_Studio/settings/active_project.json` until you:

- switch to another project
- deactivate the active project
- archive the active project
- delete the active project

Do **not** manually delete project folders in Google Drive unless recovering a
damaged workspace and following documented recovery steps. Use AI Studio delete
instead.

## Project lifecycle

1. `python core/scripts/create_project.py --name "Dogfood Test"`
2. `python core/scripts/list_projects.py`
3. `python core/scripts/set_active_project.py --slug dogfood-test`
4. `python core/scripts/show_project.py --project dogfood-test`
5. `python core/scripts/deactivate_project.py` — confirm global-only mode
6. Reactivate, then rename display name only:
   `python core/scripts/rename_project.py --project dogfood-test --name "Dogfood Renamed"`
7. Optional slug rename:
   `python core/scripts/rename_project.py --project dogfood-test --name "Alpine" --new-slug alpine-demo`
8. Archive / restore:
   `python core/scripts/archive_project.py --project alpine-demo --yes`
   `python core/scripts/restore_project.py --project alpine-demo`
9. Statistics:
   `python core/scripts/project_statistics.py --project alpine-demo`
10. Delete dry-run, then exact confirmation:
    `python core/scripts/delete_project.py --project alpine-demo --dry-run`
    `python core/scripts/delete_project.py --project alpine-demo --confirm-slug alpine-demo`

Notebook delete (Package 4.6.1): Workspace menu collects the exact slug in the
notebook, then launches `delete_project.py --project … --confirm-slug …`.
Do not rely on interactive stdin inside the subprocess — `run_repo_python`
does not forward it. Direct shell usage may still omit `--confirm-slug` and
confirm interactively when stdin is a TTY.

Deleting a project:
- removes the managed project folder and project mirrors (including `projects/<slug>/generations/`)
- does **not** delete canonical files under `AI_Studio/outputs/`
- does **not** erase historical generation evidence or global snapshots under `AI_Studio/generations/`
- Google Drive's web interface may take a short time to reflect folder deletion

## Generation snapshots (Package 4.7)

Verified outputs automatically create immutable snapshots under:
- Global: `AI_Studio/generations/<generation_id>/`
- Project: `AI_Studio/projects/<slug>/generations/<generation_id>/`

Each snapshot contains `metadata.json`, `workflow.json`, and `manifest.json` (written last).
The canonical image remains under `AI_Studio/outputs/`.

1. `python core/scripts/list_generations.py` — shows generation ID and snapshot status
2. `python core/scripts/generation_info.py --generation-id gen_<uuid>`
3. `python core/scripts/export_generation.py --generation-id gen_<uuid>`
4. `python core/scripts/validate_generation_snapshot.py --generation-id gen_<uuid>`
5. `python core/scripts/migrate_generation_snapshots.py --dry-run`

Deleting a project:

- removes the managed project folder and project mirrors
- does **not** delete canonical files under `AI_Studio/outputs/`
- does **not** erase historical generation evidence
- appends a lifecycle audit row to `AI_Studio/logs/project_lifecycle.jsonl`

## Migration (Package 4.5 projects)

11. `python core/scripts/migrate_projects.py --dry-run`
12. `python core/scripts/migrate_projects.py --apply`

Dry-run is fully read-only. Apply adds schema fields / project_id defaults
without renaming folders or touching assets. Malformed metadata is reported,
not silently overwritten.

## Project-aware outputs

13. With active project set, generate txt2img (no manual sync).
14. Confirm global Drive output under `AI_Studio/outputs/` still written.
15. Confirm evidence records `project_id` and `project_output_path` when project mirror succeeds.
16. Deactivate, generate again — confirm global-only (no project mirror).
17. Confirm watcher picks up activate/deactivate/rename without restart.

## Generation history & assets

18. `python core/scripts/list_generations.py --project alpine-demo --capability txt2img`
19. `python core/scripts/list_generations.py --prompt-contains mountain --date-from 2026-07-01`
20. `python core/scripts/list_project_assets.py --project alpine-demo`
21. `python core/scripts/workflow_catalog.py --summary`

## Control Panel menu (option 9)

```
=== Workspace / Projects ===
1. List projects
2. Create project
3. Switch active project
4. Show active project
5. Deactivate active project
6. Rename project
7. Archive project
8. Restore archived project
9. Delete project
10. Project statistics
11. Workflow catalog
12. Recent generations
13. Search generations
0. Back
```

## Pass / Fail

**PASS:** create/switch/deactivate/rename/archive/restore/delete work safely;
global outputs and evidence survive project deletion; default list hides archived
projects; watcher does not recreate archived/deleted project folders; Package
4.5.2 autosync/runtime ownership remains green.

**FAIL:** silent project overwrite, automatic folder rename on migrate, deletion
of `AI_Studio/outputs/` or evidence, path traversal, or watcher recreating
deleted/archived projects.
