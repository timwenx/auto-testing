import json
import logging
import os
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from django.http import JsonResponse, FileResponse, Http404
from django.db.models import Count, Q
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Project, TestCase, ExecutionRecord, AIConversation, SystemSetting, Screenshot
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


def _create_screenshot_records(record, step_logs, screenshot_paths):
    """从执行结果创建持久化 Screenshot 记录"""
    # 先按 screenshot_paths（有序）创建记录
    path_set = set()
    for i, path in enumerate(screenshot_paths, 1):
        if not path or not os.path.isfile(path):
            continue
        # 找到对应的 step 描述
        action = ''
        for step in step_logs:
            if step.get('screenshot_path') == path:
                action = step.get('action', '')
                break
        try:
            Screenshot.objects.create(
                execution=record,
                image=path,  # FileField 可以接受绝对路径
                step_num=i,
                action=action,
            )
            path_set.add(path)
        except Exception as e:
            logger.warning("创建 Screenshot 记录失败: %s", e)

    # 补充 step_logs 中有 screenshot_path 但不在 screenshot_paths 里的
    for step in step_logs:
        sp = step.get('screenshot_path', '')
        if sp and sp not in path_set and os.path.isfile(sp):
            try:
                Screenshot.objects.create(
                    execution=record,
                    image=sp,
                    step_num=step.get('step_num'),
                    action=step.get('action', ''),
                )
            except Exception as e:
                logger.warning("创建 Screenshot 记录失败: %s", e)


def _save_agent_result(record, result):
    """将 Agent 执行结果保存到 ExecutionRecord（统一回调）。

    step_logs 和 tool_calls_count 已通过 AgentRunner._persist_step() 实时写入，
    此处只更新最终状态、耗时、日志等字段。
    """
    record.status = result['status']
    record.log = result['log']
    record.error_message = result['error_message']
    record.duration = result['duration']
    record.screenshots = result.get('screenshots', [])
    record.agent_response = result.get('agent_response', {})
    record.save(update_fields=[
        'status', 'log', 'error_message', 'duration', 'screenshots', 'agent_response',
    ])
    _create_screenshot_records(record, result.get('step_logs', []), result.get('screenshots', []))

    # 兜底推送 execution_end 事件 — 确保即使 AgentRunner 的推送丢失，
    # 客户端也能通过 WebSocket 收到执行结束通知
    try:
        from .event_emitter import _emit_step_event
        _emit_step_event(record.pk, 'execution_end', {
            'status': result['status'],
            'total_steps': len(result.get('step_logs', [])),
            'input_tokens': result.get('agent_response', {}).get('total_input_tokens', 0),
            'output_tokens': result.get('agent_response', {}).get('total_output_tokens', 0),
        })
    except Exception as e:
        logger.warning("[Views] 兜底 execution_end 推送失败: %s", e)


def _save_script_result(record, result):
    """将 Script 执行结果保存到 ExecutionRecord"""
    record.status = result['status']
    record.log = result['log']
    record.error_message = result['error_message']
    record.duration = result['duration']
    record.save()


def _submit_agent_task(task_fn):
    """用 ThreadPoolExecutor 提交 Agent 异步任务"""
    try:
        max_workers = min(int(SystemSetting.get('max_workers', '3')), 2)
    except (ValueError, TypeError):
        max_workers = 2
    executor = ThreadPoolExecutor(max_workers=max_workers)
    executor.submit(task_fn)


def _get_ai_model():
    """获取当前 AI 模型名称，失败返回空字符串"""
    from .ai_engine import _get_model
    try:
        return _get_model()
    except Exception:
        return ''


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
    
    支持的路径格式：
    1. 简单文件名（如 "step1.png"）-> 从 media/screenshots/ 目录查找
    2. 相对路径（如 "screenshots/step1.png"）-> 从 media/ 根目录查找
    3. 绝对路径 -> 必须在允许的目录中（media 或 temp）
    4. 来自 ExecutionRecord.screenshots 或 step_logs 的任何格式
    
    Mac/Linux 友好的路径处理，支持符号链接。
    """
    import tempfile
    from django.conf import settings as django_settings
    
    file_path = request.query_params.get('path', '').strip()
    if not file_path:
        return Response({'error': '缺少 path 参数'}, status=status.HTTP_400_BAD_REQUEST)

    media_root = str(django_settings.MEDIA_ROOT)
    temp_dir = tempfile.gettempdir()
    
    # 智能路径解析：尝试多个位置
    potential_paths = []
    
    # 1. 直接尝试绝对路径
    potential_paths.append(file_path)
    
    # 2. 如果是相对路径，尝试在多个目录下查找
    if not os.path.isabs(file_path):
        # 尝试 media 目录
        potential_paths.append(os.path.join(media_root, file_path))
        
        # 特殊情况：如果不含目录分隔符，尝试多个子目录
        if '/' not in file_path and '\\' not in file_path:
            potential_paths.append(os.path.join(media_root, 'screenshots', file_path))
        
        # 尝试项目根目录下的 images 子目录
        project_root = os.path.dirname(media_root)
        potential_paths.append(os.path.join(project_root, 'images', file_path))
    
    # 3. 从当前工作目录开始查找
    potential_paths.append(os.path.abspath(file_path))
    
    abs_path = None
    for candidate in potential_paths:
        try:
            candidate_abs = os.path.abspath(candidate)
            if os.path.isfile(candidate_abs):
                abs_path = candidate_abs
                break
        except (ValueError, TypeError):
            continue
    
    if not abs_path:
        logger.warning("Screenshot file not found in any location: file_path=%s, tried=%s", file_path, potential_paths)
        raise Http404("截图文件不存在")

    # 安全检查：只允许访问临时目录、media 目录或 images 目录下的文件
    abs_path_real = os.path.realpath(abs_path)
    media_root_real = os.path.realpath(media_root)
    project_root = os.path.dirname(media_root)
    images_dir = os.path.join(project_root, 'images')
    images_dir_real = os.path.realpath(images_dir)
    
    allowed_prefixes = [
        media_root,
        media_root_real,
        os.path.abspath(media_root),
        images_dir,
        images_dir_real,
        os.path.abspath(images_dir),
        temp_dir,
        os.path.realpath(temp_dir),
        os.path.abspath(temp_dir),
    ]
    
    # Mac 特殊处理：/var/folders 等临时目录
    if temp_dir.startswith('/var/folders'):
        allowed_prefixes.append('/private' + temp_dir if not temp_dir.startswith('/private') else temp_dir)
    
    allowed_prefixes_real = [os.path.realpath(p) for p in allowed_prefixes]
    
    path_allowed = (
        any(abs_path.startswith(prefix + '/') or abs_path == prefix for prefix in allowed_prefixes) or
        any(abs_path_real.startswith(prefix + '/') or abs_path_real == prefix for prefix in allowed_prefixes_real)
    )
    
    if not path_allowed:
        logger.warning(
            "Screenshot access denied: path=%s, abs_path=%s, abs_path_real=%s, allowed_prefixes=%s",
            file_path, abs_path, abs_path_real, allowed_prefixes_real
        )
        return Response({'error': '不允许访问该路径'}, status=status.HTTP_403_FORBIDDEN)

    # 验证路径确实存在于某个 ExecutionRecord 或 Screenshot 记录中
    def normalize_for_comparison(path):
        """标准化路径以便比较，支持多种格式"""
        try:
            return os.path.realpath(os.path.abspath(path))
        except Exception:
            return path
    
    normalized_req_path = normalize_for_comparison(file_path)
    normalized_abs_path = normalize_for_comparison(abs_path)
    
    # 检查是否存在于数据库记录中
    exists_in_db = (
        ExecutionRecord.objects.filter(screenshot_path=file_path).exists()
        or ExecutionRecord.objects.filter(screenshot_path=abs_path).exists()
        or ExecutionRecord.objects.filter(screenshot_path=abs_path_real).exists()
        or Screenshot.objects.filter(image=file_path).exists()
        or Screenshot.objects.filter(image=abs_path).exists()
    )

    if not exists_in_db:
        # 检查 screenshots JSON 字段（用多种格式比较）
        for record in ExecutionRecord.objects.only('screenshots'):
            if not record.screenshots:
                continue
            for screenshot_path in record.screenshots:
                if (screenshot_path == file_path or 
                    screenshot_path == abs_path or
                    normalize_for_comparison(screenshot_path) == normalized_req_path or
                    normalize_for_comparison(screenshot_path) == normalized_abs_path):
                    exists_in_db = True
                    break
            if exists_in_db:
                break

    if not exists_in_db:
        # 检查 step_logs 中的 screenshot_path
        for record in ExecutionRecord.objects.only('step_logs'):
            if not record.step_logs:
                continue
            for step in record.step_logs:
                if isinstance(step, dict):
                    sp = step.get('screenshot_path', '')
                    if (sp == file_path or 
                        sp == abs_path or
                        normalize_for_comparison(sp) == normalized_req_path or
                        normalize_for_comparison(sp) == normalized_abs_path):
                        exists_in_db = True
                        break
            if exists_in_db:
                break
    
    if not exists_in_db:
        logger.warning(
            "Screenshot not found in DB records: file_path=%s, abs_path=%s",
            file_path, abs_path
        )
        return Response({'error': '未找到关联的执行记录'}, status=status.HTTP_404_NOT_FOUND)

    # 返回文件
    content_type = mimetypes.guess_type(abs_path)[0] or 'image/png'
    try:
        return FileResponse(open(abs_path, 'rb'), content_type=content_type)
    except IOError as e:
        logger.error("Failed to read screenshot file: %s", e)
        raise Http404("无法读取截图文件")


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
        _save_script_result(record, result)
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
                _save_script_result(r, result)
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

    # 创建执行记录
    record = ExecutionRecord.objects.create(
        project=testcase.project,
        testcase=testcase,
        status='running',
        execution_mode='agent',
        ai_model=_get_ai_model(),
    )
    testcase.status = 'running'
    testcase.save(update_fields=['status'])

    def _agent_task():
        result = execution_engine.execute_testcase_with_agent(testcase, base_url, execution_id=record.pk)
        _save_agent_result(record, result)
        testcase.status = result['status']
        testcase.save(update_fields=['status'])
        return result

    _submit_agent_task(_agent_task)

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

    ai_model = _get_ai_model()
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

        def _make_task(r, t):
            def _agent_task():
                result = execution_engine.execute_testcase_with_agent(t, project.base_url, execution_id=r.pk)
                _save_agent_result(r, result)
                t.status = result['status']
                t.save(update_fields=['status'])
                return result
            return _agent_task

        _submit_agent_task(_make_task(record, tc))
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


def _generate_and_save_testcases(project, requirement, target=''):
    """
    调用 AI 生成测试用例并持久化到数据库。

    Returns:
        (generated_raw, created_tcs, conversation) 三元组
    Raises:
        Exception: AI 调用失败时向上抛出
    """
    generated = ai_engine.generate_testcases(
        project_name=project.name,
        base_url=project.base_url or '',
        requirement=requirement,
        project=project,
        target=target,
    )

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

    return generated, created, conv


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
        generated, created, conv = _generate_and_save_testcases(project, requirement, target)
    except Exception as e:
        logger.exception("AI generate testcase failed")
        return Response({'error': f'AI 生成失败: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
        generated, created, conv = _generate_and_save_testcases(project, requirement, target)
    except Exception as e:
        logger.exception("Agent generate failed")
        return Response({'error': f'Agent 生成失败: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
    执行单个测试用例。支持 script/agent 两种模式。
    若请求中未指定 execution_mode，则使用系统设置 default_execution_mode。
    """
    serializer = AgentExecuteRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    testcase_id = serializer.validated_data['testcase_id']
    execution_mode = serializer.validated_data.get('execution_mode')
    if not execution_mode:
        execution_mode = SystemSetting.get('default_execution_mode', 'script').strip().lower()

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
        execution_mode=execution_mode,
        ai_model=_get_ai_model(),
    )
    testcase.status = 'running'
    testcase.save(update_fields=['status'])

    # ── Agent 模式 ──
    if execution_mode == 'agent':
        def _agent_task():
            result = execution_engine.execute_testcase_with_agent(testcase, base_url, execution_id=record.pk)
            _save_agent_result(record, result)
            testcase.status = result['status']
            testcase.save(update_fields=['status'])
            return result

        _submit_agent_task(_agent_task)

    # ── Script 模式 ──
    else:
        def _on_complete_script(tc, result):
            _save_script_result(record, result)
            tc.status = result['status']
            tc.save(update_fields=['status'])

        execution_engine.execute_testcase_async(testcase, base_url, callback=_on_complete_script)

    return Response({
        'test_run_id': record.id,
        'testcase_id': testcase.id,
        'status': 'running',
        'execution_mode': execution_mode,
        'message': f'{"Agent" if execution_mode == "agent" else "Script"} 执行已提交',
    }, status=status.HTTP_202_ACCEPTED)


# ─── 系统 ───

@api_view(['GET'])
def execution_latest_frame(request, pk):
    """
    GET /api/executions/<id>/latest_frame/
    返回指定执行的最新浏览器截图帧（JPEG）。
    实时帧从内存缓存读取，无数据库查询。
    """
    from .screenshot_stream import get_latest_frame
    ts, jpeg_bytes = get_latest_frame(pk)
    if jpeg_bytes is None:
        return Response({'error': '暂无截图帧'}, status=status.HTTP_404_NOT_FOUND)

    from django.http import HttpResponse
    response = HttpResponse(jpeg_bytes, content_type='image/jpeg')
    response['Content-Length'] = len(jpeg_bytes)
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['X-Frame-Timestamp'] = str(ts or '')
    return response


@api_view(['GET'])
def execution_steps(request, pk):
    """
    GET /api/executions/<id>/steps/
    返回执行记录的 step_logs（用于 WebSocket 连接前的步骤补齐，或页面刷新后恢复状态）。
    """
    try:
        record = ExecutionRecord.objects.get(pk=pk)
    except ExecutionRecord.DoesNotExist:
        return Response({'error': '执行记录不存在'}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        'execution_id': record.id,
        'status': record.status,
        'step_logs': record.step_logs or [],
        'screenshots': record.screenshots or [],
        'agent_response': record.agent_response or {},
        'duration': record.duration,
        'tool_calls_count': record.tool_calls_count,
    })


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
