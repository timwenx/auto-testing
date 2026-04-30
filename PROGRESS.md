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

## Round 3 — Verification and finalization

### Review
- Audited all 9 tasks against the codebase — all fully implemented:
  1. **WebSocket heartbeat** (`consumers.py` + `useExecutionObserver.js`) — server 15s heartbeat, client 20s ping/pong
  2. **Vite proxy config** (`vite.config.js`) — `timeout: 0`, `proxyTimeout: 0`
  3. **Screenshot watchdog** (`screenshot_stream.py` + `agent_service.py`) — `_FrameWatchdog` thread sends `frame_heartbeat` during browser tool execution
  4. **Stale detection + REST fallback** (`useExecutionObserver.js`) — 10s threshold, 3s REST polling interval
  5. **`duration_ms` in step_logs** (`agent_service.py` + `execution_engine.py`) — recorded in tool_calls_log, extracted in `_build_step_logs`
  6. **ExecutionReplay.vue** — full playback with play/pause, speed control (0.5x/1x/2x/4x), seek slider
  7. **Replay integration** — replay button in `Executions.vue` list + detail dialog, `?replay=true` query param in `ExecutionObserver.vue`
  8. **Fallback `execution_end`** (`views.py`) — `_save_agent_result` emits fallback event after DB write
  9. **Manual testing** — not automated; 148 unit tests all pass

### Status
- All 148 tests pass (verified in round 3)
- No code changes needed — implementation complete
- Only binary screenshot files have uncommitted changes (from test runs)

## Round 3 — Plan 3 (6 tasks) audit and fixes

### Audit Results (Plan 3 Tasks 1-6)
All 6 tasks fully implemented and verified:
1. **Task 1 (步骤实时写入 DB)**: `_persist_step` in AgentRunner, `execution_record` passed from execution_engine, `_save_agent_result` has fallback writes
2. **Task 2 (两种进入场景差异化处理)**: Three branches in onMounted — replay=true, terminal status (REST only), running (REST + WS)
3. **Task 3 (WS 连接阶段状态推送)**: Four phase_change events emitted at correct lifecycle points, frontend tracks currentPhase, BrowserView displays phase text
4. **Task 4 (断线重连改进)**: `completed_steps` in connection_established, three layers of backfill resilience (immediate, stale poll, view-level watch)
5. **Task 5 (固定时长截图持久化)**: `auto_captured` field + migration, persist logic in ScreenshotStream (3s interval), API returns auto_screenshots
6. **Task 6 (截图流 debounce)**: 500ms debounce on both `browser_frame` and `frame_heartbeat` events

### Fixes Applied
- **executing_step phase enhancement** (`BrowserView.vue`): Now shows step_num and tool_name (e.g. "正在执行步骤 3: browser_click...")
- **Stale phase on reconnect** (`useExecutionObserver.js`): Clear `currentPhase` on `connection_established` to prevent stale phase text flashing; store full phase event data (not just string)

### Status
- All 148 tests pass
- Commit: `d34a008`

## Round 1/3 — Dual WS channels, unified screenshot storage, event emitter recovery

### Tasks Completed (13/14)

1. **Task 1: FrameConsumer + frame WS route** (`consumers.py`, `routing.py`)
   - New `FrameConsumer` class handling `browser_frame` / `frame_heartbeat` / `heartbeat` events
   - Route: `ws/execution/<int:execution_id>/frame/`
   - Group: `frame_{execution_id}`

2. **Task 2: Dual-channel event_emitter** (`event_emitter.py`)
   - `_emit_step_event()` → pushes to `execution_{id}` group (step events)
   - `_emit_frame_event()` → pushes to `frame_{id}` group (frame events)
   - Both use `asyncio.run_coroutine_threadsafe()` with `_is_loop_usable()` guard
   - Previously disabled `_emit_step_event` is now fully restored

3. **Task 3: ScreenshotStream uses `_emit_frame_event`** (`screenshot_stream.py`)
   - `browser_frame` and `frame_heartbeat` events now go through frame channel

4. **Task 4: Unified screenshot storage `media/{execution_id}/`** (`models.py`, `screenshot_stream.py`, `agent_tools.py`, `agent_service.py`)
   - `_screenshot_upload_path` → `{execution_id}/{filename}`
   - `_persist_screenshot` saves to `media/{execution_id}/`
   - `_execute_browser_screenshot` saves to `media/{execution_id}/`
   - `execution_id` added to AgentRunner context dict

5. **Task 5: Fix `_create_screenshot_record` sync_to_async** (`screenshot_stream.py`)
   - Simplified to direct synchronous ORM call (always runs in Playwright sync thread)

6. **Task 6: Fix MEDIA_URL** (`settings.py`)
   - `'media/'` → `'/media/'`

7. **Task 7: Vite `/media` proxy** (`vite.config.js`)
   - Added `/media` proxy rule for dev server

8. **Task 8: `useFrameObserver.js`** (new file)
   - Dedicated frame WS composable with reconnection, heartbeat, stale poll fallback
   - Returns `currentFrame`, `frameWsStatus`, `connectFrame()`, `disconnectFrame()`

9. **Task 9: Remove frame handling from `useExecutionObserver.js`**
   - Removed `currentFrame`, `_getFrameUrl`, frame polling, debounce logic
   - Step-only composable now

10. **Task 10: Dual WS in `ExecutionObserver.vue`**
    - Imports both `useExecutionObserver` and `useFrameObserver`
    - Running: connects both channels
    - Terminal: REST-only, sets `currentFrame` from screenshots data
    - Replay: no WS connections

11. **Task 11: Terminal BrowserView screenshot** (included in Task 10)
    - `_setTerminalFrame()` picks last screenshot from gallery, step_logs, or `latest_frame` endpoint

12. **Task 12: Optimize `serve_screenshot` O(N) scan** (`views.py`)
    - Parses `execution_id` from path, queries only that execution's records
    - Removed full table scans over all ExecutionRecord objects

13. **Task 13: ScreenshotGallery/ToolDetailPanel URL building**
    - No changes needed — `serve_screenshot` endpoint handles both old and new path formats

### Tests
- All 148 tests pass
- Updated tests: `EmitStepEventTest` (added `_is_loop_usable` guard handling), `ScreenshotStreamRunTest` (mock `_emit_frame_event`), `BuildStepLogsTest` (updated `format_step_action` expectation)
- Task 14 (manual testing) pending for rounds 2-3

### Files Changed
- `core/consumers.py` — Added `FrameConsumer`
- `core/routing.py` — Added frame route
- `core/event_emitter.py` — Restored `_emit_step_event`, added `_emit_frame_event`
- `core/screenshot_stream.py` — Uses `_emit_frame_event`, simplified `_create_screenshot_record`
- `core/models.py` — New screenshot upload path
- `core/agent_tools.py` — Uses `execution_id` for screenshot dir
- `core/agent_service.py` — Added `execution_id` to context
- `core/views.py` — Optimized `serve_screenshot` DB validation
- `core/tests.py` — Updated mocks and expectations
- `backend/settings.py` — `MEDIA_URL = '/media/'`
- `frontend/vite.config.js` — Added `/media` proxy
- `frontend/src/composables/useFrameObserver.js` — New file
- `frontend/src/composables/useExecutionObserver.js` — Removed frame handling
- `frontend/src/views/ExecutionObserver.vue` — Dual-channel integration
