# Progress Notes — Round 5 (Phase 1-2: Critical Fixes + Navigation Redesign)

## Completed: 6/6 tasks

### 1. Fix Plan Execution Auth Bug (P0)
- **File**: `frontend/src/api.js`, `frontend/src/views/TestPlanView.vue`
- `executePlan()` in api.js now accepts optional `options` (3rd arg) for custom headers
- `handleExecutePlan()` in TestPlanView sends `X-Plan-Token` header with plan's api_token
- This resolves the 403 error when clicking "执行方案" from the UI

### 2. AI Generation State Persistence (P0)
- **File**: `frontend/src/views/ProjectDetail.vue`
- After AI generate: saves draft (conversation_id, testcase_ids, names, requirement) via `saveGenerationDraft()`
- After AI adjust: updates draft with new state
- After save all: clears draft via `clearGenerationDraft()`
- On mount: checks for existing draft, reloads testcases from DB, reopens AI dialog
- Uses existing backend `generation_draft` JSONField + API endpoints

### 3. Route Guard
- **File**: `frontend/src/router/index.js`
- Added `beforeEach` guard: redirects to `/login` if no `mytest_token` in localStorage
- Already-logged-in users visiting `/login` are redirected to `/`

### 4. Sidebar Navigation Redesign
- **File**: `frontend/src/App.vue`
- Renamed: 仪表盘→工作台, 项目管理→项目, 脚本管理→脚本, 用例方案→测试方案
- Reordered: 工作台, 项目, 脚本, 测试方案, 执行记录, 系统设置 (workflow order)
- Sidebar active state uses `sidebarActive` computed that matches sub-routes to parent

### 5. App.vue Layout Redesign
- **File**: `frontend/src/App.vue`
- Replaced `pageTitleMap` with breadcrumb navigation (el-breadcrumb)
- Sub-routes generate multi-level breadcrumbs (e.g., 项目 > 项目详情)
- Header shows current username from localStorage
- Logout button: confirms with ElMessageBox, clears localStorage, pushes /login

### 6. Verification
- 332 backend tests pass (2 pre-existing BatchGenerateViewTest failures unrelated to this round)
- Frontend build succeeds
- Django system check: 0 issues

### Pre-existing Issues (not introduced this round)
- `core/views.py` has uncommitted changes to `batch_generate_testcases` that break 2 tests
- `frontend/src/components/BatchTestCaseEditor.vue` has uncommitted changes
