from rest_framework import serializers
from .models import Project, TestCase, ExecutionRecord, AIConversation, SystemSetting


class ProjectSerializer(serializers.ModelSerializer):
    testcase_count = serializers.ReadOnlyField()
    last_execution_status = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            'id', 'name', 'description', 'base_url',
            'repo_url', 'repo_username', 'repo_password',
            'github_url', 'github_token', 'local_repo_path',
            'testcase_count', 'last_execution_status',
            'created_at', 'updated_at',
        ]
        extra_kwargs = {
            'repo_password': {'write_only': True},
            'github_token': {'write_only': True},
        }

    def get_last_execution_status(self, obj):
        ex = obj.last_execution
        return ex.status if ex else None


class TestCaseSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    execution_count = serializers.SerializerMethodField()

    class Meta:
        model = TestCase
        fields = [
            'id', 'project', 'project_name', 'name', 'description',
            'steps', 'expected_result', 'status', 'is_ai_generated',
            'markdown_content', 'priority', 'test_type',
            'target_page_or_api', 'version', 'created_by',
            'conversation_history',
            'execution_count', 'created_at', 'updated_at',
        ]

    def get_execution_count(self, obj):
        return obj.executions.count()


class ExecutionRecordSerializer(serializers.ModelSerializer):
    testcase_name = serializers.CharField(source='testcase.name', read_only=True, default='')
    project_name = serializers.CharField(source='project.name', read_only=True)

    class Meta:
        model = ExecutionRecord
        fields = [
            'id', 'project', 'project_name', 'testcase', 'testcase_name',
            'status', 'execution_mode', 'tool_calls_count', 'ai_model',
            'log', 'screenshot_path', 'duration',
            'error_message', 'screenshots', 'step_logs', 'agent_response',
            'created_at',
        ]


class AIConversationSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True, default='')

    class Meta:
        model = AIConversation
        fields = [
            'id', 'conversation_type', 'project', 'project_name',
            'user_message', 'ai_response', 'created_at',
        ]


class AIGenerateRequestSerializer(serializers.Serializer):
    """AI 生成用例的请求"""
    project_id = serializers.IntegerField()
    requirement = serializers.CharField(help_text='用自然语言描述要测试的功能')
    target = serializers.CharField(
        required=False, default='', allow_blank=True,
        help_text='测试目标（可选），如「用户登录页面」「/api/users/ 接口」'
    )


class AIAdjustRequestSerializer(serializers.Serializer):
    """AI 对话式调整用例的请求"""
    project_id = serializers.IntegerField()
    conversation_id = serializers.IntegerField(
        required=False, default=None, allow_null=True,
        help_text='之前的对话 ID（可选，用于恢复上下文）'
    )
    user_feedback = serializers.CharField(help_text='用户的修改意见')
    current_cases = serializers.ListField(
        child=serializers.DictField(),
        help_text='当前的用例列表'
    )
    testcase_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False, default=[],
        help_text='当前用例对应的数据库 TestCase ID 列表（用于更新已有记录）'
    )


class AIAnalyzeRequestSerializer(serializers.Serializer):
    """AI 分析执行结果的请求"""
    execution_id = serializers.IntegerField()


class SystemSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSetting
        fields = ['id', 'key', 'value', 'description', 'updated_at']
        read_only_fields = ['id', 'description', 'updated_at']


class SystemSettingBulkUpdateSerializer(serializers.Serializer):
    """批量更新设置"""
    settings = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        help_text='键值对，如 {"claude_cli_path": "claude", "max_workers": "3"}',
    )


# ─── Agent API 请求 Serializer ───

class AgentGenerateRequestSerializer(serializers.Serializer):
    """Agent 生成用例的请求"""
    project_id = serializers.IntegerField()
    requirement = serializers.CharField(help_text='用自然语言描述要测试的功能')
    target = serializers.CharField(
        required=False, default='', allow_blank=True,
        help_text='测试目标（可选），如「用户登录页面」「/api/users/ 接口」'
    )


class AgentRefineRequestSerializer(serializers.Serializer):
    """Agent 单用例对话式调整请求"""
    testcase_id = serializers.IntegerField(help_text='要调整的测试用例 ID')
    user_feedback = serializers.CharField(
        required=False, default='', allow_blank=True,
        help_text='用户的修改意见，为空时 Agent 主动提问'
    )


class AgentConfirmRequestSerializer(serializers.Serializer):
    """Agent 确认用例请求"""
    testcase_id = serializers.IntegerField(help_text='要确认的测试用例 ID')


class AgentExecuteRequestSerializer(serializers.Serializer):
    """Agent 执行用例请求"""
    testcase_id = serializers.IntegerField(help_text='要执行的测试用例 ID')
