# Dogfooding Checklist — Workspace Foundation (Package 4.5)

## Project workspace

1. `python core/scripts/create_project.py --name "Dogfood Test"`
2. `python core/scripts/list_projects.py`
3. `python core/scripts/set_active_project.py --slug dogfood-test`
4. `python core/scripts/show_project.py --slug dogfood-test`

## Project-aware outputs

5. With active project set, generate txt2img (no manual sync).
6. Confirm global Drive output under `AI_Studio/outputs/` still written.
7. Confirm evidence records `project_id` and `project_output_path` when project mirror succeeds.
8. Confirm no unnecessary duplicate when project output already contains same SHA-256.

## Workflow catalog and export

9. `python core/scripts/workflow_catalog.py --summary`
10. Prepare inpainting workflow — confirm Drive copy under `AI_Studio/workflows/prepared/`.
11. Confirm canonical reference workflows in repo remain unchanged.

## Generation history

12. `python core/scripts/report_generation_history.py --summary`
13. `python core/scripts/list_generations.py`

## No-project mode (backward compatibility)

14. Clear active project: `python core/scripts/set_active_project.py --clear`
15. Generate again — confirm global-only persistence still works.

## Pass / Fail

**PASS:** projects create/list/activate cleanly, catalog shows runtime/quality/production, prepared workflows export to Drive, no-project mode unchanged.

**FAIL:** silent project overwrite, automatic Drive migration/deletion, or broken global output path.
