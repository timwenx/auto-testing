# Progress Notes — Round 4 (CLI Dual-Engine — Verification & Bug Fixes)

## Status: All 6 plan tasks completed in Round 1. Round 4 fixed bugs and verified.

### Verification & Fixes Applied

1. **`resolve_claude_bin()` wired up** — The function was defined in `cli_service.py` but never called. Now integrated into both `is_cli_available()` and `call_cli()` so the CLI path is properly resolved on Windows (searches APPDATA/npm, uses `which`/`shutil.which`).

2. **`batch_save_testcases` missing `@api_view` decorator** — View used `request.data` (DRF attribute) but wasn't decorated with `@api_view(['POST'])`, causing `AttributeError: 'WSGIRequest' object has no attribute 'data'`. Fixed by adding the decorator. All 9 BatchSave tests now pass.

3. **Test mock fixes** — Two tests (`test_is_cli_available_success`, `test_cli_check_default_path`) failed after wiring `resolve_claude_bin` because the function resolves the actual Windows `claude.exe` path, breaking assertion `['claude', '--version']`. Fixed by mocking `resolve_claude_bin` to pass through input unchanged.

4. **Cleaned up stray file** — Removed accidentally created `My_Test/core/cli_service.py`.

### Verification Results
- **334 tests total**: ALL PASS ✅
- **18 CLI-specific tests**: all pass
- **9 BatchSave tests**: all pass (were broken before this round)
- **Frontend build**: succeeds ✅
- **Django check**: 0 issues ✅

### Files Changed This Round
| File | Change |
|------|--------|
| `core/cli_service.py` | Wire `resolve_claude_bin()` into `is_cli_available()` and `call_cli()` |
| `core/views.py` | Add `@api_view(['POST'])` decorator to `batch_save_testcases` |
| `core/tests.py` | Mock `resolve_claude_bin` in 2 tests to prevent Windows path resolution interference |
| `.claudepotter/kb/README.md` | Update test count (334 all pass), add resolve_claude_bin docs |
