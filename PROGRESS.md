# Progress Notes — Enriched Context Round

## Completed: 7/7 tasks

All 7 tasks from the enriched context plan implemented successfully.

### Changes Summary

**Task 1: Extended discovered_items JSON Schema**
- `core/repo_analyzer.py`: Rewrote `ANALYSIS_SYSTEM_PROMPT` to instruct Claude to extract:
  - Page elements: `[{selector, type, label, description}]` with priority `#id` > `[name=xxx]` > `[data-testid=xxx]` > `.class`
  - API params: `[{name, in, type, required, description}]` and response_fields: `[{name, type, description}]`
  - Max 10 per category per item to control token budget
- Updated `_parse_analysis_response()` to extract elements/params/response_fields with backward compatibility (defaults to empty arrays)

**Task 2: Optimized SDK analysis prompt**
- Added `_FORM_KEYWORDS` list for SDK mode: Vue/React form elements (`el-form`, `el-input`, `<form`, `<input`, `<button`, `data-testid`) + API parameter definitions (`@RequestParam`, `@RequestBody`, `serializer`, `Serializer`)
- SDK mode now runs two-round search: route keywords (high priority) first, then form keywords (supplementary context) within the same 15-file budget
- Increased SDK `max_tokens` from 4096 to 8192

**Task 3: TestCase.test_context JSONField**
- `core/models.py`: Added `test_context` JSONField (default=dict) to TestCase model
- Updated RepoAnalysis.discovered_items help_text to document new schema
- Migration `0021_add_test_context_to_testcase.py` created and applied

**Task 4: Modified batch generator to pass enriched context**
- `core/batch_generator.py`: Updated `BATCH_GENERATE_SYSTEM_PROMPT` to:
  - Instruct Claude to reference CSS selectors in test steps when elements are provided
  - Require `test_context` field in output (page type or API type with elements/params)
- Updated `_generate_batch()` to inject elements/params/response_fields into target descriptions
- `core/views.py`: `batch_save_testcases()` now saves `test_context` from generated data

**Task 5: Injected enriched context into Agent execution prompt**
- `core/agent_tools.py`: Added 3 formatting functions:
  - `_format_test_context()`: Routes to page/api formatter based on context_type or auto-detection
  - `_format_page_context()`: Lists selectors with "优先使用这些已知选择器" instruction
  - `_format_api_context()`: Lists params and response_fields
- Updated `build_test_execution_system_prompt()` to include `{test_context_section}` placeholder
- Updated `_get_fallback_template()` to include the placeholder
- `agent_execute_prompt.md`: Added `{test_context_section}` placeholder + "Phase 0" workflow for using pre-extracted context

**Task 6: Frontend display of enriched analysis results**
- `CodeAnalysisPanel.vue`:
  - Page table: Added expandable rows showing elements table (selector, type, label, description)
  - API table: Added expandable rows showing params table (name, in, type, required, description) and response_fields table
  - Added element/param count badge columns
  - Added `elemTypeTag()` and `paramInTag()` helper functions for colored tags
  - Updated analyzing progress text to mention "页面元素和 API 参数"

**Task 7: Tests**
- `core/tests_enriched_context.py`: 26 tests across 5 test classes:
  - `ParseAnalysisResponseEnrichedTest` (9 tests): enriched JSON, backward compatible, edge cases
  - `FormatTestContextTest` (8 tests): page/api context formatting, auto-detection, empty/None
  - `BuildPromptWithContextTest` (3 tests): prompt injection with/without context
  - `TestCaseTestContextFieldTest` (4 tests): model field CRUD
  - `BatchGeneratorPromptTest` (2 tests): system prompt includes context instructions

### Verification
- **26 tests** all passing
- **Frontend builds** successfully (1.15s)
- **Django check**: 0 issues
- **Bug fix**: `_parse_analysis_response` regex fallback now has try/except for invalid JSON

### Files Changed
| File | Change |
|------|--------|
| core/repo_analyzer.py | Enriched ANALYSIS_SYSTEM_PROMPT, _parse_analysis_response with elements/params, _FORM_KEYWORDS, SDK max_tokens 8192, regex fallback fix |
| core/agent_tools.py | _format_test_context/_format_page_context/_format_api_context, updated build_test_execution_system_prompt, updated fallback template |
| core/templates/agent_execute_prompt.md | {test_context_section} placeholder, Phase 0 workflow |
| core/batch_generator.py | Updated system prompt with test_context field, _generate_batch includes elements/params in descriptions |
| core/models.py | Added test_context JSONField to TestCase, updated RepoAnalysis help_text |
| core/views.py | batch_save_testcases saves test_context |
| core/migrations/0021_add_test_context_to_testcase.py | New migration |
| core/tests_enriched_context.py | 26 new tests |
| frontend/src/components/CodeAnalysisPanel.vue | Expandable rows with elements/params tables |
