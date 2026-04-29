from rest_framework import serializers
from .models import Project, TestCase, ExecutionRecord, AIConversation


class ProjectSerializer(serializers.ModelSerializer):
    testcase_count = serializers.ReadOnlyField()
    last_execution_status = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            'id', 'name', 'description', 'base_url',
            'testcase_count', 'last_execution_status',
            'created_at', 'updated_at',
        ]

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
            'status', 'log', 'screenshot_path', 'duration',
            'error_message', 'created_at',
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


class AIAnalyzeRequestSerializer(serializers.Serializer):
    """AI 分析执行结果的请求"""
    execution_id = serializers.IntegerField()
