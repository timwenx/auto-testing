# Progress Notes — Plan Parameter Management (Round 1/3)

## Status: ALL 6 TASKS COMPLETE

### Changes Summary

1. **Task 1: Deterministic `_make_param_name`** — Replaced index-based parameter naming with selector-content hash (`_selector_hash`). Same CSS selector always produces the same parameter name across scripts. `browser_navigate` uses fixed `param_url`. `browser_assert` uses selector-based name. Added `_deduplicate_param_names()` for same-selector value conflicts.

2. **Task 2: Plan Parameters API** — New `GET /api/plans/<id>/parameters/` endpoint. Collects parameters from all scripts in plan, deduplicates by name, detects conflicts (same name, different defaults). Returns `parameters` dict with sources info and `all_script_params` per-script mapping.

3. **Task 3: Plan Execute with Overrides** — `plan_execute` now accepts optional `parameter_overrides` dict in request body. `_run_single_script` filters overrides to only params the script uses before passing to `ReplayExecutor`. Backward compatible: empty body = same behavior.

4. **Task 4: Frontend Parameter Dialog** — Modified `handleExecutePlan` to fetch parameters first. If params exist, shows editing dialog with input/assertion groups, conflict warnings, reset-to-default. Passes only changed values as `parameter_overrides`. Updated API examples with `-d` body.

5. **Task 5: Batch Normalization** — Added `normalize_parameter_names()` post-processor in `batch_convert_scripts`. Groups by label+default, renames to first occurrence's name, updates both parameters dict and template references in steps.

6. **Task 6: Unit Tests** — 23 new tests across 4 test classes: deterministic naming (6), parameter aggregation (8), override handling (4), normalization (5). Total: 370 + 63 = 433 tests passing.

### Files Changed
| File | Changes |
|------|---------|
| `core/script_converter.py` | `_selector_hash()`, `_make_param_name()` deterministic, `_deduplicate_param_names()`, `normalize_parameter_names()` |
| `core/views.py` | `plan_parameters()` view, `plan_execute` body parsing, `_run_single_script` overrides filtering |
| `core/serializers.py` | `PlanExecuteRequestSerializer` |
| `core/urls.py` | `plans/<id>/parameters/` route |
| `core/tests.py` | 23 new tests in 4 classes |
| `frontend/src/api.js` | `getPlanParameters()`, updated `executePlan()` |
| `frontend/src/views/TestPlanView.vue` | Parameter dialog, execute flow, conflict UI |
