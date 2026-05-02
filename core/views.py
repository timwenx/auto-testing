import json
import logging
import os
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from django.http import FileResponse, Http404
from django.db.models import Count, Max
from django.db import transaction
from rest_framework import generics, status, serializers as drf_serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Project, TestCase, ExecutionRecord, AIConversation, SystemSetting, Screenshot, RepoAnalysis, PreconditionTemplate, Script, TestPlan, TestPlanItem, PlanExecution
from .serializers import (
    ProjectSerializer, TestCaseSerializer, ExecutionRecordSerializer, ExecutionRecordListSerializer,
    AIConversationSerializer, AIGenerateRequestSerializer, AIAnalyzeRequestSerializer,
    AIAdjustRequestSerializer, SystemSettingSerializer, SystemSettingBulkUpdateSerializer,
    AgentGenerateRequestSerializer, AgentRefineRequestSerializer,
    AgentConfirmRequestSerializer, AgentExecuteRequestSerializer,
    RepoAnalysisSerializer, PreconditionTemplateSerializer,
    BatchGenerateRequestSerializer, BatchSaveRequestSerializer,
    TestCaseReorderSerializer,
    ScriptSerializer, ScriptConvertRequestSerializer, ScriptExecuteRequestSerializer,
    TestPlanSerializer, TestPlanCreateUpdateSerializer,
    TestPlanItemSerializer, TestPlanItemCreateSerializer, TestPlanItemsReorderSerializer,
    PlanExecutionSerializer, PlanExecutionDetailSerializer,
    PlanExecuteRequestSerializer,
)
from . import ai_engine
from . import execution_engine

logger = logging.getLogger(__name__)

# 模块级线程池 — 避免局部变量被 GC 导致 "cannot schedule new futures after shutdown"
_agent_executor = ThreadPoolExecutor(max_workers=2)


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
    # step_logs 已通过 AgentRunner._persist_step() 实时写入 DB（含 screenshot_path）；
    # _build_step_logs 重建的 step_logs 缺少 auto-screenshot 路径，
    # 因此合并：用 DB 中已有的 screenshot_path 补充到 result 的 step_logs 中。
    result_step_logs = result.get('step_logs', [])
    if result_step_logs:
        existing_logs = list(record.step_logs or [])
        if existing_logs:
            # 按 step_num 建立 screenshot_path 映射
            sp_map = {}
            for s in existing_logs:
                if isinstance(s, dict) and s.get('screenshot_path'):
                    sp_map[s.get('step_num')] = s['screenshot_path']
            # 将 DB 中已有的 screenshot_path 回填到 result step_logs
            for s in result_step_logs:
                if isinstance(s, dict) and not s.get('screenshot_path'):
                    sp = sp_map.get(s.get('step_num'), '')
                    if sp:
                        s['screenshot_path'] = sp
        record.step_logs = result_step_logs

    # tool_calls_count 兜底：若 _persist_step 已设置则保留，否则从 step_logs / script 推断。
    if record.tool_calls_count == 0:
        count = len(result.get('step_logs', []))
        if count == 0:
            try:
                script_data = json.loads(result.get('script', '{}'))
                count = len(script_data.get('tool_calls', []))
            except (json.JSONDecodeError, TypeError):
                pass
        record.tool_calls_count = count

    record.status = result['status']
    # 将 tool_calls JSON 追加到 log 末尾，确保脚本转换能获取完整输入参数
    log_text = result.get('log', '')
    script_json = result.get('script', '')
    if script_json:
        log_text += '\n\n=== TOOL_CALLS_JSON ===\n' + script_json
    record.log = log_text
    record.error_message = result['error_message']
    record.duration = result['duration']
    record.screenshots = result.get('screenshots', [])
    record.agent_response = result.get('agent_response', {})
    record.save(update_fields=[
        'status', 'log', 'error_message', 'duration', 'screenshots', 'agent_response',
        'step_logs', 'tool_calls_count',
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


def _submit_agent_task(task_fn):
    """用模块级线程池提交 Agent 异步任务"""
    _agent_executor.submit(task_fn)


def _execute_testcases_sequential_by_records(testcases, records, project):
    """顺序执行已创建 ExecutionRecord 的一组测试用例。

    Args:
        testcases: list[TestCase]，已按 sort_order 排序
        records: list[ExecutionRecord]，与 testcases 一一对应
        project: Project 对象
    """
    for tc, record in zip(testcases, records):
        try:
            result = execution_engine.execute_testcase_with_agent(tc, project.base_url, execution_id=record.pk)
            _save_agent_result(record, result)
            tc.status = result['status']
            tc.save(update_fields=['status'])
        except Exception as e:
            logger.exception("[GroupTask] 执行用例 %s 失败: %s", tc.name, e)
            record.status = 'failed'
            record.error_message = str(e)
            record.save(update_fields=['status', 'error_message'])
            tc.status = 'failed'
            tc.save(update_fields=['status'])


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
    serializer_class = ExecutionRecordListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        testcase_id = self.request.query_params.get('testcase')
        if testcase_id:
            qs = qs.filter(testcase_id=testcase_id)
        has_script = self.request.query_params.get('has_replay_script')
        if has_script:
            qs = qs.exclude(replay_script__isnull=True).exclude(replay_script='')
        source_exec = self.request.query_params.get('source_execution')
        if source_exec:
            qs = qs.filter(source_execution_id=source_exec)
        status = self.request.query_params.get('status')
        if status:
            qs = qs.filter(status=status)
        execution_mode = self.request.query_params.get('execution_mode')
        if execution_mode:
            qs = qs.filter(execution_mode=execution_mode)
        plan_execution = self.request.query_params.get('plan_execution')
        if plan_execution:
            qs = qs.exclude(plan_execution__isnull=True)
        created_after = self.request.query_params.get('created_after')
        if created_after:
            qs = qs.filter(created_at__date__gte=created_after)
        created_before = self.request.query_params.get('created_before')
        if created_before:
            qs = qs.filter(created_at__date__lte=created_before)
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
    
    path_allowed = False
    for pfx in set(allowed_prefixes + allowed_prefixes_real):
        # 规范化路径分隔符，兼容 Windows 反斜杠
        norm_prefix = os.path.normpath(pfx)
        if (os.path.normpath(abs_path).startswith(norm_prefix + os.sep) or
                os.path.normpath(abs_path) == norm_prefix or
                os.path.normpath(abs_path_real).startswith(norm_prefix + os.sep) or
                os.path.normpath(abs_path_real) == norm_prefix):
            path_allowed = True
            break
    
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

    def _parse_execution_id_from_path(path):
        """
        从路径中解析 execution_id。
        新路径格式: {execution_id}/xxx.png
        旧路径格式: screenshots/{project_id}/{execution_id}/xxx.png
        同时支持 / 和 \ 分隔符（Windows 兼容）。
        """
        import re
        # 统一分隔符以便 regex 匹配
        norm_path = path.replace('\\', '/')
        # 新格式: "24/auto_123456.jpg"
        m = re.match(r'^(\d+)/', norm_path)
        if m:
            return int(m.group(1))
        # 旧格式: "screenshots/2/18/step_1.png"
        m = re.match(r'^screenshots/\d+/(\d+)/', norm_path)
        if m:
            return int(m.group(1))
        # 绝对路径：尝试从尾部匹配 .../{execution_id}/xxx.png
        m = re.search(r'[\\/](\d+)[\\/][^\\/]+\.\w+$', path)
        if m:
            return int(m.group(1))
        return None

    normalized_req_path = normalize_for_comparison(file_path)
    normalized_abs_path = normalize_for_comparison(abs_path)

    # 计算相对 media root 的路径
    relative_to_media = None
    try:
        relative_to_media = os.path.relpath(abs_path_real, media_root)
    except (ValueError, Exception):
        pass

    # 检查是否存在于数据库记录中（使用索引查询，避免全表扫描）
    exists_in_db = (
        ExecutionRecord.objects.filter(screenshot_path=file_path).exists()
        or ExecutionRecord.objects.filter(screenshot_path=abs_path).exists()
        or ExecutionRecord.objects.filter(screenshot_path=abs_path_real).exists()
        or Screenshot.objects.filter(image=file_path).exists()
        or Screenshot.objects.filter(image=abs_path).exists()
    )

    # auto_captured 截图的 Screenshot.image 存储的是 media_root 相对路径
    if not exists_in_db and relative_to_media:
        exists_in_db = Screenshot.objects.filter(image=relative_to_media).exists()

    # 从路径中解析 execution_id，只查询该执行的记录（避免全表扫描）
    if not exists_in_db:
        exec_id = _parse_execution_id_from_path(file_path)
        if not exec_id and relative_to_media:
            exec_id = _parse_execution_id_from_path(relative_to_media)

        if exec_id:
            # 只查询指定 execution 的 screenshots 和 step_logs
            try:
                record = ExecutionRecord.objects.only('screenshots', 'step_logs').get(pk=exec_id)
                # 检查 screenshots JSON 字段
                if record.screenshots:
                    for screenshot_path in record.screenshots:
                        if (screenshot_path == file_path or
                            screenshot_path == abs_path or
                            normalize_for_comparison(screenshot_path) == normalized_req_path or
                            normalize_for_comparison(screenshot_path) == normalized_abs_path):
                            exists_in_db = True
                            break
                # 检查 step_logs 中的 screenshot_path
                if not exists_in_db and record.step_logs:
                    for step in record.step_logs:
                        if isinstance(step, dict):
                            sp = step.get('screenshot_path', '')
                            if (sp == file_path or
                                sp == abs_path or
                                normalize_for_comparison(sp) == normalized_req_path or
                                normalize_for_comparison(sp) == normalized_abs_path):
                                exists_in_db = True
                                break
            except ExecutionRecord.DoesNotExist:
                pass

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
    """通过 Agent 模式批量执行项目下所有就绪/草稿测试用例。

    按 feature_group 分组，每个组内按 sort_order 顺序执行，
    不同功能组之间并行提交到线程池。
    """
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    if not project.base_url:
        return Response(
            {'error': '请先在项目中配置测试目标 URL'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    testcases = list(project.testcases.filter(
        status__in=['draft', 'ready']
    ).order_by('feature_group', 'sort_order'))
    if not testcases:
        return Response(
            {'error': '没有可执行的测试用例'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 按 feature_group 分组
    from collections import OrderedDict
    groups = OrderedDict()
    for tc in testcases:
        fg = tc.feature_group or ''
        groups.setdefault(fg, []).append(tc)

    # 为每个功能组创建 ExecutionRecord 并保存，然后提交顺序执行任务
    ai_model = _get_ai_model()
    all_records = []
    for fg, group_tcs in groups.items():
        # 预创建所有 ExecutionRecord（HTTP 202 立即返回所有 ID）
        group_records = []
        for tc in group_tcs:
            record = ExecutionRecord.objects.create(
                project=project,
                testcase=tc,
                status='running',
                execution_mode='agent',
                ai_model=ai_model,
            )
            tc.status = 'running'
            tc.save(update_fields=['status'])
            group_records.append(record)
        all_records.extend(group_records)

        # 提交组任务到线程池 — 组内顺序执行
        _submit_agent_task(lambda tcs=group_tcs, recs=group_records: _execute_testcases_sequential_by_records(tcs, recs, project))

    return Response(
        ExecutionRecordSerializer(all_records, many=True).data,
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
    for idx, item in enumerate(generated, 1):
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
            feature_group=item.get('feature_group', ''),
            sort_order=idx,
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
                tc.feature_group = item.get('feature_group', tc.feature_group)
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


@api_view(['GET'])
def cli_check(request):
    """GET /api/settings/cli-check/ — 检测 Claude CLI 是否可用"""
    from .cli_service import is_cli_available
    cli_path = request.query_params.get('cli_path', '').strip() or None
    available, info = is_cli_available(cli_path)
    return Response({
        'available': available,
        'version': info if available else '',
        'error': info if not available else None,
    })


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
    使用 Agent 模式执行单个测试用例。
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

    return Response({
        'test_run_id': record.id,
        'testcase_id': testcase.id,
        'status': 'running',
        'execution_mode': 'agent',
        'message': 'Agent 执行已提交',
    }, status=status.HTTP_202_ACCEPTED)


# ─── 系统 ───

@api_view(['GET', 'HEAD'])
def execution_latest_frame(request, pk):
    """
    GET/HEAD /api/executions/<id>/latest_frame/
    返回指定执行的最新浏览器截图帧（JPEG）。
    实时帧从内存缓存读取，无数据库查询。
    HEAD 方法用于前端验证帧可用性，不传输图片数据。
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
    返回执行记录的 step_logs 和截图（包括自动截图）。
    用于 WebSocket 连接前的步骤补齐，或页面刷新后恢复状态。
    """
    try:
        record = ExecutionRecord.objects.get(pk=pk)
    except ExecutionRecord.DoesNotExist:
        return Response({'error': '执行记录不存在'}, status=status.HTTP_404_NOT_FOUND)

    # 合并手动截图（JSONField）和自动截图（Screenshot model）
    screenshots = list(record.screenshots or [])
    auto_screenshots = list(
        Screenshot.objects.filter(execution=record, auto_captured=True)
        .order_by('created_at')
        .values_list('image', flat=True)
    )

    return Response({
        'execution_id': record.id,
        'status': record.status,
        'step_logs': record.step_logs or [],
        'screenshots': screenshots,
        'auto_screenshots': auto_screenshots,
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


# ══════════════════════════════════════════════════════════════════
# 脚本回放：转换 / 获取 / 更新 / 执行
# ══════════════════════════════════════════════════════════════════

@api_view(['POST'])
def convert_to_script(request, pk):
    """POST /api/executions/<pk>/convert-script/ — 将 agent 执行记录转为结构化回放脚本"""
    try:
        record = ExecutionRecord.objects.select_related('project', 'testcase').get(pk=pk)
    except ExecutionRecord.DoesNotExist:
        return Response({'error': '执行记录不存在'}, status=status.HTTP_404_NOT_FOUND)

    if record.execution_mode != 'agent':
        return Response({'error': '仅支持转换 Agent 模式的执行记录'}, status=status.HTTP_400_BAD_REQUEST)

    terminal = ['passed', 'failed', 'error']
    if record.status not in terminal:
        return Response({'error': '仅支持转换已完成的执行记录'}, status=status.HTTP_400_BAD_REQUEST)

    from .script_converter import convert_execution_to_script
    try:
        script = convert_execution_to_script(record)
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    record.replay_script = script
    record.save(update_fields=['replay_script'])

    return Response(script)


@api_view(['GET'])
def get_replay_script(request, pk):
    """GET /api/executions/<pk>/replay-script/ — 获取已转换的回放脚本"""
    try:
        record = ExecutionRecord.objects.get(pk=pk)
    except ExecutionRecord.DoesNotExist:
        return Response({'error': '执行记录不存在'}, status=status.HTTP_404_NOT_FOUND)

    if not record.replay_script:
        return Response({'error': '尚未生成回放脚本'}, status=status.HTTP_404_NOT_FOUND)

    return Response(record.replay_script)


@api_view(['PUT'])
def update_replay_script(request, pk):
    """PUT /api/executions/<pk>/replay-script/ — 更新回放脚本（编辑参数/步骤）"""
    try:
        record = ExecutionRecord.objects.get(pk=pk)
    except ExecutionRecord.DoesNotExist:
        return Response({'error': '执行记录不存在'}, status=status.HTTP_404_NOT_FOUND)

    data = request.data

    # 删除脚本
    if isinstance(data, dict) and data.get('delete'):
        record.replay_script = None
        record.save(update_fields=['replay_script'])
        return Response({'deleted': True})

    if not record.replay_script:
        return Response({'error': '尚未生成回放脚本'}, status=status.HTTP_404_NOT_FOUND)

    if not isinstance(data, dict):
        return Response({'error': '无效的脚本数据'}, status=status.HTTP_400_BAD_REQUEST)

    # 合并更新：允许部分更新 parameters 和 steps
    current = record.replay_script
    if 'parameters' in data:
        current['parameters'] = data['parameters']
    if 'steps' in data:
        current['steps'] = data['steps']
    if 'name' in data:
        current['name'] = data['name']
    if 'base_url' in data:
        current['base_url'] = data['base_url']

    record.replay_script = current
    record.save(update_fields=['replay_script'])

    return Response(current)


@api_view(['POST'])
def replay_execute(request, pk):
    """POST /api/executions/<pk>/replay-execute/ — 执行回放脚本"""
    try:
        source_record = ExecutionRecord.objects.select_related('project', 'testcase').get(pk=pk)
    except ExecutionRecord.DoesNotExist:
        return Response({'error': '执行记录不存在'}, status=status.HTTP_404_NOT_FOUND)

    if not source_record.replay_script:
        return Response({'error': '尚未生成回放脚本，请先转换'}, status=status.HTTP_400_BAD_REQUEST)

    parameter_overrides = request.data.get('parameter_overrides', {})

    # 创建新的执行记录
    new_record = ExecutionRecord.objects.create(
        project=source_record.project,
        testcase=source_record.testcase,
        status='running',
        execution_mode='replay',
        source_execution=source_record,
    )

    def _replay_task():
        from .script_executor import ReplayExecutor
        executor = ReplayExecutor(new_record, source_record)
        executor.run(source_record.replay_script, parameter_overrides)

    _submit_agent_task(_replay_task)

    return Response(
        ExecutionRecordSerializer(new_record).data,
        status=status.HTTP_202_ACCEPTED,
    )


# ══════════════════════════════════════════════════════════════════
# 仓库分析 + 批量用例生成 API
# ══════════════════════════════════════════════════════════════════

@api_view(['POST'])
def repo_pull(request, project_id):
    """POST /api/projects/<id>/repo/pull/ — 拉取/更新 Git 仓库"""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    try:
        from . import repo_service
        local_path = repo_service.clone_or_update_repo(project)
    except RuntimeError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.exception("Repo pull failed for project #%s", project_id)
        return Response({'error': f'仓库拉取失败: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({
        'status': 'ready',
        'local_path': local_path,
    })


@api_view(['POST'])
def repo_analyze(request, project_id):
    """POST /api/projects/<id>/repo/analyze/ — 触发仓库代码分析（异步）"""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    if not project.local_repo_path and not project.repo_url:
        return Response({'error': '项目未配置 Git 仓库'}, status=status.HTTP_400_BAD_REQUEST)

    # 自动恢复卡住的分析（心跳超时 > 60s）
    from django.utils import timezone
    from datetime import timedelta
    from django.db import models as db_models
    stale_cutoff = timezone.now() - timedelta(seconds=60)
    stale_analyses = RepoAnalysis.objects.filter(
        project=project, status='analyzing',
    ).filter(
        db_models.Q(last_heartbeat__isnull=True, created_at__lt=stale_cutoff)
        | db_models.Q(last_heartbeat__lt=stale_cutoff)
    )
    if stale_analyses.exists():
        stale_analyses.update(status='failed', analysis_log='分析进程中断（心跳超时），已自动标记为失败')

    # 防止重复触发分析
    active = RepoAnalysis.objects.filter(project=project, status='analyzing').exists()
    if active:
        return Response({'error': '该项目的分析正在进行中'}, status=status.HTTP_409_CONFLICT)

    def _analyze_task():
        from .repo_analyzer import analyze_repo
        try:
            analyze_repo(project)
        except Exception as e:
            logger.exception("[RepoAnalyze] Task failed for project #%s: %s", project_id, e)

    _submit_agent_task(_analyze_task)

    return Response({
        'status': 'analyzing',
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
def repo_analysis_detail(request, project_id):
    """GET /api/projects/<id>/repo/analysis/ — 获取最新的仓库分析结果"""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    analysis = project.repo_analyses.order_by('-created_at').first()
    if not analysis:
        return Response({'analysis': None})

    data = RepoAnalysisSerializer(analysis).data

    # 计算卡住检测和已用时间
    if analysis.status == 'analyzing':
        from django.utils import timezone
        ref_time = analysis.last_heartbeat or analysis.created_at
        if ref_time:
            data['is_stuck'] = (timezone.now() - ref_time).total_seconds() > 30
        else:
            data['is_stuck'] = False
        start = analysis.started_at or analysis.created_at
        data['elapsed_seconds'] = int((timezone.now() - start).total_seconds()) if start else 0
    else:
        data['is_stuck'] = False
        data['elapsed_seconds'] = 0

    return Response({'analysis': data})


@api_view(['POST'])
def repo_analysis_reset(request, project_id):
    """POST /api/projects/<id>/repo/analysis/reset/ — 重置卡住的分析"""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    updated = RepoAnalysis.objects.filter(
        project=project, status='analyzing',
    ).update(status='failed', analysis_log='用户手动重置')

    return Response({'reset_count': updated})


@api_view(['GET'])
def repo_analysis_list(request, project_id):
    """GET /api/projects/<id>/repo/analysis/list/ — 获取历史分析列表"""
    try:
        Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    analyses = RepoAnalysis.objects.filter(project_id=project_id)[:20]
    return Response({
        'analyses': RepoAnalysisSerializer(analyses, many=True).data,
    })


@api_view(['POST'])
def batch_generate_testcases(request, project_id):
    """POST /api/projects/<id>/batch-generate/ — 批量生成测试用例（不保存 DB）"""
    from django.utils import timezone
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    serializer = BatchGenerateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    selected_items = serializer.validated_data['selected_items']
    descriptions = serializer.validated_data.get('descriptions', {})
    precondition_id = serializer.validated_data.get('precondition_id')

    if not selected_items:
        return Response({'error': '请至少选择一个目标'}, status=status.HTTP_400_BAD_REQUEST)

    # Only validate precondition when one is explicitly provided
    if precondition_id is not None:
        try:
            PreconditionTemplate.objects.get(pk=precondition_id)
        except PreconditionTemplate.DoesNotExist:
            return Response({'error': '前置条件模板不存在'}, status=status.HTTP_404_NOT_FOUND)

    # Save generation draft as 'generating' status immediately
    project.generation_draft = {
        'selected_items': selected_items,
        'descriptions': descriptions,
        'precondition_id': precondition_id,
        'status': 'generating',
        'step': 3,
        'started_at': timezone.now().isoformat(),
    }
    project.save(update_fields=['generation_draft', 'updated_at'])

    # Run generation in background thread to avoid blocking ASGI
    _project_id = project.id
    _selected_items = selected_items
    _descriptions = descriptions
    _precondition_id = precondition_id

    def _do_generate():
        from .models import Project as _Project
        from .batch_generator import generate_testcases_for_items, MAX_ITEMS_PER_BATCH
        from django.db import close_old_connections
        from django.utils import timezone as _tz
        import math

        total_items = len(_selected_items)
        total_batches = math.ceil(total_items / MAX_ITEMS_PER_BATCH)

        def _update_draft(**kwargs):
            """Update generation draft with progress info"""
            try:
                close_old_connections()
                p = _Project.objects.get(pk=_project_id)
                draft = dict(p.generation_draft or {})
                draft.update(kwargs)
                p.generation_draft = draft
                p.save(update_fields=['generation_draft', 'updated_at'])
            except Exception:
                pass

        # ── Heartbeat: every 10s update last_heartbeat ──
        _stop_heartbeat = threading.Event()

        def _heartbeat_loop():
            while not _stop_heartbeat.wait(10):
                try:
                    close_old_connections()
                    p = _Project.objects.get(pk=_project_id)
                    draft = dict(p.generation_draft or {})
                    draft['last_heartbeat'] = _tz.now().isoformat()
                    p.generation_draft = draft
                    p.save(update_fields=['generation_draft', 'updated_at'])
                except Exception:
                    pass

        heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
        heartbeat_thread.start()

        try:
            close_old_connections()
            print(f"[BatchGenerate] 项目#{_project_id} 开始生成: {total_items} 个目标, {total_batches} 批")

            all_testcases = []
            for batch_idx in range(total_batches):
                batch_start = batch_idx * MAX_ITEMS_PER_BATCH
                batch_end = min(batch_start + MAX_ITEMS_PER_BATCH, total_items)
                batch_items = _selected_items[batch_start:batch_end]
                batch_num = batch_idx + 1

                print(f"[BatchGenerate] 项目#{_project_id} 第 {batch_num}/{total_batches} 批 ({len(batch_items)} 个目标)...")
                _update_draft(
                    progress=f'正在生成第{batch_start + 1}/{total_items}个目标',
                    current_batch=batch_num,
                    total_batches=total_batches,
                )

                close_old_connections()
                proj = _Project.objects.get(pk=_project_id)
                prec = None
                if _precondition_id:
                    try:
                        prec = PreconditionTemplate.objects.get(pk=_precondition_id)
                    except PreconditionTemplate.DoesNotExist:
                        pass

                batch_result = generate_testcases_for_items(
                    proj, batch_items, _descriptions, prec
                )
                all_testcases.extend(batch_result)
                print(f"[BatchGenerate] 项目#{_project_id} 第 {batch_num} 批完成, 累计 {len(all_testcases)} 条用例")

            # No retry — if generation fails, report failure directly
            close_old_connections()
            proj = _Project.objects.get(pk=_project_id)
            if all_testcases:
                print(f"[BatchGenerate] 项目#{_project_id} 生成完成: {len(all_testcases)} 条用例")
                proj.generation_draft = {
                    'selected_items': _selected_items,
                    'descriptions': _descriptions,
                    'precondition_id': _precondition_id,
                    'generated_cases': all_testcases,
                    'status': 'completed',
                    'step': 3,
                    'started_at': proj.generation_draft.get('started_at') if proj.generation_draft else None,
                }
            else:
                print(f"[BatchGenerate] 项目#{_project_id} 生成失败: AI 未返回有效用例")
                proj.generation_draft = {
                    'selected_items': _selected_items,
                    'descriptions': _descriptions,
                    'precondition_id': _precondition_id,
                    'status': 'failed',
                    'error': 'AI 未能生成有效用例，请检查目标描述是否足够详细后重试',
                    'step': 3,
                }
            proj.save(update_fields=['generation_draft', 'updated_at'])
        except Exception as e:
            logger.exception("Background batch generate failed for project #%s", _project_id)
            print(f"[BatchGenerate] 项目#{_project_id} 异常: {e}")
            try:
                close_old_connections()
                proj = _Project.objects.get(pk=_project_id)
                proj.generation_draft = {
                    **proj.generation_draft,
                    'status': 'failed',
                    'error': str(e),
                }
                proj.save(update_fields=['generation_draft', 'updated_at'])
            except Exception:
                logger.exception("Failed to save error state for project #%s", _project_id)
            finally:
                _stop_heartbeat.set()
                heartbeat_thread.join(timeout=2)

    import threading
    t = threading.Thread(target=_do_generate, daemon=True)
    t.start()

    return Response({
        'status': 'generating',
        'message': '已开始生成，请稍候轮询结果',
    })
@api_view(['POST'])
def batch_save_testcases(request, project_id):
    """POST /api/projects/<id>/batch-save/ — 批量保存确认后的测试用例"""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    serializer = BatchSaveRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    testcases_data = serializer.validated_data['testcases']
    if not testcases_data:
        return Response({'error': '用例列表为空'}, status=status.HTTP_400_BAD_REQUEST)

    created = []
    with transaction.atomic():
        for idx, item in enumerate(testcases_data, 1):
            tc = TestCase.objects.create(
                project=project,
                name=item.get('name', '未命名用例'),
                description=item.get('description', ''),
                steps=item.get('steps', ''),
                expected_result=item.get('expected_result', ''),
                markdown_content=item.get('markdown_content', ''),
                priority=item.get('priority', ''),
                test_type=item.get('test_type', ''),
                target_page_or_api=item.get('target_page_or_api', ''),
                feature_group=item.get('feature_group', ''),
                sort_order=item.get('sort_order', idx),
                test_context=item.get('test_context', {}),
                status='draft',
                is_ai_generated=True,
                created_by='claude_cli',
            )
            created.append(tc)

    # Clear generation draft after successful save
    project.generation_draft = {}
    project.save(update_fields=['generation_draft', 'updated_at'])

    return Response({
        'testcases': TestCaseSerializer(created, many=True).data,
        'count': len(created),
    }, status=status.HTTP_201_CREATED)


@api_view(['GET', 'POST', 'DELETE'])
def generation_draft(request, project_id):
    """GET/POST/DELETE /api/projects/<id>/generation-draft/ — 管理生成草稿状态"""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        draft = dict(project.generation_draft or {})
        # Stuck detection: if generating but heartbeat stale > 30s, mark as failed
        if draft.get('status') == 'generating':
            from django.utils import timezone as _tz
            from datetime import datetime
            is_stuck = False
            last_hb_str = draft.get('last_heartbeat')
            started_at_str = draft.get('started_at')
            ref_str = last_hb_str or started_at_str
            if ref_str:
                try:
                    ref_time = datetime.fromisoformat(ref_str)
                    if hasattr(ref_time, 'tzinfo') and ref_time.tzinfo is None:
                        from datetime import timezone as _pytz
                        ref_time = ref_time.replace(tzinfo=_pytz.utc)
                    elapsed = (_tz.now() - ref_time).total_seconds()
                    is_stuck = elapsed > 30
                except (ValueError, TypeError):
                    pass
            if is_stuck:
                draft['status'] = 'failed'
                draft['error'] = '生成进程中断（心跳超时），可能是服务重启或进程异常'
                project.generation_draft = draft
                project.save(update_fields=['generation_draft', 'updated_at'])
            else:
                draft['is_stuck'] = False
        return Response({'draft': draft})

    elif request.method == 'POST':
        project.generation_draft = request.data.get('draft', request.data)
        project.save(update_fields=['generation_draft', 'updated_at'])
        return Response({'draft': project.generation_draft})

    elif request.method == 'DELETE':
        project.generation_draft = {}
        project.save(update_fields=['generation_draft', 'updated_at'])
        return Response({'draft': {}})


@api_view(['POST'])
def testcase_reorder(request, project_id):
    """POST /api/projects/<id>/testcases/reorder/ — 批量调整用例排序和功能点分组"""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    serializer = TestCaseReorderSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    orders = serializer.validated_data['orders']
    if not orders:
        return Response({'error': '排序数据为空'}, status=status.HTTP_400_BAD_REQUEST)

    # 构建更新映射
    order_map = {}
    for item in orders:
        order_map[item['id']] = {
            'feature_group': item.get('feature_group', ''),
            'sort_order': item.get('sort_order', 0),
        }

    tc_ids = list(order_map.keys())
    testcases = TestCase.objects.filter(id__in=tc_ids, project=project)
    if testcases.count() != len(tc_ids):
        found_ids = set(testcases.values_list('id', flat=True))
        missing = set(tc_ids) - found_ids
        return Response(
            {'error': f'用例不存在或不属于该项目: {missing}'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    updated_count = 0
    with transaction.atomic():
        for tc in testcases:
            update_data = order_map[tc.id]
            tc.feature_group = update_data['feature_group']
            tc.sort_order = update_data['sort_order']
            tc.save(update_fields=['feature_group', 'sort_order'])
            updated_count += 1

    return Response({
        'updated': updated_count,
    })


@api_view(['GET'])
def project_feature_groups(request, project_id):
    """GET /api/projects/<id>/feature-groups/ — 获取项目下所有功能点分组（含用例概要）"""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    # 基础分组 + 计数
    groups = (
        TestCase.objects.filter(project=project)
        .values('feature_group')
        .annotate(count=Count('id'))
        .order_by('feature_group')
    )

    # 是否返回详细信息（含每个用例的最近执行状态）
    detailed = request.query_params.get('detailed', '').lower() in ('true', '1', 'yes')

    result = []
    for g in groups:
        name = g['feature_group'] or '未分组'
        entry = {
            'name': name,
            'count': g['count'],
        }

        if detailed:
            testcases = TestCase.objects.filter(
                project=project, feature_group=g['feature_group']
            ).order_by('sort_order')

            tc_list = []
            for tc in testcases:
                latest_exec = tc.executions.order_by('-created_at').first()
                tc_list.append({
                    'id': tc.id,
                    'name': tc.name,
                    'description': tc.description,
                    'steps': tc.steps,
                    'expected_result': tc.expected_result,
                    'markdown_content': tc.markdown_content,
                    'status': tc.status,
                    'priority': tc.priority,
                    'test_type': tc.test_type,
                    'feature_group': tc.feature_group,
                    'sort_order': tc.sort_order,
                    'latest_execution_status': latest_exec.status if latest_exec else None,
                    'latest_execution_id': latest_exec.id if latest_exec else None,
                })
            entry['testcases'] = tc_list

        result.append(entry)

    return Response({'groups': result})


# ─── 前置条件模板 CRUD ───

@api_view(['GET'])
def precondition_list(request):
    """GET /api/preconditions/ — 列出所有前置条件模板"""
    templates = PreconditionTemplate.objects.all()
    return Response({
        'preconditions': PreconditionTemplateSerializer(templates, many=True).data,
    })


@api_view(['POST'])
def precondition_create(request):
    """POST /api/preconditions/ — 创建前置条件模板"""
    serializer = PreconditionTemplateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    template = serializer.save()
    return Response(PreconditionTemplateSerializer(template).data, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
def precondition_update(request, pk):
    """PUT /api/preconditions/<pk>/ — 更新前置条件模板"""
    try:
        template = PreconditionTemplate.objects.get(pk=pk)
    except PreconditionTemplate.DoesNotExist:
        return Response({'error': '模板不存在'}, status=status.HTTP_404_NOT_FOUND)

    serializer = PreconditionTemplateSerializer(template, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(PreconditionTemplateSerializer(template).data)


@api_view(['DELETE'])
def precondition_delete(request, pk):
    """DELETE /api/preconditions/<pk>/ — 删除前置条件模板"""
    try:
        template = PreconditionTemplate.objects.get(pk=pk)
    except PreconditionTemplate.DoesNotExist:
        return Response({'error': '模板不存在'}, status=status.HTTP_404_NOT_FOUND)

    if template.is_default:
        return Response({'error': '系统内置模板不可删除'}, status=status.HTTP_400_BAD_REQUEST)

    template.delete()
    return Response({'deleted': True})


# ══════════════════════════════════════════════════════════════════
# Script CRUD + Convert API
# ══════════════════════════════════════════════════════════════════

@api_view(['GET'])
def script_list(request):
    """GET /api/scripts/ — 脚本列表，支持 project/feature_group/status 筛选"""
    qs = Script.objects.select_related('project', 'testcase').all()
    project_id = request.query_params.get('project')
    if project_id:
        qs = qs.filter(project_id=project_id)
    feature_group = request.query_params.get('feature_group')
    if feature_group:
        qs = qs.filter(feature_group=feature_group)
    script_status = request.query_params.get('status')
    if script_status:
        qs = qs.filter(status=script_status)
    serializer = ScriptSerializer(qs, many=True)
    return Response({'scripts': serializer.data})


@api_view(['GET'])
def script_detail(request, pk):
    """GET /api/scripts/<id>/ — 脚本详情"""
    try:
        script = Script.objects.select_related('project', 'testcase', 'source_execution').get(pk=pk)
    except Script.DoesNotExist:
        return Response({'error': '脚本不存在'}, status=status.HTTP_404_NOT_FOUND)
    return Response(ScriptSerializer(script).data)


@api_view(['PUT'])
def script_update(request, pk):
    """PUT /api/scripts/<id>/ — 更新脚本"""
    try:
        script = Script.objects.get(pk=pk)
    except Script.DoesNotExist:
        return Response({'error': '脚本不存在'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ScriptSerializer(script, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(ScriptSerializer(script).data)


@api_view(['DELETE'])
def script_delete(request, pk):
    """DELETE /api/scripts/<id>/ — 删除脚本"""
    try:
        script = Script.objects.get(pk=pk)
    except Script.DoesNotExist:
        return Response({'error': '脚本不存在'}, status=status.HTTP_404_NOT_FOUND)

    script.delete()
    return Response({'deleted': True})


@api_view(['POST'])
def script_convert(request):
    """POST /api/scripts/convert/ — 从 ExecutionRecord 生成 Script"""
    serializer = ScriptConvertRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    execution_id = serializer.validated_data['execution_id']
    name = serializer.validated_data.get('name', '')
    feature_group = serializer.validated_data.get('feature_group', '')

    try:
        record = ExecutionRecord.objects.select_related('project', 'testcase').get(pk=execution_id)
    except ExecutionRecord.DoesNotExist:
        return Response({'error': '执行记录不存在'}, status=status.HTTP_404_NOT_FOUND)

    if record.execution_mode != 'agent':
        return Response({'error': '仅支持转换 Agent 模式的执行记录'}, status=status.HTTP_400_BAD_REQUEST)

    terminal = ['passed', 'failed', 'error']
    if record.status not in terminal:
        return Response({'error': '仅支持转换已完成的执行记录'}, status=status.HTTP_400_BAD_REQUEST)

    from .script_converter import convert_execution_to_script
    try:
        script_data = convert_execution_to_script(record)
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    # 同时保留 legacy replay_script 字段
    record.replay_script = script_data
    record.save(update_fields=['replay_script'])

    script_name = name or (record.testcase.name if record.testcase else f'脚本-{record.pk}')
    script_feature_group = feature_group or (record.testcase.feature_group if record.testcase else '')

    script = Script.objects.create(
        project=record.project,
        testcase=record.testcase,
        source_execution=record,
        name=script_name,
        feature_group=script_feature_group,
        script_data=script_data,
        status='active',
        version=1,
    )

    return Response(ScriptSerializer(script).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def script_execute(request, pk):
    """POST /api/scripts/<id>/execute/ — 执行脚本"""
    try:
        script = Script.objects.select_related('project', 'testcase', 'source_execution').get(pk=pk)
    except Script.DoesNotExist:
        return Response({'error': '脚本不存在'}, status=status.HTTP_404_NOT_FOUND)

    if not script.script_data:
        return Response({'error': '脚本内容为空'}, status=status.HTTP_400_BAD_REQUEST)

    param_serializer = ScriptExecuteRequestSerializer(data=request.data)
    param_serializer.is_valid(raise_exception=True)
    parameter_overrides = param_serializer.validated_data.get('parameter_overrides', {})

    # 查找关联的 source_execution 用于回放
    source_record = script.source_execution
    if not source_record:
        # 如果没有 source_execution，创建一个虚拟执行记录以支持回放
        source_record = ExecutionRecord.objects.create(
            project=script.project,
            testcase=script.testcase,
            status='completed',
            execution_mode='replay',
            replay_script=script.script_data,
        )
        script.source_execution = source_record
        script.save(update_fields=['source_execution'])

    # 创建新的执行记录
    new_record = ExecutionRecord.objects.create(
        project=script.project,
        testcase=script.testcase,
        status='running',
        execution_mode='replay',
        source_execution=source_record,
    )

    # 闭包捕获
    def _replay_task():
        from .script_executor import ReplayExecutor
        # 更新 source_record 的 replay_script（如果需要的话，保证一致性）
        if not source_record.replay_script:
            source_record.replay_script = script.script_data
            source_record.save(update_fields=['replay_script'])
        executor = ReplayExecutor(new_record, source_record)
        executor.run(script.script_data, parameter_overrides)

    _submit_agent_task(_replay_task)

    return Response(
        ExecutionRecordSerializer(new_record).data,
        status=status.HTTP_202_ACCEPTED,
    )


class BatchConvertRequestSerializer(drf_serializers.Serializer):
    """批量脚本转换请求"""
    project_id = drf_serializers.IntegerField(help_text='项目 ID')
    feature_group = drf_serializers.CharField(
        required=False, default='', allow_blank=True,
        help_text='功能点名称，空字符串表示未分组',
    )


@api_view(['POST'])
def batch_convert_scripts(request):
    """POST /api/scripts/batch-convert/ — 按功能点批量将 Agent 执行记录转为 Script"""
    serializer = BatchConvertRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    project_id = serializer.validated_data['project_id']
    feature_group = serializer.validated_data.get('feature_group', '')

    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    # 查找该功能点下所有 Agent 执行记录（已完成的终端状态）
    fg_filter = '' if feature_group == '未分组' else feature_group
    records = ExecutionRecord.objects.filter(
        project=project,
        execution_mode='agent',
        status__in=['passed', 'failed', 'error'],
        testcase__feature_group=fg_filter,
    ).select_related('project', 'testcase')

    if not records.exists():
        return Response({'error': '该功能点下没有可转换的 Agent 执行记录'}, status=status.HTTP_400_BAD_REQUEST)

    # 查找已存在的 Script（按 source_execution）去重
    existing_source_ids = set(
        Script.objects.filter(
            project=project,
            source_execution__in=records,
        ).values_list('source_execution_id', flat=True)
    )

    from .script_converter import convert_execution_to_script
    created_scripts = []
    skipped = 0

    for record in records:
        if record.pk in existing_source_ids:
            skipped += 1
            continue

        try:
            script_data = convert_execution_to_script(record)
        except ValueError:
            skipped += 1
            continue

        # 同时保留 legacy replay_script 字段
        record.replay_script = script_data
        record.save(update_fields=['replay_script'])

        script_name = record.testcase.name if record.testcase else f'脚本-{record.pk}'
        script_feature_group = record.testcase.feature_group if record.testcase else ''

        script = Script.objects.create(
            project=record.project,
            testcase=record.testcase,
            source_execution=record,
            name=script_name,
            feature_group=script_feature_group,
            script_data=script_data,
            status='active',
            version=1,
        )
        created_scripts.append(script)

    # Post-process: normalize parameter names across batch
    if created_scripts:
        from .script_converter import normalize_parameter_names
        normalize_parameter_names(created_scripts)

    return Response({
        'scripts': ScriptSerializer(created_scripts, many=True).data,
        'created': len(created_scripts),
        'skipped': skipped,
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def script_feature_groups(request):
    """GET /api/scripts/feature-groups/ — 获取脚本的功能分组列表"""
    project_id = request.query_params.get('project')
    if not project_id:
        return Response({'error': '缺少 project 参数'}, status=status.HTTP_400_BAD_REQUEST)

    groups = (
        Script.objects.filter(project_id=project_id)
        .values('feature_group')
        .annotate(count=Count('id'))
        .order_by('feature_group')
    )

    result = []
    for g in groups:
        name = g['feature_group'] or '未分组'
        result.append({
            'name': name,
            'count': g['count'],
        })

    return Response({'groups': result})


# ══════════════════════════════════════════════════════════════════
# Feature 分组执行 API
# ══════════════════════════════════════════════════════════════════

@api_view(['POST'])
def execute_feature_group(request, project_id, feature_group):
    """POST /api/projects/<id>/features/<feature_group>/execute/ — 顺序执行指定功能下的所有用例"""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

    if not project.base_url:
        return Response(
            {'error': '请先在项目中配置测试目标 URL'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # feature_group 从 URL path 获取（URL decoded by Django）
    # '未分组' 映射到空字符串
    fg_filter = '' if feature_group == '未分组' else feature_group

    testcases = list(project.testcases.filter(
        feature_group=fg_filter,
        status__in=['draft', 'ready']
    ).order_by('sort_order'))

    if not testcases:
        return Response(
            {'error': f'功能分组「{feature_group}」下没有可执行的测试用例'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 预创建所有 ExecutionRecord（HTTP 202 立即返回所有 ID）
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
        records.append(record)

    # 提交顺序执行任务到线程池
    _submit_agent_task(lambda tcs=testcases, recs=records: _execute_testcases_sequential_by_records(tcs, recs, project))

    return Response({
        'feature_group': feature_group,
        'execution_ids': [r.id for r in records],
        'submitted': len(records),
        'count': len(records),
        'records': ExecutionRecordSerializer(records, many=True).data,
    }, status=status.HTTP_202_ACCEPTED)


# ══════════════════════════════════════════════════════════════════
# TestPlan CRUD API
# ══════════════════════════════════════════════════════════════════

@api_view(['GET'])
def plan_list(request):
    """GET /api/plans/ — 方案列表（支持 project filter）"""
    qs = TestPlan.objects.select_related('project').prefetch_related('items').all()
    project_id = request.query_params.get('project')
    if project_id:
        qs = qs.filter(project_id=project_id)
    serializer = TestPlanSerializer(qs, many=True)
    return Response({'plans': serializer.data})


@api_view(['POST'])
def plan_create(request):
    """POST /api/plans/ — 创建方案"""
    serializer = TestPlanCreateUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    plan = serializer.save()
    return Response(TestPlanSerializer(plan).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def plan_detail(request, pk):
    """GET /api/plans/<id>/ — 方案详情（含 items）"""
    try:
        plan = TestPlan.objects.select_related('project').prefetch_related('items__script', 'items__testcase').get(pk=pk)
    except TestPlan.DoesNotExist:
        return Response({'error': '方案不存在'}, status=status.HTTP_404_NOT_FOUND)
    return Response(TestPlanSerializer(plan).data)


@api_view(['PUT'])
def plan_update(request, pk):
    """PUT /api/plans/<id>/ — 更新方案基本信息"""
    try:
        plan = TestPlan.objects.get(pk=pk)
    except TestPlan.DoesNotExist:
        return Response({'error': '方案不存在'}, status=status.HTTP_404_NOT_FOUND)

    serializer = TestPlanCreateUpdateSerializer(plan, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(TestPlanSerializer(plan).data)


@api_view(['DELETE'])
def plan_delete(request, pk):
    """DELETE /api/plans/<id>/ — 删除方案（含所有子项）"""
    try:
        plan = TestPlan.objects.get(pk=pk)
    except TestPlan.DoesNotExist:
        return Response({'error': '方案不存在'}, status=status.HTTP_404_NOT_FOUND)

    plan.delete()
    return Response({'deleted': True})


@api_view(['POST'])
def plan_add_item(request, pk):
    """POST /api/plans/<id>/items/ — 添加方案子项"""
    try:
        plan = TestPlan.objects.get(pk=pk)
    except TestPlan.DoesNotExist:
        return Response({'error': '方案不存在'}, status=status.HTTP_404_NOT_FOUND)

    serializer = TestPlanItemCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    item_type = serializer.validated_data['item_type']
    script_id = serializer.validated_data.get('script_id')
    testcase_id = serializer.validated_data.get('testcase_id')
    feature_group_name = serializer.validated_data.get('feature_group_name', '')

    # 验证
    if item_type == 'script' and not script_id:
        return Response({'error': 'script 类型必须指定 script_id'}, status=status.HTTP_400_BAD_REQUEST)
    if item_type == 'feature_group' and not feature_group_name:
        return Response({'error': 'feature_group 类型必须指定 feature_group_name'}, status=status.HTTP_400_BAD_REQUEST)
    if item_type == 'agent_testcase' and not testcase_id:
        return Response({'error': 'agent_testcase 类型必须指定 testcase_id'}, status=status.HTTP_400_BAD_REQUEST)

    script_obj = None
    if script_id:
        try:
            script_obj = Script.objects.get(pk=script_id)
        except Script.DoesNotExist:
            return Response({'error': '脚本不存在'}, status=status.HTTP_404_NOT_FOUND)

    testcase_obj = None
    if testcase_id:
        try:
            testcase_obj = TestCase.objects.get(pk=testcase_id)
        except TestCase.DoesNotExist:
            return Response({'error': '测试用例不存在'}, status=status.HTTP_404_NOT_FOUND)

    # 获取当前最大 sort_order
    max_order = plan.items.aggregate(max_order=Max('sort_order'))['max_order'] or 0

    item = TestPlanItem.objects.create(
        test_plan=plan,
        item_type=item_type,
        script=script_obj,
        testcase=testcase_obj,
        feature_group_name=feature_group_name,
        sort_order=max_order + 1,
    )

    return Response(TestPlanItemSerializer(item).data, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
def plan_reorder_items(request, pk):
    """PUT /api/plans/<id>/items/reorder/ — 重新排序方案子项"""
    try:
        plan = TestPlan.objects.get(pk=pk)
    except TestPlan.DoesNotExist:
        return Response({'error': '方案不存在'}, status=status.HTTP_404_NOT_FOUND)

    serializer = TestPlanItemsReorderSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    orders = serializer.validated_data['orders']
    if not orders:
        return Response({'error': '排序数据为空'}, status=status.HTTP_400_BAD_REQUEST)

    updated = 0
    with transaction.atomic():
        for item_data in orders:
            item_id = item_data.get('id')
            sort_order = item_data.get('sort_order', 0)
            try:
                item = plan.items.get(pk=item_id)
                item.sort_order = sort_order
                item.save(update_fields=['sort_order'])
                updated += 1
            except TestPlanItem.DoesNotExist:
                pass

    return Response({'updated': updated})


@api_view(['DELETE'])
def plan_delete_item(request, item_pk):
    """DELETE /api/plans/items/<id>/ — 删除方案子项"""
    try:
        item = TestPlanItem.objects.get(pk=item_pk)
    except TestPlanItem.DoesNotExist:
        return Response({'error': '子项不存在'}, status=status.HTTP_404_NOT_FOUND)

    item.delete()
    return Response({'deleted': True})


@api_view(['POST'])
def plan_regenerate_token(request, pk):
    """POST /api/plans/<id>/regenerate-token/ — 重新生成 API Token"""
    import uuid
    try:
        plan = TestPlan.objects.get(pk=pk)
    except TestPlan.DoesNotExist:
        return Response({'error': '方案不存在'}, status=status.HTTP_404_NOT_FOUND)

    plan.api_token = uuid.uuid4()
    plan.save(update_fields=['api_token'])
    return Response({
        'api_token': str(plan.api_token),
    })


# ══════════════════════════════════════════════════════════════════
# Plan Parameter Aggregation API
# ══════════════════════════════════════════════════════════════════

@api_view(['GET'])
def plan_parameters(request, pk):
    """GET /api/plans/<id>/parameters/ — 聚合方案下所有脚本的参数（去重）

    遍历方案所有 TestPlanItem，收集 script 类型的 script_data.parameters 和
    feature_group 类型展开后所有脚本的参数。按参数名去重，同名不同 default 值
    的标记 conflict 并保留 sources 信息。

    Returns:
        {
            parameters: {
                [name]: {label, type, default, group, sources: [{script_id, script_name, default}]}
            },
            all_script_params: {
                [script_id]: {[name]: value}   // 每个脚本的默认参数值映射
            }
        }
    """
    try:
        plan = TestPlan.objects.select_related('project').prefetch_related('items__script', 'items__testcase').get(pk=pk)
    except TestPlan.DoesNotExist:
        return Response({'error': '方案不存在'}, status=status.HTTP_404_NOT_FOUND)

    items = plan.items.all().order_by('sort_order')

    # Collect all scripts to run (same logic as plan_execute)
    scripts = []
    for item in items:
        if item.item_type == 'script' and item.script:
            if item.script.status == 'active':
                scripts.append(item.script)
        elif item.item_type == 'feature_group':
            group_scripts = Script.objects.filter(
                project=plan.project,
                feature_group=item.feature_group_name,
                status='active',
            ).order_by('sort_order')
            scripts.extend(group_scripts)

    # Aggregate parameters across all scripts
    aggregated = {}       # pname -> {label, type, default, group, sources: []}
    all_script_params = {}  # script_id -> {pname: default_value}

    for script in scripts:
        params = script.script_data.get('parameters', {})
        script_defaults = {}

        for pname, pinfo in params.items():
            default = pinfo.get('default', '')
            script_defaults[pname] = default

            source_entry = {
                'script_id': script.id,
                'script_name': script.name,
                'default': default,
            }

            if pname not in aggregated:
                # First occurrence — use this as the base
                aggregated[pname] = {
                    'label': pinfo.get('label', pname),
                    'type': pinfo.get('type', 'string'),
                    'default': default,
                    'group': pinfo.get('group', ''),
                    'conflict': False,
                    'sources': [source_entry],
                }
            else:
                # Already seen — check for conflict
                existing = aggregated[pname]
                existing['sources'].append(source_entry)
                if str(default) != str(existing['default']):
                    existing['conflict'] = True

        all_script_params[str(script.id)] = script_defaults

    return Response({
        'parameters': aggregated,
        'all_script_params': all_script_params,
    })


# ══════════════════════════════════════════════════════════════════
# PlanExecution API (含 CI/CD 支持)
# ══════════════════════════════════════════════════════════════════

def _authenticate_plan_request(request, plan):
    """验证方案执行请求的认证 — Django session 或 X-Plan-Token"""
    # Django session 认证（前端 UI）
    if request.user and request.user.is_authenticated:
        return True
    # API Token 认证（CI/CD）
    token = request.headers.get('X-Plan-Token', '')
    if token and str(plan.api_token) == token.strip():
        return True
    return False


@api_view(['POST'])
def plan_execute(request, pk):
    """POST /api/plans/<id>/execute/ — 触发方案执行（支持 parameter_overrides）"""
    try:
        plan = TestPlan.objects.select_related('project').prefetch_related('items__script', 'items__testcase').get(pk=pk)
    except TestPlan.DoesNotExist:
        return Response({'error': '方案不存在'}, status=status.HTTP_404_NOT_FOUND)

    if not _authenticate_plan_request(request, plan):
        return Response({'error': '认证失败'}, status=status.HTTP_403_FORBIDDEN)

    if not plan.project.base_url:
        return Response({'error': '请先在项目中配置测试目标 URL'}, status=status.HTTP_400_BAD_REQUEST)

    # Parse optional parameter_overrides from request body
    serializer = PlanExecuteRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    parameter_overrides = serializer.validated_data.get('parameter_overrides', {})

    items = plan.items.all().order_by('sort_order')
    if not items.exists():
        return Response({'error': '方案没有子项'}, status=status.HTTP_400_BAD_REQUEST)

    trigger_source = 'api' if request.headers.get('X-Plan-Token') else 'manual'

    # 创建 PlanExecution 记录
    from django.utils import timezone
    plan_exec = PlanExecution.objects.create(
        test_plan=plan,
        project=plan.project,
        status='running',
        trigger_source=trigger_source,
        summary={'total': 0, 'passed': 0, 'failed': 0, 'error': 0, 'skipped': 0},
        started_at=timezone.now(),
    )

    # 收集要执行的脚本和Agent用例（按 sort_order 顺序）
    scripts_to_run = []
    agent_testcases_to_run = []
    for item in items:
        if item.item_type == 'script' and item.script:
            if item.script.status == 'active':
                scripts_to_run.append(item.script)
        elif item.item_type == 'feature_group':
            # 查找该功能分组下所有活跃脚本
            group_scripts = Script.objects.filter(
                project=plan.project,
                feature_group=item.feature_group_name,
                status='active',
            ).order_by('sort_order')
            scripts_to_run.extend(group_scripts)
        elif item.item_type == 'agent_testcase' and item.testcase:
            agent_testcases_to_run.append(item.testcase)

    total_count = len(scripts_to_run) + len(agent_testcases_to_run)
    if not total_count:
        plan_exec.status = 'completed'
        plan_exec.completed_at = timezone.now()
        plan_exec.summary = {'total': 0, 'passed': 0, 'failed': 0, 'error': 0, 'skipped': 0}
        plan_exec.save()
        return Response(PlanExecutionSerializer(plan_exec).data)

    plan_exec.summary = {
        'total': total_count,
        'passed': 0, 'failed': 0, 'error': 0, 'skipped': 0,
    }
    plan_exec.save(update_fields=['summary'])

    # 同步模式：阻塞等待完成
    sync_mode = request.query_params.get('sync', '').lower() in ('true', '1', 'yes')

    if sync_mode:
        return _execute_plan_sync(plan_exec, scripts_to_run, agent_testcases_to_run, plan, parameter_overrides)
    else:
        _submit_agent_task(lambda: _execute_plan_async(plan_exec, scripts_to_run, agent_testcases_to_run, plan, parameter_overrides))
        return Response(PlanExecutionSerializer(plan_exec).data, status=status.HTTP_202_ACCEPTED)


def _run_single_script(plan_exec, script, plan, parameter_overrides=None):
    """执行单个脚本并返回结果状态。

    Args:
        parameter_overrides: plan-level 参数覆盖 dict，直接按参数名传递到脚本执行。
    """
    source_record = script.source_execution
    if not source_record or not script.script_data:
        return 'skipped'

    # Map plan-level overrides to script-level: filter to only params this script uses
    script_overrides = {}
    if parameter_overrides:
        script_params = script.script_data.get('parameters', {})
        for pname in script_params:
            if pname in parameter_overrides:
                script_overrides[pname] = parameter_overrides[pname]

    new_record = ExecutionRecord.objects.create(
        project=plan.project,
        testcase=script.testcase,
        status='running',
        execution_mode='replay',
        source_execution=source_record,
        plan_execution=plan_exec,
    )

    if not source_record.replay_script:
        source_record.replay_script = script.script_data
        source_record.save(update_fields=['replay_script'])

    from .script_executor import ReplayExecutor
    executor = ReplayExecutor(new_record, source_record)
    executor.run(script.script_data, script_overrides)

    new_record.refresh_from_db()
    return new_record.status


def _run_single_agent_testcase(plan_exec, testcase, plan):
    """通过 Agent 模式执行单个测试用例并返回结果状态"""
    new_record = ExecutionRecord.objects.create(
        project=plan.project,
        testcase=testcase,
        status='running',
        execution_mode='agent',
        ai_model=_get_ai_model(),
        plan_execution=plan_exec,
    )
    testcase.status = 'running'
    testcase.save(update_fields=['status'])

    try:
        result = execution_engine.execute_testcase_with_agent(
            testcase, plan.project.base_url, execution_id=new_record.pk,
        )
        _save_agent_result(new_record, result)
        testcase.status = result['status']
        testcase.save(update_fields=['status'])
        return result['status']
    except Exception:
        logger.exception("[PlanExecute] Agent testcase %s failed", testcase.name)
        new_record.status = 'error'
        new_record.error_message = 'Agent execution failed'
        new_record.save(update_fields=['status', 'error_message'])
        testcase.status = 'error'
        testcase.save(update_fields=['status'])
        return 'error'


def _finalize_plan_execution(plan_exec):
    """汇总所有子执行的状态并更新 PlanExecution"""
    from django.utils import timezone
    records = plan_exec.execution_records.all()
    summary = {'total': records.count(), 'passed': 0, 'failed': 0, 'error': 0, 'skipped': 0}
    for r in records:
        if r.status in summary:
            summary[r.status] += 1
        else:
            summary['error'] += 1

    overall_status = 'completed'
    if summary['failed'] > 0 or summary['error'] > 0:
        overall_status = 'failed' if summary['error'] == 0 else 'error'

    plan_exec.status = overall_status
    plan_exec.summary = summary
    plan_exec.completed_at = timezone.now()
    plan_exec.save()


def _execute_plan_sync(plan_exec, scripts_to_run, agent_testcases_to_run, plan, parameter_overrides=None):
    """同步执行方案（阻塞等待）"""
    try:
        for script in scripts_to_run:
            _run_single_script(plan_exec, script, plan, parameter_overrides)
        for testcase in agent_testcases_to_run:
            _run_single_agent_testcase(plan_exec, testcase, plan)
        _finalize_plan_execution(plan_exec)
    except Exception as e:
        logger.exception("[PlanExecute] Sync execution failed")
        plan_exec.status = 'error'
        plan_exec.save(update_fields=['status'])

    # 同步模式在视图函数内直接返回
    return Response(PlanExecutionDetailSerializer(plan_exec).data)


def _execute_plan_async(plan_exec, scripts_to_run, agent_testcases_to_run, plan, parameter_overrides=None):
    """异步执行方案（线程池内运行）"""
    try:
        for script in scripts_to_run:
            _run_single_script(plan_exec, script, plan, parameter_overrides)
        for testcase in agent_testcases_to_run:
            _run_single_agent_testcase(plan_exec, testcase, plan)
        _finalize_plan_execution(plan_exec)
    except Exception as e:
        logger.exception("[PlanExecute] Async execution failed")
        from django.utils import timezone
        plan_exec.status = 'error'
        plan_exec.completed_at = timezone.now()
        plan_exec.save()


@api_view(['GET'])
def plan_execution_list(request):
    """GET /api/plan-executions/ — 方案执行历史列表"""
    qs = PlanExecution.objects.select_related('test_plan', 'project').all()
    plan_id = request.query_params.get('plan')
    if plan_id:
        qs = qs.filter(test_plan_id=plan_id)
    project_id = request.query_params.get('project')
    if project_id:
        qs = qs.filter(project_id=project_id)
    serializer = PlanExecutionSerializer(qs, many=True)
    return Response({'executions': serializer.data})


@api_view(['GET'])
def plan_execution_detail(request, pk):
    """GET /api/plan-executions/<id>/ — 方案执行详情（含子 ExecutionRecord）"""
    try:
        plan_exec = PlanExecution.objects.select_related(
            'test_plan', 'project'
        ).prefetch_related('execution_records__testcase').get(pk=pk)
    except PlanExecution.DoesNotExist:
        return Response({'error': '方案执行记录不存在'}, status=status.HTTP_404_NOT_FOUND)
    return Response(PlanExecutionDetailSerializer(plan_exec).data)


@api_view(['GET'])
def plan_execution_status(request, pk):
    """GET /api/plan-executions/<id>/status/ — 轻量状态查询（CI/CD polling）"""
    try:
        plan_exec = PlanExecution.objects.only('id', 'status', 'summary', 'started_at', 'completed_at').get(pk=pk)
    except PlanExecution.DoesNotExist:
        return Response({'error': '方案执行记录不存在'}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        'id': plan_exec.id,
        'status': plan_exec.status,
        'summary': plan_exec.summary,
        'started_at': plan_exec.started_at,
        'completed_at': plan_exec.completed_at,
    })


@api_view(['GET'])
def plan_execution_report(request, pk):
    """GET /api/plan-executions/<id>/report/ — JUnit XML 格式测试报告（CI/CD 集成）"""
    try:
        plan_exec = PlanExecution.objects.select_related('test_plan').prefetch_related(
            'execution_records__testcase'
        ).get(pk=pk)
    except PlanExecution.DoesNotExist:
        return Response({'error': '方案执行记录不存在'}, status=status.HTTP_404_NOT_FOUND)

    records = plan_exec.execution_records.select_related('testcase').all()
    summary = plan_exec.summary or {}

    total = summary.get('total', records.count())
    passed = summary.get('passed', 0)
    failed_count = summary.get('failed', 0)
    error_count = summary.get('error', 0)
    skipped = summary.get('skipped', 0)
    failures = failed_count + error_count

    # 计算 duration
    duration = 0.0
    for r in records:
        if r.duration:
            duration += r.duration

    plan_name = plan_exec.test_plan.name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    xml_parts = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuites tests="{total}" failures="{failures}" errors="{error_count}" time="{duration:.3f}">',
        f'<testsuite name="{plan_name}" tests="{total}" failures="{failures}" errors="{error_count}" skipped="{skipped}" time="{duration:.3f}">',
    ]

    for r in records:
        tc_name = (r.testcase.name if r.testcase else f'Execution-{r.id}')
        tc_name = tc_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        r_duration = r.duration or 0

        if r.status in ('passed',):
            xml_parts.append(f'<testcase classname="{plan_name}" name="{tc_name}" time="{r_duration:.3f}" />')
        elif r.status in ('failed',):
            error_msg = (r.error_message or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            xml_parts.append(f'<testcase classname="{plan_name}" name="{tc_name}" time="{r_duration:.3f}">')
            xml_parts.append(f'<failure message="{error_msg[:200]}">{error_msg}</failure>')
            xml_parts.append(f'</testcase>')
        elif r.status in ('error',):
            error_msg = (r.error_message or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            xml_parts.append(f'<testcase classname="{plan_name}" name="{tc_name}" time="{r_duration:.3f}">')
            xml_parts.append(f'<error message="{error_msg[:200]}">{error_msg}</error>')
            xml_parts.append(f'</testcase>')
        else:
            xml_parts.append(f'<testcase classname="{plan_name}" name="{tc_name}" time="{r_duration:.3f}">')
            xml_parts.append(f'<skipped />')
            xml_parts.append(f'</testcase>')

    xml_parts.append('</testsuite>')
    xml_parts.append('</testsuites>')

    xml_content = '\n'.join(xml_parts)
    return Response(xml_content, content_type='application/xml')
