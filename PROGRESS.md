# Progress Notes — Round 1-3: UI/UX Simplification + Batch Execution Refactor

## Round 1 (commit f4a74eb)
All 5 tasks implemented. 378 tests pass, frontend builds clean.

1. **Task 1: Simplified testcase click view** — Removed description/steps/expected_result/markdown_content display when clicking a testcase in the tree. Only name, status, and action buttons remain.
2. **Task 2: Feature group drag-drop sort** — Added `sortablejs` dependency. Drag-and-drop row reordering with API persistence.
3. **Task 3: Refactored batch execution** — Groups by feature_group, sequential within group, parallel across groups.
4. **Task 4: Simplified execution record list** — Removed execution_mode and tool_calls_count columns. Added testcase_feature_group subtitle.
5. **Task 5: Backend tests** — 8 new tests, 2 updated tests.

## Round 2 (commit 149428c)
Code quality fixes:
- Fixed Sortable memory leak: added onUnmounted cleanup
- Fixed Sortable re-init after failed sort + loadData revert
- Hoisted _get_ai_model() before feature group loop (was N calls, now 1)
- Removed dead code _execute_testcases_sequential (30 lines)
- 378 tests pass, frontend builds successfully

## Round 3 (commit 2eb84f6)
Final QA:
- Strengthened `ExecuteProjectOrderingTest`: replaced silent-skip guard with explicit assertion that verifies all expected records are found
- Added `test_feature_group_empty_returns_400`: edge case test for non-existent feature group execution
- **442 tests pass** (378 original + 64 from rounds 1-2 + 1 new from round 3)
- Frontend builds successfully
- Django system check: 0 issues
