from django.contrib import admin
from .models import (
    Project, TestCase, ExecutionRecord, AIConversation, SystemSetting,
    Screenshot, RepoAnalysis, PreconditionTemplate,
    Script, TestPlan, TestPlanItem, PlanExecution,
)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'base_url', 'testcase_count', 'created_at']
    search_fields = ['name']


@admin.register(TestCase)
class TestCaseAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'status', 'priority', 'test_type', 'created_by', 'version', 'is_ai_generated', 'created_at']
    list_filter = ['status', 'is_ai_generated', 'created_by', 'priority', 'project']
    search_fields = ['name', 'target_page_or_api']
    readonly_fields = ['conversation_history']


@admin.register(ExecutionRecord)
class ExecutionRecordAdmin(admin.ModelAdmin):
    list_display = ['id', 'project', 'testcase', 'status', 'execution_mode', 'tool_calls_count', 'duration', 'created_at']
    list_filter = ['status', 'execution_mode', 'project']
    readonly_fields = ['screenshots', 'step_logs', 'agent_response']


@admin.register(AIConversation)
class AIConversationAdmin(admin.ModelAdmin):
    list_display = ['id', 'conversation_type', 'project', 'created_at']
    list_filter = ['conversation_type']


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ['key', 'value', 'description', 'updated_at']
    search_fields = ['key', 'description']


@admin.register(Screenshot)
class ScreenshotAdmin(admin.ModelAdmin):
    list_display = ['id', 'execution', 'step_num', 'action', 'created_at']
    list_filter = ['execution__project']
    search_fields = ['action']


@admin.register(RepoAnalysis)
class RepoAnalysisAdmin(admin.ModelAdmin):
    list_display = ['id', 'project', 'status', 'created_at']
    list_filter = ['status', 'project']
    readonly_fields = ['discovered_items', 'analysis_log']


@admin.register(PreconditionTemplate)
class PreconditionTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_default', 'created_at', 'updated_at']
    list_filter = ['is_default']
    search_fields = ['name']


@admin.register(Script)
class ScriptAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'project', 'feature_group', 'status', 'version', 'created_at']
    list_filter = ['status', 'project']
    search_fields = ['name']


@admin.register(TestPlan)
class TestPlanAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'project', 'status', 'api_token', 'created_at']
    list_filter = ['status', 'project']
    search_fields = ['name']


@admin.register(TestPlanItem)
class TestPlanItemAdmin(admin.ModelAdmin):
    list_display = ['id', 'test_plan', 'item_type', 'script', 'feature_group_name', 'sort_order']
    list_filter = ['item_type']


@admin.register(PlanExecution)
class PlanExecutionAdmin(admin.ModelAdmin):
    list_display = ['id', 'test_plan', 'project', 'status', 'trigger_source', 'started_at', 'completed_at']
    list_filter = ['status', 'trigger_source', 'project']
