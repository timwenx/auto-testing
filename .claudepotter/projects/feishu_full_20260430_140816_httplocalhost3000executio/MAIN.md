---
status: planning
mode: planning
short_title:
git_commit: "df92daa"
git_branch: "master"
created_at: "2026-04-30T14:14:22.924798+08:00"
plan_file: PLAN.md
rounds: 6
---

# Overall Goal

See PLAN.md for details.

## Plan

Now I have a thorough understanding of the entire codebase. Let me analyze the root cause and create the implementation plan.

# Implementation Plan

## Overview

This plan addresses two issues: (1) the WebSocket observation panel loses real-time events after `browser_navigate` starts — the UI freezes at step 2 showing "执行中" while the backend completes all 20 steps; (2) there is no way to view/replay completed executions in the observation panel. The root cause of issue (1) is likely a combination of: the `browser_navigate` call blocking the agent thread for a long time (Playwright browser init + page load), the WebSocket connection silently closing during this gap, and the `_emit_step_event` function silently swallowing all exceptions. Issue (2) is a missing feature — the "观察" button only appears for `running` executions and there is no replay mode in the observer.

## Tasks

- [ ] **Task 1: Add diagnostic logging and error visibility to `_emit_step_event`**
  - Scope: `/Users/wenxinji/Documents/ai-project/auto-testing/core/event_emitter.py`
  - Approach: Replace the silent `except` + `logger.warning` pattern with proper `logger.exception` calls that include full tracebacks. Add a logging statement on the success path for non-`browser_frame` events so we can verify which events were successfully dispatched. Add a counter or check to detect when `_asgi_event_loop` is None or not running, and log an explicit ERROR in that case instead of falling through silently.
  - Complexity: Low

- [ ] **Task 2: Add WebSocket keep-alive (ping/pong) mechanism to `ExecutionConsumer`**
  - Scope: `/Users/wenxinji/Documents/ai-project/auto-testing/core/consumers.py`
  - Approach: Switch `ExecutionConsumer` from synchronous `WebsocketConsumer` to `AsyncWebsocketConsumer` so that `asyncio` operations (like periodic pings) can be used directly. Add a background task that sends a lightweight `ping` event every 15 seconds during execution. This prevents intermediate proxies, the Vite dev proxy, or the browser itself from closing the WebSocket due to inactivity during long `browser_navigate` or browser-init blocks. Alternatively, if staying with the sync consumer, use `self.send()` in a `channel_layer.group_send` callback to send a heartbeat event at regular intervals.
  - Complexity: Medium

- [ ] **Task 3: Add frontend WebSocket health monitoring and dead-connection recovery**
  - Scope: `/Users/wenxinji/Documents/ai-project/auto-testing/frontend/src/composables/useExecutionObserver.js`
  - Approach: (a) Handle the new `ping` event in `_handleEvent` — on each received message, reset a `lastMessageTime` timestamp. (b) Add a health check timer (every 20 seconds): if `status === 'running'` and no message has been received for 30+ seconds, consider the connection dead. In that case, actively fetch the execution record via REST (`GET /api/executions/<id>/`), and if the execution status is no longer `running`, transition to `completed` state and load final data via `_fetchFinalDataAndClose()`. If the execution is still `running`, attempt a WebSocket reconnect. (c) Ensure the `onclose` handler also triggers a REST status check before giving up (currently it only reconnects, but if the execution is already done, it should fetch final data instead).
  - Complexity: Medium
  - Depends on: Task 3a (ping handling) needs the backend ping from Task 2, but the REST fallback works independently.

- [ ] **Task 4: Make "观察" button available for all execution statuses in `Executions.vue`**
  - Scope: `/Users/wenxinji/Documents/ai-project/auto-testing/frontend/src/views/Executions.vue` (line 54 and line 70)
  - Approach: Remove the `v-if="row.status === 'running'"` condition from the "观察" button in the table (line 54). Also remove the same condition from the detail dialog's "观察执行" button (line 69). Allow navigating to the observer page for `passed`, `failed`, `error`, and `completed` statuses as well.
  - Complexity: Low

- [ ] **Task 5: Add replay mode to `ExecutionObserver.vue` for completed executions**
  - Scope: `/Users/wenxinji/Documents/ai-project/auto-testing/frontend/src/views/ExecutionObserver.vue`, `/Users/wenxinji/Documents/ai-project/auto-testing/frontend/src/composables/useExecutionObserver.js`, `/Users/wenxinji/Documents/ai-project/auto-testing/frontend/src/components/ExecutionTimeline.vue`
  - Approach: (a) In `ExecutionObserver.vue` on mount, when the execution status is already non-running (e.g., `passed`, `failed`, `completed`, `error`), enter "replay mode" instead of connecting via WebSocket. Load all step logs via REST API (already done on mount, lines 176-194). Then automatically animate through them one by one with configurable delay (e.g., 1 second per step). (b) Add a replay control bar component (`ReplayControls.vue`) with: play/pause button, speed selector (0.5x, 1x, 2x, 4x), step forward/backward buttons, progress bar showing current position. (c) In the composable, add replay state (`replayMode`, `replayIndex`, `replayPlaying`, `replaySpeed`) and a `startReplay()` method. During replay, increment `replayIndex` at intervals and only show steps up to `replayIndex` in the timeline. (d) When the observer loads for a running execution, behave as today (WebSocket real-time). When it loads for a completed execution, show all steps immediately with option to "replay from start" via a button.
  - Complexity: High
  - Depends on: Task 4

- [ ] **Task 6: Update `ExecutionTimeline.vue` to support replay mode**
  - Scope: `/Users/wenxinji/Documents/ai-project/auto-testing/frontend/src/components/ExecutionTimeline.vue`
  - Approach: Accept a `visibleCount` prop (or similar) that limits how many steps are displayed during replay animation. When `visibleCount` is set and less than `steps.length`, only render the first `visibleCount` steps. This creates the "animation" effect of steps appearing one by one during replay. When `visibleCount` is null/undefined, show all steps (normal mode).
  - Complexity: Low
  - Depends on: Task 5

- [ ] **Task 7: Add backend diagnostic endpoint or logging for WebSocket delivery verification**
  - Scope: `/Users/wenxinji/Documents/ai-project/auto-testing/core/consumers.py`, `/Users/wenxinji/Documents/ai-project/auto-testing/core/agent_service.py`
  - Approach: In `AgentRunner.run()`, add a logger.info call after each `_emit_step_event` invocation that logs the event type and step number, so we can compare backend event emission logs with frontend event reception. Also log the state of `_asgi_event_loop` at the start of the agent run (is it None? is it running?). This helps diagnose whether the issue is events not being sent or events not being received.
  - Complexity: Low

## Key Decisions

1. **Sync vs Async WebSocket Consumer**: The current `ExecutionConsumer` is synchronous (`WebsocketConsumer`). Switching to `AsyncWebsocketConsumer` would make periodic ping sending easier but requires changing all `self.send()` and `group_add/group_discard` calls to use `await`. Decision: switch to async consumer since Daphne natively supports it and it eliminates the `async_to_sync` overhead.
2. **Replay via frontend animation vs backend replay**: The replay should be implemented entirely on the frontend by loading persisted `step_logs` from REST and animating through them. This avoids re-executing the test or creating a complex backend replay service. The step logs already contain all necessary data (action, target, result, screenshot_path, timestamp, duration).
3. **WebSocket connection for completed executions**: When loading the observer for a completed execution, do NOT connect via WebSocket (no events to receive). Use REST-only data loading and replay mode. The WebSocket should only be used for `running` executions.
4. **Keep-alive interval**: 15 seconds is a good balance — frequent enough to prevent most proxy timeouts (typically 60s) but infrequent enough to not add significant overhead.

## Considerations

- **Edge case: execution transitions from running to completed while observer is open**: The frontend currently handles this via `execution_end` event. With the health monitoring in Task 3, if the WebSocket drops and the execution completes, the REST fallback will catch it. Need to ensure no duplicate data loading occurs (both WS `execution_end` and REST fallback triggering simultaneously).
- **Edge case: page refresh during execution**: Already handled — `onMounted` loads step logs via REST and connects WebSocket if running. Need to ensure the replay mode doesn't conflict with this (replay should only activate when the execution is confirmed non-running).
- **Performance: `InMemoryChannelLayer` limitations**: The `InMemoryChannelLayer` is single-process only and has a default message expiry of 60 seconds. This is fine for development but should be noted for production deployment. No action needed now.
- **Testing strategy**: Test with a deliberately slow `browser_navigate` (e.g., navigating to a slow-loading page) to verify the keep-alive and health monitoring work. Test the replay mode with a completed execution that has many steps. Test the "观察" button for each execution status.
- **Consideration for diagnosis**: Before implementing fixes, first run the execution again with the diagnostic logging from Task 1 and Task 7 enabled. Check the backend logs to see if `_emit_step_event` was called for all 20 steps and whether it succeeded or failed. This will confirm whether the root cause is event emission failure or WebSocket delivery failure.

## In Progress

## Todo

- [ ] Task 1: Add diagnostic logging and error visibility to `_emit_step_event`
- [ ] Task 2: Add WebSocket keep-alive (ping/pong) mechanism to `ExecutionConsumer`
- [ ] Task 3: Add frontend WebSocket health monitoring and dead-connection recovery
- [ ] Task 4: Make "观察" button available for all execution statuses in `Executions.vue`
- [ ] Task 5: Add replay mode to `ExecutionObserver.vue` for completed executions
- [ ] Task 6: Update `ExecutionTimeline.vue` to support replay mode
- [ ] Task 7: Add backend diagnostic endpoint or logging for WebSocket delivery verification

## Done

## Execution Log
