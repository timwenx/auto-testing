from django.contrib import admin
from .models import Project, TestCase, ExecutionRecord, AIConversation, SystemSetting, Screenshot


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
