# Progress Notes — Round 1: UI/UX Simplification + Batch Execution Refactor

## Completed (5/5 tasks)

All 5 tasks implemented successfully. 378 tests pass, frontend builds clean.

### Changes Summary

1. **Task 1: Simplified testcase click view** — Removed description/steps/expected_result/markdown_content display when clicking a testcase in the tree. Only name, status, and action buttons remain. Full details still available via "查看详情" drawer button.

2. **Task 2: Feature group drag-drop sort** — Added `sortablejs` dependency. Feature group test case table now supports drag-and-drop row reordering. On drag end, calls existing `reorderTestcases` API to persist new sort_order. Watch on `treeSelection` initializes/destroys SortableJS instance.

3. **Task 3: Refactored batch execution** —
   - `execute_project_agent`: Groups testcases by `feature_group`, submits one thread task per group (parallel across groups, sequential within)
   - `execute_feature_group`: Changed from per-testcase parallel submission to single sequential task submission
   - New helpers: `_execute_testcases_sequential` and `_execute_testcases_sequential_by_records`
   - All ExecutionRecords are pre-created before task submission (HTTP 202 returns all IDs immediately)

4. **Task 4: Simplified execution record list** — Removed `execution_mode` and `tool_calls_count` columns. Added `testcase_feature_group` as subtitle text under testcase name.

5. **Task 5: Backend tests** —
   - Updated `ExecuteAllEndpointTest`: expects 1 group task (both in same default group)
   - Updated `ExecuteProjectOrderingTest`: expects 2 group tasks (2 feature groups)
   - New `SequentialExecutionHelperTest` (2 tests): verifies in-order execution and continue-after-failure
   - New `GroupedBatchExecutionTest` (4 tests): verifies group count, single group, no-group, and sort order
   - New `FeatureGroupSequentialExecutionTest` (2 tests): verifies single submission and submitted count

### Files Changed
| File | Changes |
|------|---------|
| `core/views.py` | `_execute_testcases_sequential`, `_execute_testcases_sequential_by_records`, refactored `execute_project_agent` and `execute_feature_group` |
| `core/tests.py` | 8 new tests, 2 updated tests |
| `frontend/src/views/ProjectDetail.vue` | Simplified testcase click view, sortable table, simplified execution list |
| `frontend/package.json` | Added `sortablejs` dependency |
