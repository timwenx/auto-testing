import json
import logging
from django.http import JsonResponse
from django.db.models import Count, Q
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Project, TestCase, ExecutionRecord, AIConversation
from .serializers import (
    ProjectSerializer, TestCaseSerializer, ExecutionRecordSerializer,
    AIConversationSerializer, AIGenerateRequestSerializer, AIAnalyzeRequestSerializer,
)
from . import ai_engine
from . import execution_engine

logger = logging.getLogger(__name__)


# ─── 项目 ───

class ProjectListCreateView(generics.ListCreateAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer


class ProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer


# ─── 测试用例 ───

class TestCaseListCreateView(generics.ListCreateAPIView):
    queryset = TestCase.objects.select_related('project').all()
    serializer_class = TestCaseSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs


class TestCaseDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = TestCase.objects.select_related('project').all()
    serializer_class = TestCaseSerializer


class ProjectTestCaseListView(generics.ListAPIView):
    serializer_class = TestCaseSerializer

    def get_queryset(self):
        return TestCase.objects.filter(project_id=self.kwargs['project_id'])


# ─── 执行记录 ───

class ExecutionRecordListView(generics.ListAPIView):
    queryset = ExecutionRecord.objects.select_related('project', 'testcase').all()
    serializer_class = ExecutionRecordSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        testcase_id = self.request.query_params.get('testcase')
        if testcase_id:
            qs = qs.filter(testcase_id=testcase_id)
        return qs


class ExecutionRecordDetailView(generics.RetrieveAPIView):
    queryset = ExecutionRecord.objects.select_related('project', 'testcase').all()
    serializer_class = ExecutionRecordSerializer


@api_view(['POST'])
def execute_testcase(request, testcase_id):
    """执行单个测试用例"""
    try:
        testcase = TestCase.objects.select_related('project').get(pk=testcase_id)
    except TestCase.DoesNotExist:
        return Response({'error': '测试用例不存在'}, status=status.HTTP_404_NOT_FOUND)

    base_url = testcase.project.base_url
    if not base_url:
        return Response(
            {'error': '请先在项目中配置测试目标 URL'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 创建执行记录
    record = ExecutionRecord.objects.create(
        project=testcase.project,
        testcase=testcase,
        status='running',
    )
    testcase.status = 'running'
    testcase.save(update_fields=['status'])

    # 异步执行
    def _on_complete(tc, result):
        record.status = result['status']
        record.log = result['log']
        record.error_message = result['error_message']
        record.duration = result['duration']
        record.save()
        tc.status = result['status']
        tc.save(update_fields=['status'])

    execution_engine.execute_testcase_async(testcase, base_url, callback=_on_complete)

    return Response(
        ExecutionRecordSerializer(record).data,
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(['POST'])
def execute_project(request, project_id):
    """批量执行项目下所有就绪/草稿测试用例"""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    if not project.base_url:
        return Response(
            {'error': '请先在项目中配置测试目标 URL'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    testcases = project.testcases.filter(status__in=['draft', 'ready'])
    if not testcases.exists():
        return Response(
            {'error': '没有可执行的测试用例'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    records = []
    for tc in testcases:
        record = ExecutionRecord.objects.create(
            project=project, testcase=tc, status='running',
        )
        tc.status = 'running'
        tc.save(update_fields=['status'])

        def _make_callback(r, t):
            def _on_complete(_tc, result):
                r.status = result['status']
                r.log = result['log']
                r.error_message = result['error_message']
                r.duration = result['duration']
                r.save()
                t.status = result['status']
                t.save(update_fields=['status'])
            return _on_complete

        execution_engine.execute_testcase_async(tc, project.base_url, callback=_make_callback(record, tc))
        records.append(record)

    return Response(
        ExecutionRecordSerializer(records, many=True).data,
        status=status.HTTP_202_ACCEPTED,
    )


# ─── AI ───

class AIConversationListView(generics.ListAPIView):
    queryset = AIConversation.objects.all()
    serializer_class = AIConversationSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        conv_type = self.request.query_params.get('type')
        if conv_type:
            qs = qs.filter(conversation_type=conv_type)
        return qs


@api_view(['POST'])
def ai_generate_testcase(request):
    """AI 生成测试用例"""
    serializer = AIGenerateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    project_id = serializer.validated_data['project_id']
    requirement = serializer.validated_data['requirement']

    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    try:
        generated = ai_engine.generate_testcases(
            project_name=project.name,
            base_url=project.base_url or '',
            requirement=requirement,
        )
    except Exception as e:
        logger.exception("AI generate testcase failed")
        return Response({'error': f'AI 生成失败: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 保存到数据库
    created = []
    for item in generated:
        tc = TestCase.objects.create(
            project=project,
            name=item.get('name', '未命名用例'),
            description=item.get('description', ''),
            steps=item.get('steps', ''),
            expected_result=item.get('expected_result', ''),
            status='draft',
            is_ai_generated=True,
        )
        created.append(tc)

    # 保存 AI 对话记录
    AIConversation.objects.create(
        conversation_type='generate',
        project=project,
        user_message=requirement,
        ai_response=json.dumps(generated, ensure_ascii=False),
    )

    return Response(TestCaseSerializer(created, many=True).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def ai_analyze_result(request):
    """AI 分析执行结果"""
    serializer = AIAnalyzeRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    execution_id = serializer.validated_data['execution_id']
    try:
        record = ExecutionRecord.objects.select_related('testcase').get(pk=execution_id)
    except ExecutionRecord.DoesNotExist:
        return Response({'error': '执行记录不存在'}, status=status.HTTP_404_NOT_FOUND)

    tc_name = record.testcase.name if record.testcase else '未知'

    try:
        analysis = ai_engine.analyze_execution(
            testcase_name=tc_name,
            status=record.status,
            log=record.log,
            error_message=record.error_message,
        )
    except Exception as e:
        logger.exception("AI analyze result failed")
        return Response({'error': f'AI 分析失败: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    AIConversation.objects.create(
        conversation_type='analyze',
        project=record.project,
        user_message=f"分析执行记录 #{record.id}",
        ai_response=json.dumps(analysis, ensure_ascii=False),
    )

    return Response(analysis)


# ─── 系统 ───

@api_view(['GET'])
def health_check(request):
    return Response({'status': 'ok'})


@api_view(['GET'])
def system_stats(request):
    return Response({
        'projects': Project.objects.count(),
        'testcases': TestCase.objects.count(),
        'executions': ExecutionRecord.objects.count(),
        'ai_conversations': AIConversation.objects.count(),
        'testcase_status': dict(
            TestCase.objects.values_list('status').annotate(c=Count('id')).values_list('status', 'c')
        ),
        'execution_status': dict(
            ExecutionRecord.objects.values_list('status').annotate(c=Count('id')).values_list('status', 'c')
        ),
    })
