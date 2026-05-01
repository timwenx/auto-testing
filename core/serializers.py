from rest_framework import serializers
from .models import (
    Project, TestCase, ExecutionRecord, AIConversation, SystemSetting,
    RepoAnalysis, PreconditionTemplate,
    Script, TestPlan, TestPlanItem, PlanExecution,
)


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
            'target_page_or_api', 'feature_group', 'sort_order',
            'version', 'created_by',
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
            'replay_script', 'source_execution', 'plan_execution', 'created_at',
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


# ─── 仓库分析 + 批量生成 API Serializer ───

class RepoAnalysisSerializer(serializers.ModelSerializer):
    class Meta:
        model = RepoAnalysis
        fields = ['id', 'project', 'status', 'local_repo_path', 'discovered_items',
                  'analysis_log', 'created_at']
        read_only_fields = ['id', 'status', 'local_repo_path', 'discovered_items',
                            'analysis_log', 'created_at']


class PreconditionTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PreconditionTemplate
        fields = ['id', 'name', 'description', 'steps', 'markdown_content',
                  'is_default', 'created_at', 'updated_at']
        read_only_fields = ['is_default', 'created_at', 'updated_at']


class BatchGenerateRequestSerializer(serializers.Serializer):
    """批量生成测试用例请求"""
    selected_items = serializers.ListField(
        child=serializers.DictField(),
        help_text='从分析结果中勾选的 discovered_items 子集',
    )
    descriptions = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False, default=dict,
        help_text='key 为 item 的 path, value 为用户描述',
    )
    precondition_id = serializers.IntegerField(
        required=False, default=None, allow_null=True,
        help_text='前置条件模板 ID（可选）',
    )


class BatchSaveRequestSerializer(serializers.Serializer):
    """批量保存测试用例请求"""
    testcases = serializers.ListField(
        child=serializers.DictField(),
        help_text='确认后的用例列表 [{name, description, steps, ...}]',
    )


class TestCaseReorderItemSerializer(serializers.Serializer):
    """单条用例排序信息"""
    id = serializers.IntegerField(help_text='用例 ID')
    feature_group = serializers.CharField(
        required=False, default='', allow_blank=True,
        help_text='功能点名称',
    )
    sort_order = serializers.IntegerField(
        required=False, default=0,
        help_text='排序序号',
    )


class TestCaseReorderSerializer(serializers.Serializer):
    """批量调整用例排序请求"""
    orders = serializers.ListField(
        child=TestCaseReorderItemSerializer(),
        help_text='用例排序信息列表 [{id, feature_group, sort_order}]',
    )


# ─── Script Serializer ───

class ScriptSerializer(serializers.ModelSerializer):
    testcase_name = serializers.CharField(source='testcase.name', read_only=True, default='')
    project_name = serializers.CharField(source='project.name', read_only=True)

    class Meta:
        model = Script
        fields = [
            'id', 'project', 'project_name', 'testcase', 'testcase_name',
            'source_execution', 'name', 'feature_group', 'sort_order',
            'script_data', 'status', 'version',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'source_execution', 'created_at', 'updated_at']


class ScriptConvertRequestSerializer(serializers.Serializer):
    """从 ExecutionRecord 生成 Script 的请求"""
    execution_id = serializers.IntegerField(help_text='Agent 执行记录 ID')
    name = serializers.CharField(
        required=False, default='', allow_blank=True,
        help_text='脚本名称，默认继承用例名'
    )
    feature_group = serializers.CharField(
        required=False, default='', allow_blank=True,
        help_text='功能分组'
    )


class ScriptExecuteRequestSerializer(serializers.Serializer):
    """执行脚本的请求"""
    parameter_overrides = serializers.DictField(
        required=False, default=dict,
        help_text='参数覆盖 key-value'
    )


# ─── TestPlan Serializer ───

class TestPlanItemSerializer(serializers.ModelSerializer):
    script_name = serializers.CharField(source='script.name', read_only=True, default='')
    script_feature_group = serializers.CharField(source='script.feature_group', read_only=True, default='')

    class Meta:
        model = TestPlanItem
        fields = [
            'id', 'test_plan', 'item_type', 'script', 'script_name',
            'script_feature_group', 'feature_group_name', 'sort_order',
        ]
        read_only_fields = ['id']


class TestPlanSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    items = TestPlanItemSerializer(many=True, read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = TestPlan
        fields = [
            'id', 'project', 'project_name', 'name', 'description',
            'status', 'api_token', 'items', 'item_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'api_token', 'created_at', 'updated_at']

    def get_item_count(self, obj):
        return obj.items.count()


class TestPlanCreateUpdateSerializer(serializers.ModelSerializer):
    """用于创建/更新方案，不含嵌套 items（items 通过独立 API 管理）"""
    project_name = serializers.CharField(source='project.name', read_only=True)

    class Meta:
        model = TestPlan
        fields = [
            'id', 'project', 'project_name', 'name', 'description',
            'status', 'api_token', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'api_token', 'created_at', 'updated_at']


class TestPlanItemCreateSerializer(serializers.Serializer):
    """添加方案子项请求"""
    item_type = serializers.ChoiceField(choices=['script', 'feature_group'])
    script_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    feature_group_name = serializers.CharField(
        required=False, default='', allow_blank=True,
        help_text='item_type=feature_group 时必填'
    )


class TestPlanItemsReorderSerializer(serializers.Serializer):
    """方案子项重排序请求"""
    orders = serializers.ListField(
        child=serializers.DictField(),
        help_text='[{id: int, sort_order: int}]',
    )


# ─── PlanExecution Serializer ───

class PlanExecutionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source='test_plan.name', read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True)
    execution_count = serializers.SerializerMethodField()

    class Meta:
        model = PlanExecution
        fields = [
            'id', 'test_plan', 'plan_name', 'project', 'project_name',
            'status', 'trigger_source', 'summary',
            'execution_count', 'started_at', 'completed_at', 'created_at',
        ]

    def get_execution_count(self, obj):
        return obj.execution_records.count()


class PlanExecutionDetailSerializer(PlanExecutionSerializer):
    """方案执行详情 — 包含子 ExecutionRecord 列表"""
    execution_records = serializers.SerializerMethodField()

    class Meta(PlanExecutionSerializer.Meta):
        fields = PlanExecutionSerializer.Meta.fields + ['execution_records']

    def get_execution_records(self, obj):
        from .serializers import ExecutionRecordSerializer
        records = obj.execution_records.select_related('testcase', 'project').all()
        return ExecutionRecordSerializer(records, many=True).data
