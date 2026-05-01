# Progress Notes — Round 1 (Plan: UI/UX improvements + batch convert)

## Completed: 7/7 tasks

### Phase 1: Backend — ExecutionRecordListSerializer feature group field
- **serializers.py**: Added `testcase_feature_group = serializers.CharField(source='testcase.feature_group', read_only=True, default='')` to `ExecutionRecordListSerializer`
- Frontend can now group execution records by feature group

### Phase 2: Backend — Batch script convert API endpoint
- **views.py**: Added `BatchConvertRequestSerializer` and `batch_convert_scripts` view function
  - POST /api/scripts/batch-convert/ — accepts `project_id` and `feature_group`
  - Finds all Agent execution records with terminal status in that feature group
  - Skips records that already have associated Script (idempotent)
  - Returns created count, skipped count, and script list
- **urls.py**: Added `scripts/batch-convert/` route (before `scripts/<int:pk>/execute/` to avoid path conflict)
- Also added `from rest_framework import serializers as drf_serializers` import alias in views.py

### Phase 3: Frontend API layer
- **api.js**: Added `batchConvertScripts(projectId, featureGroup)` function calling POST /api/scripts/batch-convert/

### Phase 4: Executions.vue redesign
- Complete rewrite of the execution records page:
  - Replaced flat table with `el-collapse` grouped by `testcase_feature_group`
  - Each group shows: feature name, record count, pass/fail/running stats as badges
  - "生成脚本" button per group calls `batchConvertScripts` API
  - Special groups: "方案执行" (plan_execution records), "未关联用例" (no testcase), "未分组" (empty feature_group)
  - All groups auto-expand on data load
  - Preserved: expand rows with step_logs/screenshots/agent_response, detail dialog, log dialog, image preview, filters, pagination, polling

### Phase 5: ProjectDetail.vue simplification
- Removed `viewMode` ref and `el-button-group` toggle (tree/grouped/flat)
- Removed grouped view (el-collapse with group tables)
- Removed flat list view (el-table with feature_group column)
- Removed `groupedTestcases` and `groupNames` computed properties
- Removed `activeCollapse` ref
- Removed `handleMoveUp`/`handleMoveDown` functions
- Tree view is now the only and default view mode (no v-if needed)

### Phase 6: TestPlanView.vue bug fix
- **Form reset timing**: Moved `addItemForm.value = {...}` BEFORE `await loadScriptsForProject()` in the `watch(showAddItem)` handler — prevents async load from overwriting user's radio selection
- **Paginated response**: Changed `availableTestcases.value = testcasesRes.data || []` to `testcasesRes.data.results || testcasesRes.data || []` — handles DRF paginated response format `{count, results}`

### Phase 7: Tests + Build
- **13 tests** in `core/tests.py`, all passing:
  - `ExecutionRecordListSerializerTest` (3 tests): feature_group field, empty group, no testcase
  - `BatchConvertScriptsTest` (10 tests): creates scripts, skips existing, different groups, no records, invalid project, empty group, only agent mode, only terminal status, idempotent, missing project_id
- **Django system check**: 0 issues
- **Frontend build**: success in 684ms

### Files Changed (8 files)
| File | Change |
|------|--------|
| core/serializers.py | Added testcase_feature_group to ExecutionRecordListSerializer |
| core/views.py | Added batch_convert_scripts endpoint + BatchConvertRequestSerializer |
| core/urls.py | Added scripts/batch-convert/ route |
| core/tests.py | New file — 13 backend tests |
| frontend/src/api.js | Added batchConvertScripts function |
| frontend/src/views/Executions.vue | Full rewrite — feature-group-grouped collapsible view |
| frontend/src/views/ProjectDetail.vue | Removed grouped/flat views, tree-only |
| frontend/src/views/TestPlanView.vue | Fixed add-item dialog timing + paginated response |
