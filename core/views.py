import json
import logging
import os
import mimetypes
from django.http import JsonResponse, FileResponse, Http404
from django.db.models import Count, Q
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Project, TestCase, ExecutionRecord, AIConversation, SystemSetting
from .serializers import (
    ProjectSerializer, TestCaseSerializer, ExecutionRecordSerializer,
    AIConversationSerializer, AIGenerateRequestSerializer, AIAnalyzeRequestSerializer,
    AIAdjustRequestSerializer, SystemSettingSerializer, SystemSettingBulkUpdateSerializer,
    AgentGenerateRequestSerializer, AgentRefineRequestSerializer,
    AgentConfirmRequestSerializer, AgentExecuteRequestSerializer,
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


@api_view(['GET'])
def serve_screenshot(request):
    """
    GET /api/executions/screenshots/?path=<filepath>
    安全地提供 Agent 执行过程中生成的截图文件。
    仅允许访问已记录在 ExecutionRecord.screenshots 或 step_logs 中的路径。
    """
    file_path = request.query_params.get('path', '').strip()
    if not file_path:
        return Response({'error': '缺少 path 参数'}, status=status.HTTP_400_BAD_REQUEST)

    # 规范化路径，防止目录遍历
    try:
        abs_path = os.path.realpath(file_path)
    except (ValueError, TypeError):
        return Response({'error': '无效路径'}, status=status.HTTP_400_BAD_REQUEST)

    # 安全检查 1: 文件必须存在且是文件
    if not os.path.isfile(abs_path):
        raise Http404("截图文件不存在")

    # 安全检查 2: 只允许访问临时目录或项目下的文件
    import tempfile
    allowed_prefixes = [
        tempfile.gettempdir(),
        os.path.realpath(os.path.join(os.path.dirname(__file__), '..', 'media')),
    ]
    if not any(abs_path.startswith(prefix) for prefix in allowed_prefixes):
        return Response({'error': '不允许访问该路径'}, status=status.HTTP_403_FORBIDDEN)

    # 安全检查 3: 验证路径确实存在于某个 ExecutionRecord 中
    exists_in_db = ExecutionRecord.objects.filter(
        Q(screenshots__contains=file_path) |
        Q(screenshot_path=file_path)
    ).exists()
    if not exists_in_db:
        # 也检查 step_logs 中的 screenshot_path
        exists_in_db = ExecutionRecord.objects.filter(
            step_logs__icontains=file_path
        ).exists()
    if not exists_in_db:
        return Response({'error': '未找到关联的执行记录'}, status=status.HTTP_404_NOT_FOUND)

    content_type = mimetypes.guess_type(abs_path)[0] or 'image/png'
    return FileResponse(open(abs_path, 'rb'), content_type=content_type)


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


@api_view(['POST'])
def execute_testcase_agent(request, testcase_id):
    """通过 Agent 模式执行单个测试用例"""
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

    from .ai_engine import _get_model
    try:
        ai_model = _get_model()
    except Exception:
        ai_model = ''

    # 创建执行记录
    record = ExecutionRecord.objects.create(
        project=testcase.project,
        testcase=testcase,
        status='running',
        execution_mode='agent',
        ai_model=ai_model,
    )
    testcase.status = 'running'
    testcase.save(update_fields=['status'])

    # 异步执行
    def _on_complete(tc, result):
        record.status = result['status']
        record.log = result['log']
        record.error_message = result['error_message']
        record.duration = result['duration']
        # 从 script 字段解析 tool_calls_count
        try:
            import json
            script_data = json.loads(result.get('script', '{}'))
            record.tool_calls_count = len(script_data.get('tool_calls', []))
        except (json.JSONDecodeError, TypeError):
            pass
        # 保存 Agent 结构化数据
        record.step_logs = result.get('step_logs', [])
        record.screenshots = result.get('screenshots', [])
        record.agent_response = result.get('agent_response', {})
        record.save()
        tc.status = result['status']
        tc.save(update_fields=['status'])

    def _agent_task():
        result = execution_engine.execute_testcase_with_agent(testcase, base_url)
        _on_complete(testcase, result)
        return result

    from concurrent.futures import ThreadPoolExecutor
    from .models import SystemSetting
    try:
        max_workers = min(int(SystemSetting.get('max_workers', '3')), 2)
    except (ValueError, TypeError):
        max_workers = 2
    executor = ThreadPoolExecutor(max_workers=max_workers)
    executor.submit(_agent_task)

    return Response(
        ExecutionRecordSerializer(record).data,
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(['POST'])
def execute_project_agent(request, project_id):
    """通过 Agent 模式批量执行项目下所有就绪/草稿测试用例"""
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

    from .ai_engine import _get_model
    try:
        ai_model = _get_model()
    except Exception:
        ai_model = ''

    records = []
    for tc in testcases:
        record = ExecutionRecord.objects.create(
            project=project,
            testcase=tc,
            status='running',
            execution_mode='agent',
            ai_model=ai_model,
        )
        tc.status = 'running'
        tc.save(update_fields=['status'])

        def _make_callback(r, t):
            def _on_complete(result):
                r.status = result['status']
                r.log = result['log']
                r.error_message = result['error_message']
                r.duration = result['duration']
                try:
                    import json
                    script_data = json.loads(result.get('script', '{}'))
                    r.tool_calls_count = len(script_data.get('tool_calls', []))
                except (json.JSONDecodeError, TypeError):
                    pass
                # 保存 Agent 结构化数据
                r.step_logs = result.get('step_logs', [])
                r.screenshots = result.get('screenshots', [])
                r.agent_response = result.get('agent_response', {})
                r.save()
                t.status = result['status']
                t.save(update_fields=['status'])
            return _on_complete

        def _make_task(t, callback):
            def _agent_task():
                result = execution_engine.execute_testcase_with_agent(t, project.base_url)
                callback(result)
                return result
            return _agent_task

        from concurrent.futures import ThreadPoolExecutor
        from .models import SystemSetting
        try:
            max_workers = min(int(SystemSetting.get('max_workers', '3')), 2)
        except (ValueError, TypeError):
            max_workers = 2

        # 每个用例独立 executor，避免 Agent 模式下过多并发
        executor = ThreadPoolExecutor(max_workers=max_workers)
        executor.submit(_make_task(tc, _make_callback(record, tc)))
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
    target = serializer.validated_data.get('target', '')

    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    try:
        generated = ai_engine.generate_testcases(
            project_name=project.name,
            base_url=project.base_url or '',
            requirement=requirement,
            project=project,
            target=target,
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
            markdown_content=item.get('markdown_content', ''),
            priority=item.get('priority', ''),
            test_type=item.get('test_type', ''),
            target_page_or_api=target,
            status='draft',
            is_ai_generated=True,
            created_by='agent',
        )
        created.append(tc)

    # 保存 AI 对话记录（存储 messages 格式）
    messages = [
        {"role": "user", "content": requirement},
        {"role": "assistant", "content": json.dumps(generated, ensure_ascii=False)},
    ]
    conv = AIConversation.objects.create(
        conversation_type='generate',
        project=project,
        user_message=requirement,
        ai_response=json.dumps(messages, ensure_ascii=False),
    )

    return Response({
        'testcases': TestCaseSerializer(created, many=True).data,
        'conversation_id': conv.id,
    }, status=status.HTTP_201_CREATED)


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


@api_view(['POST'])
def ai_adjust_testcase(request):
    """AI 对话式调整测试用例"""
    serializer = AIAdjustRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    project_id = serializer.validated_data['project_id']
    conversation_id = serializer.validated_data.get('conversation_id')
    user_feedback = serializer.validated_data['user_feedback']
    current_cases = serializer.validated_data['current_cases']
    testcase_ids = serializer.validated_data.get('testcase_ids', [])

    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    # 恢复之前的对话上下文
    conversation_history = []
    if conversation_id:
        try:
            prev_conv = AIConversation.objects.get(pk=conversation_id)
            # ai_response 存储的是 messages 数组
            try:
                prev_messages = json.loads(prev_conv.ai_response)
                if isinstance(prev_messages, list):
                    conversation_history = prev_messages
            except (json.JSONDecodeError, TypeError):
                pass
        except AIConversation.DoesNotExist:
            pass

    if not conversation_history:
        # 从项目最近的 generate 类型对话恢复
        prev_conv = AIConversation.objects.filter(
            project=project, conversation_type='generate'
        ).order_by('-created_at').first()
        if prev_conv:
            try:
                prev_messages = json.loads(prev_conv.ai_response)
                if isinstance(prev_messages, list):
                    conversation_history = prev_messages
            except (json.JSONDecodeError, TypeError):
                pass

    try:
        adjusted = ai_engine.adjust_testcases(
            project=project,
            conversation_history=conversation_history,
            user_feedback=user_feedback,
            current_cases=current_cases,
        )
    except Exception as e:
        logger.exception("AI adjust testcase failed")
        return Response({'error': f'AI 调整失败: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 将调整后的用例更新到数据库
    # 策略：按位置匹配 testcase_ids，更新对应记录
    if testcase_ids:
        existing_tcs = TestCase.objects.filter(
            id__in=testcase_ids, project=project
        )
        tc_map = {tc.id: tc for tc in existing_tcs}

        for idx, tc_id in enumerate(testcase_ids):
            if tc_id in tc_map and idx < len(adjusted):
                item = adjusted[idx]
                tc = tc_map[tc_id]
                tc.name = item.get('name', tc.name)
                tc.description = item.get('description', tc.description)
                tc.steps = item.get('steps', tc.steps)
                tc.expected_result = item.get('expected_result', tc.expected_result)
                tc.markdown_content = item.get('markdown_content', tc.markdown_content)
                tc.priority = item.get('priority', tc.priority)
                tc.test_type = item.get('test_type', tc.test_type)
                tc.version = (tc.version or 1) + 1
                tc.save()

    # 追加到对话记录
    conversation_history.append({"role": "user", "content": user_feedback})
    conversation_history.append({
        "role": "assistant",
        "content": json.dumps(adjusted, ensure_ascii=False),
    })

    conv = AIConversation.objects.create(
        conversation_type='chat',
        project=project,
        user_message=user_feedback,
        ai_response=json.dumps(conversation_history, ensure_ascii=False),
    )

    return Response({
        'testcases': adjusted,
        'conversation_id': conv.id,
    })


@api_view(['GET', 'PUT'])
def settings_view(request):
    """获取或批量更新系统设置"""
    if request.method == 'GET':
        all_settings = SystemSetting.get_all_dict()
        return Response(all_settings)

    # PUT — 批量更新
    serializer = SystemSettingBulkUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    updates = serializer.validated_data['settings']

    for key, value in updates.items():
        obj, created = SystemSetting.objects.update_or_create(
            key=key,
            defaults={'value': value},
        )
    return Response(SystemSetting.get_all_dict())


# ─── Agent 统一 API ───

@api_view(['POST'])
def agent_generate(request):
    """
    POST /api/agent/generate
    Agent 驱动生成测试用例（包装 ai_generate_testcase，返回 spec 格式）
    """
    serializer = AgentGenerateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    project_id = serializer.validated_data['project_id']
    requirement = serializer.validated_data['requirement']
    target = serializer.validated_data.get('target', '')

    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    try:
        generated = ai_engine.generate_testcases(
            project_name=project.name,
            base_url=project.base_url or '',
            requirement=requirement,
            project=project,
            target=target,
        )
    except Exception as e:
        logger.exception("Agent generate failed")
        return Response({'error': f'Agent 生成失败: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 保存到数据库
    created = []
    for item in generated:
        tc = TestCase.objects.create(
            project=project,
            name=item.get('name', '未命名用例'),
            description=item.get('description', ''),
            steps=item.get('steps', ''),
            expected_result=item.get('expected_result', ''),
            markdown_content=item.get('markdown_content', ''),
            priority=item.get('priority', ''),
            test_type=item.get('test_type', ''),
            target_page_or_api=target,
            status='draft',
            is_ai_generated=True,
            created_by='agent',
        )
        created.append(tc)

    # 保存 AI 对话记录
    messages = [
        {"role": "user", "content": requirement},
        {"role": "assistant", "content": json.dumps(generated, ensure_ascii=False)},
    ]
    conv = AIConversation.objects.create(
        conversation_type='generate',
        project=project,
        user_message=requirement,
        ai_response=json.dumps(messages, ensure_ascii=False),
    )

    # 返回 spec 格式
    first_tc = created[0] if created else None
    return Response({
        'testcase_id': first_tc.id if first_tc else None,
        'version': first_tc.version if first_tc else 1,
        'testcases': TestCaseSerializer(created, many=True).data,
        'steps': generated,
        'markdown': first_tc.markdown_content if first_tc else '',
        'conversation_id': conv.id,
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def agent_refine(request):
    """
    POST /api/agent/refine
    Agent 驱动单用例对话式调整
    """
    serializer = AgentRefineRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    testcase_id = serializer.validated_data['testcase_id']
    user_feedback = serializer.validated_data.get('user_feedback', '')

    try:
        testcase = TestCase.objects.select_related('project').get(pk=testcase_id)
    except TestCase.DoesNotExist:
        return Response({'error': '测试用例不存在'}, status=status.HTTP_404_NOT_FOUND)

    project = testcase.project

    try:
        from .agent_service import refine_testcase_with_agent
        result = refine_testcase_with_agent(
            testcase=testcase,
            project=project,
            user_feedback=user_feedback or None,
        )
    except Exception as e:
        logger.exception("Agent refine failed")
        return Response({'error': f'Agent 调整失败: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({
        'action': result.get('action', 'question'),
        'message': result.get('message', ''),
        'suggestions': result.get('suggestions', []),
        'updated_testcase': result.get('updated_testcase'),
        'version': testcase.version,
        'testcase': TestCaseSerializer(testcase).data,
    })


@api_view(['POST'])
def agent_confirm(request):
    """
    POST /api/agent/confirm
    确认用例（将状态从 draft 改为 ready）
    """
    serializer = AgentConfirmRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    testcase_id = serializer.validated_data['testcase_id']

    try:
        testcase = TestCase.objects.get(pk=testcase_id)
    except TestCase.DoesNotExist:
        return Response({'error': '测试用例不存在'}, status=status.HTTP_404_NOT_FOUND)

    testcase.status = 'ready'
    testcase.save(update_fields=['status'])

    return Response({
        'testcase_id': testcase.id,
        'status': testcase.status,
        'ready_to_execute': True,
    })


@api_view(['POST'])
def agent_execute(request):
    """
    POST /api/agent/execute
    Agent 驱动执行单个测试用例（包装 execute_testcase_agent 逻辑）
    """
    serializer = AgentExecuteRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    testcase_id = serializer.validated_data['testcase_id']

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

    from .ai_engine import _get_model
    try:
        ai_model = _get_model()
    except Exception:
        ai_model = ''

    # 创建执行记录
    record = ExecutionRecord.objects.create(
        project=testcase.project,
        testcase=testcase,
        status='running',
        execution_mode='agent',
        ai_model=ai_model,
    )
    testcase.status = 'running'
    testcase.save(update_fields=['status'])

    # 异步执行
    def _on_complete(tc, result):
        record.status = result['status']
        record.log = result['log']
        record.error_message = result['error_message']
        record.duration = result['duration']
        try:
            script_data = json.loads(result.get('script', '{}'))
            record.tool_calls_count = len(script_data.get('tool_calls', []))
        except (json.JSONDecodeError, TypeError):
            pass
        # 保存 Agent 结构化数据
        record.step_logs = result.get('step_logs', [])
        record.screenshots = result.get('screenshots', [])
        record.agent_response = result.get('agent_response', {})
        record.save()
        tc.status = result['status']
        tc.save(update_fields=['status'])

    def _agent_task():
        result = execution_engine.execute_testcase_with_agent(testcase, base_url)
        _on_complete(testcase, result)
        return result

    from concurrent.futures import ThreadPoolExecutor
    try:
        max_workers = min(int(SystemSetting.get('max_workers', '3')), 2)
    except (ValueError, TypeError):
        max_workers = 2
    executor = ThreadPoolExecutor(max_workers=max_workers)
    executor.submit(_agent_task)

    return Response({
        'test_run_id': record.id,
        'testcase_id': testcase.id,
        'status': 'running',
        'message': 'Agent 执行已提交',
    }, status=status.HTTP_202_ACCEPTED)


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
