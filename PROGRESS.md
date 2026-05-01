# Progress Notes — CLI Dual-Engine Analysis

## Completed: All 6 tasks

### Changes Summary

1. **Task 1: System Settings** — Added 3 new entries to `SystemSetting.DEFAULTS`:
   - `claude_cli_path` (default: 'claude')
   - `analysis_engine` (default: 'cli')
   - `claude_cli_timeout` (default: '300')

2. **Task 2: CLI Service** — New file `core/cli_service.py`:
   - `is_cli_available(cli_path)` → runs `{cli_path} --version`, returns `(bool, str)`
   - `call_cli(prompt, cwd, model, timeout)` → subprocess.run with `-p --output-format text`
   - `get_cli_settings()` → reads from SystemSetting with defaults

3. **Task 3: Repo Analyzer Refactor** — `core/repo_analyzer.py` restructured:
   - `analyze_repo()` reads `analysis_engine` setting and routes to CLI or SDK
   - `_analyze_with_cli()` → calls `call_cli()` with cwd=repo_path, no manual code collection
   - `_analyze_with_sdk()` → original logic (search keywords + read files + API call)
   - Both paths use same `_parse_analysis_response()` and save logic

4. **Task 4: CLI Check Endpoint** — `GET /api/settings/cli-check/`:
   - `core/views.py`: `cli_check()` view function
   - `core/urls.py`: added route
   - `frontend/src/api.js`: `checkCliAvailable(cliPath)` function
   - `CodeAnalysisPanel.vue`: pre-checks CLI availability before starting analysis

5. **Task 5: Settings UI** — `Settings.vue` updated with card-based layout:
   - "代码分析引擎" card with CLI/SDK radio group
   - CLI path input with detection button (shows version or error)
   - CLI timeout number input (60-600 seconds)

6. **Task 6: Unit Tests** — 18 new tests:
   - `CliServiceTest` (10): available/not-found/nonzero, call_cli success/model/timeout/not-found/nonzero, get_settings defaults/custom
   - `RepoAnalyzerCliModeTest` (4): calls_cli, skips_code_collection, parses_json, handles_failure
   - `RepoAnalyzerSdkModeTest` (1): uses_api
   - `CliCheckEndpointTest` (3): available, not_available, default_path
   - Fixed existing `test_analyze_repo_success` to set `analysis_engine=sdk`

### Verification
- **334 tests** total (18 new), all new tests pass
- **Frontend builds** successfully
- **Django check**: 0 issues
- Pre-existing BatchSave test failures (8 errors, 1 fail) unrelated to this change

### Pre-existing changes not included in this commit
- `backend/settings.py`: LOGGING config
- `core/serializers.py`: added started_at/last_heartbeat to RepoAnalysisSerializer
