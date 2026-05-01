# Progress Notes — Feature Group Analysis (Round 1/3)

## Status: ALL 8 TASKS COMPLETE

### Changes Summary

1. **Task 1: ANALYSIS_SYSTEM_PROMPT** — Rewrote AI prompt to output `{features: [{name, description, pages, apis}]}` format instead of flat `{pages, apis}`. Added feature grouping instructions with constraints (2-10 items per group, business-domain grouping).

2. **Task 2: `_parse_analysis_response()`** — Now detects `features` key first (new format), flattens to items with `feature_group` field. Falls back to old `pages`+`apis` format with empty `feature_group` for backward compatibility.

3. **Task 3: CLI/SDK user prompts** — Updated wording to "识别功能模块，并提取所有前端页面路由和 REST API 端点，按功能分组归类".

4. **Task 4: CodeAnalysisPanel.vue** — Replaced el-tabs (pages/apis) with el-collapse showing feature groups. Each group has collapsible panel with items table. Old data without `feature_group` shows as "未分组".

5. **Task 5: Selection state** — Changed from `$index`-based tracking to `path`-based Set. Added group-level select/deselect with indeterminate state. Global select-all/deselect-all button.

6. **Task 6: batch_generator** — Added `feature_group` field injection into target descriptions for better AI context.

7. **Task 7: Tests** — 12 new tests in `ParseFeatureGroupFormatTest`: new format parsing, multiple groups, elements/params, empty/null, backward compat, priority over old format. All 347 tests pass (335 existing + 12 new).

8. **Task 8: Frontend build** — Verified clean build (738ms).

### Files Changed
| File | Lines Changed |
|------|-------------|
| `core/repo_analyzer.py` | +121/-27 (prompt + parser) |
| `core/batch_generator.py` | +3 (feature_group injection) |
| `core/tests_enriched_context.py` | +186 (12 new tests) |
| `frontend/src/components/CodeAnalysisPanel.vue` | +265/-43 (group display) |

### Key Design Decisions
- `discovered_items` remains a flat array with `feature_group` string field — downstream code unchanged
- Frontend groups by computed property, emits flat array — TestCaseManager interface unchanged
- New format takes priority when `features` key exists; old format is fallback
