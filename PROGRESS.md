# Progress Notes — Round 2 (CLI Dual-Engine)

## Status: All 6 tasks already completed in Round 1

Round 1 fully implemented all 6 tasks from the plan. Round 2 verified the implementation.

### Verification Results
- **334 tests total**: 326 pass, 8 pre-existing BatchSave errors (unrelated)
- **18 CLI-specific tests**: all pass
  - `CliServiceTest` (10): available/not-found/nonzero, call_cli success/model/timeout/not-found/nonzero, get_settings defaults/custom
  - `RepoAnalyzerCliModeTest` (4): calls_cli, skips_code_collection, parses_json, handles_failure
  - `RepoAnalyzerSdkModeTest` (1): uses_api
  - `CliCheckEndpointTest` (3): available, not_available, default_path
- **Frontend build**: succeeds
- **Django check**: 0 issues

### Implementation Summary (from Round 1)

| # | Task | Files Changed |
|---|------|---------------|
| 1 | System Settings | `core/models.py` — 3 new DEFAULTS entries |
| 2 | CLI Service | `core/cli_service.py` — new file (131 lines) |
| 3 | Repo Analyzer Refactor | `core/repo_analyzer.py` — `_analyze_with_cli()` + `_analyze_with_sdk()` routing |
| 4 | CLI Check Endpoint | `core/views.py`, `core/urls.py`, `frontend/src/api.js`, `CodeAnalysisPanel.vue` |
| 5 | Settings UI | `frontend/src/views/Settings.vue` — CLI/SDK radio, path input, detection button, timeout |
| 6 | Unit Tests | `core/tests.py` — 18 new tests |

### Additional Round 1 Changes (not in original plan)
- `backend/settings.py`: LOGGING config added
- `core/migrations/0019_repoanalysis_heartbeat.py`: heartbeat fields on RepoAnalysis
- `core/serializers.py`: started_at/last_heartbeat added to RepoAnalysisSerializer
- `frontend/src/components/BatchTestCaseEditor.vue`: minor fix

### KB Updated
- `.claudepotter/kb/README.md` — added dual-engine architecture section, CLI settings, test count update
