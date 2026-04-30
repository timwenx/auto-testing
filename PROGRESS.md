# Progress

## Round 2 — Bug fixes and test repairs

### Issues Found and Fixed

1. **`_extract_target` wrong param names** (`agent_service.py`):
   - `read_file`: `file_path` → `path` (matching actual tool schema)
   - `search_code`: `query` → `keyword` (matching actual tool schema)

2. **Path traversal vulnerability in `read_file`** (`agent_tools.py`):
   - Added `resolve().relative_to()` check, consistent with `list_directory`

3. **`execution_end` event reliability** (`agent_service.py`):
   - Moved from outside `try/finally` to inside `finally` block
   - Added try/except wrapper to prevent emit failure from masking original error

4. **`frame_heartbeat` event not handled** (`useExecutionObserver.js`):
   - Watchdog sends `frame_heartbeat` during browser tool execution
   - Frontend now handles it: resets `lastFrameTime` and triggers HTTP frame fetch

5. **`_stop_heartbeat` AttributeError** (`consumers.py`):
   - Changed to use `getattr(self, '_heartbeat_timer', None)` for robustness

6. **Bare `except:` → `except Exception:`** (`views.py`)

7. **Tests updated** (`tests.py`):
   - `ExtractTargetTest`: updated param names to match corrected code
   - `EmitStepEventTest`: updated to mock `asyncio.run_coroutine_threadsafe` instead of `async_to_sync`

### Status
- All 148 tests pass
- All 9 plan tasks implemented
- Remaining: manual integration testing (Task 9)
