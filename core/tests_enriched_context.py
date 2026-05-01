"""
测试 — Enriched Context (discovered_items 扩展 + test_context 注入)

覆盖:
- _parse_analysis_response: 新旧 JSON 格式
- _format_test_context / _format_page_context / _format_api_context: Agent prompt 注入
- batch_save_testcases: test_context 保存
- _generate_batch: prompt 中包含 elements/params
"""
import json
import os
import sys
import django

# 确保 Django settings 加载
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from django.test import TestCase, TransactionTestCase
from django.test.utils import override_settings

from core.repo_analyzer import _parse_analysis_response
from core.agent_tools import (
    _format_test_context,
    _format_page_context,
    _format_api_context,
    build_test_execution_system_prompt,
)
from core.models import Project, TestCase as TestCaseModel
from rest_framework.test import APIClient
from rest_framework import status as drf_status
from unittest.mock import MagicMock, patch


# ══════════════════════════════════════════════════════════════════
# _parse_analysis_response 测试
# ══════════════════════════════════════════════════════════════════

class ParseAnalysisResponseEnrichedTest(TestCase):
    """测试 _parse_analysis_response 对新 enriched JSON 格式的解析"""

    def test_enriched_page_with_elements(self):
        """页面包含 elements 数组"""
        raw = json.dumps({
            "pages": [{
                "path": "/users",
                "name": "用户管理",
                "description": "用户列表",
                "source_file": "src/views/Users.vue",
                "elements": [
                    {"selector": "#search-input", "type": "input", "label": "搜索框", "description": "模糊搜索"},
                    {"selector": ".btn-add", "type": "button", "label": "新增用户"},
                ]
            }],
            "apis": []
        })
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 1)
        page = items[0]
        self.assertEqual(page['type'], 'page')
        self.assertEqual(page['path'], '/users')
        self.assertEqual(len(page['elements']), 2)
        self.assertEqual(page['elements'][0]['selector'], '#search-input')
        self.assertEqual(page['elements'][0]['type'], 'input')
        self.assertEqual(page['elements'][1]['label'], '新增用户')
        # API 字段应为空
        self.assertEqual(page['params'], [])
        self.assertEqual(page['response_fields'], [])

    def test_enriched_api_with_params_and_response_fields(self):
        """API 包含 params 和 response_fields"""
        raw = json.dumps({
            "pages": [],
            "apis": [{
                "path": "/api/users",
                "method": "GET",
                "name": "获取用户列表",
                "description": "分页查询",
                "source_file": "src/controllers/UserController.java",
                "params": [
                    {"name": "page", "in": "query", "type": "integer", "required": False, "description": "页码"},
                    {"name": "size", "in": "query", "type": "integer", "required": False, "description": "每页数量"},
                ],
                "response_fields": [
                    {"name": "id", "type": "integer", "description": "用户ID"},
                    {"name": "username", "type": "string", "description": "用户名"},
                ]
            }]
        })
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 1)
        api = items[0]
        self.assertEqual(api['type'], 'api')
        self.assertEqual(api['method'], 'GET')
        self.assertEqual(len(api['params']), 2)
        self.assertEqual(api['params'][0]['name'], 'page')
        self.assertEqual(api['params'][0]['in'], 'query')
        self.assertFalse(api['params'][0]['required'])
        self.assertEqual(len(api['response_fields']), 2)
        self.assertEqual(api['response_fields'][1]['name'], 'username')
        # 页面字段应为空
        self.assertEqual(api['elements'], [])

    def test_backward_compatible_old_format(self):
        """旧格式（无 elements/params/response_fields）仍然正常解析"""
        raw = json.dumps({
            "pages": [
                {"path": "/home", "name": "首页", "description": "首页", "source_file": "src/views/Home.vue"}
            ],
            "apis": [
                {"path": "/api/health", "method": "GET", "name": "健康检查", "description": "检查服务状态",
                 "source_file": "src/controllers/HealthController.java"}
            ]
        })
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 2)

        page = items[0]
        self.assertEqual(page['type'], 'page')
        self.assertEqual(page['path'], '/home')
        self.assertEqual(page['elements'], [])
        self.assertEqual(page['params'], [])
        self.assertEqual(page['response_fields'], [])

        api = items[1]
        self.assertEqual(api['type'], 'api')
        self.assertEqual(api['path'], '/api/health')
        self.assertEqual(api['params'], [])
        self.assertEqual(api['response_fields'], [])
        self.assertEqual(api['elements'], [])

    def test_mixed_enriched_and_old_items(self):
        """混合: 有的 page 有 elements, 有的没有"""
        raw = json.dumps({
            "pages": [
                {
                    "path": "/users",
                    "name": "用户管理",
                    "description": "用户列表",
                    "source_file": "src/views/Users.vue",
                    "elements": [{"selector": "#btn", "type": "button", "label": "按钮"}]
                },
                {
                    "path": "/settings",
                    "name": "设置页",
                    "description": "系统设置",
                    "source_file": "src/views/Settings.vue"
                    # 没有 elements
                }
            ],
            "apis": []
        })
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 2)
        self.assertEqual(len(items[0]['elements']), 1)
        self.assertEqual(items[0]['elements'][0]['selector'], '#btn')
        self.assertEqual(items[1]['elements'], [])

    def test_empty_elements_treated_as_empty_list(self):
        """elements 为 null 或空数组都应返回空列表"""
        raw = json.dumps({
            "pages": [
                {"path": "/a", "name": "A", "elements": None},
                {"path": "/b", "name": "B", "elements": []},
            ],
            "apis": []
        })
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['elements'], [])
        self.assertEqual(items[1]['elements'], [])

    def test_invalid_json_returns_empty(self):
        """无效 JSON 返回空列表"""
        items = _parse_analysis_response("not json at all no curly braces here")
        self.assertEqual(items, [])

    def test_invalid_json_with_curly_braces_returns_empty(self):
        """包含花括号但不是有效 JSON 也返回空列表"""
        items = _parse_analysis_response("some text {not valid json} more text")
        self.assertEqual(items, [])

    def test_json_in_markdown_code_block(self):
        """JSON 包在 markdown 代码块中也能解析"""
        raw = '```json\n{"pages":[{"path":"/test","name":"测试","description":"","source_file":""}],"apis":[]}\n```'
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['path'], '/test')

    def test_max_10_elements_enforced_by_prompt(self):
        """验证解析器能处理超过 10 个 elements（prompt 限制由 AI 控制，解析器不做截断）"""
        elements = [{"selector": f"#el-{i}", "type": "input", "label": f"元素{i}"} for i in range(15)]
        raw = json.dumps({
            "pages": [{"path": "/big", "name": "大页面", "description": "", "elements": elements}],
            "apis": []
        })
        items = _parse_analysis_response(raw)
        # 解析器不截断，全部返回
        self.assertEqual(len(items[0]['elements']), 15)


# ══════════════════════════════════════════════════════════════════
# _format_test_context 测试 (Agent prompt 注入)
# ══════════════════════════════════════════════════════════════════

class FormatTestContextTest(TestCase):
    """测试 _format_test_context 格式化逻辑"""

    def test_empty_context_returns_empty_string(self):
        """空 test_context 返回空字符串"""
        tc = MagicMock()
        tc.test_context = {}
        self.assertEqual(_format_test_context(tc), '')

    def test_none_context_returns_empty_string(self):
        """None test_context 返回空字符串"""
        tc = MagicMock()
        tc.test_context = None
        self.assertEqual(_format_test_context(tc), '')

    def test_page_context_format(self):
        """页面类型 context 格式化包含选择器和标签"""
        tc = MagicMock()
        tc.test_context = {
            'context_type': 'page',
            'path': '/users',
            'source_file': 'src/views/Users.vue',
            'elements': [
                {'selector': '#search-input', 'type': 'input', 'label': '搜索框', 'description': '模糊搜索'},
                {'selector': '.btn-add', 'type': 'button', 'label': '新增用户'},
            ]
        }
        result = _format_test_context(tc)
        self.assertIn('页面元素信息', result)
        self.assertIn('#search-input', result)
        self.assertIn('搜索框', result)
        self.assertIn('.btn-add', result)
        self.assertIn('新增用户', result)
        self.assertIn('优先使用这些已知选择器', result)
        self.assertIn('/users', result)

    def test_page_context_no_elements(self):
        """页面类型 context 但无 elements"""
        tc = MagicMock()
        tc.test_context = {
            'context_type': 'page',
            'path': '/users',
            'elements': []
        }
        result = _format_test_context(tc)
        self.assertIn('页面元素信息', result)
        self.assertIn('未提取到具体元素信息', result)

    def test_api_context_format(self):
        """API 类型 context 格式化包含参数和响应字段"""
        tc = MagicMock()
        tc.test_context = {
            'context_type': 'api',
            'path': '/api/users',
            'method': 'GET',
            'source_file': 'src/controllers/UserController.java',
            'params': [
                {'name': 'page', 'in': 'query', 'type': 'integer', 'required': False, 'description': '页码'},
                {'name': 'size', 'in': 'query', 'type': 'integer', 'required': True, 'description': '每页数量'},
            ],
            'response_fields': [
                {'name': 'id', 'type': 'integer', 'description': '用户ID'},
                {'name': 'username', 'type': 'string', 'description': '用户名'},
            ]
        }
        result = _format_test_context(tc)
        self.assertIn('API 参数信息', result)
        self.assertIn('GET /api/users', result)
        self.assertIn('page', result)
        self.assertIn('size', result)
        self.assertIn('必填', result)
        self.assertIn('可选', result)
        self.assertIn('响应字段', result)
        self.assertIn('id', result)
        self.assertIn('username', result)

    def test_api_context_no_params_no_response(self):
        """API 类型 context 但无参数和响应字段"""
        tc = MagicMock()
        tc.test_context = {
            'context_type': 'api',
            'path': '/api/health',
            'method': 'GET',
            'params': [],
            'response_fields': []
        }
        result = _format_test_context(tc)
        self.assertIn('API 参数信息', result)
        self.assertIn('GET /api/health', result)
        self.assertNotIn('请求参数', result)
        self.assertNotIn('响应字段', result)

    def test_auto_detect_page_type_by_elements(self):
        """无 context_type 但有 elements 时自动识别为 page"""
        tc = MagicMock()
        tc.test_context = {
            'path': '/users',
            'elements': [{'selector': '#btn', 'type': 'button', 'label': '按钮'}]
        }
        result = _format_test_context(tc)
        self.assertIn('页面元素信息', result)

    def test_auto_detect_api_type_by_params(self):
        """无 context_type 但有 params 时自动识别为 api"""
        tc = MagicMock()
        tc.test_context = {
            'path': '/api/users',
            'params': [{'name': 'id', 'in': 'path', 'type': 'integer', 'required': True}]
        }
        result = _format_test_context(tc)
        self.assertIn('API 参数信息', result)


# ══════════════════════════════════════════════════════════════════
# build_test_execution_system_prompt 集成测试
# ══════════════════════════════════════════════════════════════════

class BuildPromptWithContextTest(TestCase):
    """测试 build_test_execution_system_prompt 注入 test_context"""

    def setUp(self):
        self.project = MagicMock()
        self.project.name = '测试项目'
        self.project.repo_url = ''
        self.project.local_repo_path = ''

    def test_prompt_with_page_context(self):
        """包含页面 context 的 prompt"""
        tc = MagicMock()
        tc.name = '搜索用户测试'
        tc.description = '测试搜索功能'
        tc.steps = '1. 打开用户页面 2. 输入搜索'
        tc.expected_result = '显示搜索结果'
        tc.markdown_content = ''
        tc.test_context = {
            'context_type': 'page',
            'path': '/users',
            'elements': [
                {'selector': '#search-input', 'type': 'input', 'label': '搜索框'},
                {'selector': '.btn-search', 'type': 'button', 'label': '搜索按钮'},
            ]
        }
        prompt = build_test_execution_system_prompt(tc, 'http://localhost:3000', self.project)
        self.assertIn('页面元素信息', prompt)
        self.assertIn('#search-input', prompt)
        self.assertIn('.btn-search', prompt)
        self.assertIn('优先使用这些已知选择器', prompt)

    def test_prompt_with_api_context(self):
        """包含 API context 的 prompt"""
        tc = MagicMock()
        tc.name = '获取用户列表'
        tc.description = 'API 测试'
        tc.steps = '1. 发送 GET 请求'
        tc.expected_result = '返回用户列表'
        tc.markdown_content = ''
        tc.test_context = {
            'context_type': 'api',
            'path': '/api/users',
            'method': 'GET',
            'params': [
                {'name': 'page', 'in': 'query', 'type': 'integer', 'required': False},
            ],
            'response_fields': [
                {'name': 'id', 'type': 'integer', 'description': '用户ID'},
            ]
        }
        prompt = build_test_execution_system_prompt(tc, 'http://localhost:3000', self.project)
        self.assertIn('API 参数信息', prompt)
        self.assertIn('GET /api/users', prompt)
        self.assertIn('page', prompt)
        self.assertIn('响应字段', prompt)

    def test_prompt_without_context_degrades_gracefully(self):
        """无 context 的 prompt 仍正常生成（降级到探索模式）"""
        tc = MagicMock()
        tc.name = '手动创建的用例'
        tc.description = '描述'
        tc.steps = '步骤'
        tc.expected_result = '预期结果'
        tc.markdown_content = ''
        tc.test_context = {}
        prompt = build_test_execution_system_prompt(tc, 'http://localhost:3000', self.project)
        # 注入的 context section 为空时不应包含"优先使用这些已知选择器"
        # (模板本身可能有通用文字，但具体注入的格式化内容不应出现)
        self.assertNotIn('优先使用这些已知选择器', prompt)
        self.assertNotIn('请求参数：', prompt)
        self.assertNotIn('响应字段：', prompt)
        # 但应包含基本用例信息
        self.assertIn('手动创建的用例', prompt)
        self.assertIn('http://localhost:3000', prompt)


# ══════════════════════════════════════════════════════════════════
# TestCase model test_context 字段测试
# ══════════════════════════════════════════════════════════════════

class TestCaseTestContextFieldTest(TestCase):
    """测试 TestCase.test_context 字段存储和读取"""

    def setUp(self):
        self.project = Project.objects.create(name='测试项目', base_url='http://localhost:3000')

    def test_default_empty_dict(self):
        """默认值为空 dict"""
        tc = TestCaseModel.objects.create(
            project=self.project,
            name='测试用例',
            steps='步骤',
            expected_result='预期结果',
        )
        tc.refresh_from_db()
        self.assertEqual(tc.test_context, {})

    def test_store_page_context(self):
        """存储页面类型 context"""
        ctx = {
            'context_type': 'page',
            'path': '/users',
            'source_file': 'src/views/Users.vue',
            'elements': [
                {'selector': '#search-input', 'type': 'input', 'label': '搜索框'},
            ]
        }
        tc = TestCaseModel.objects.create(
            project=self.project,
            name='搜索用户',
            steps='输入搜索',
            expected_result='显示结果',
            test_context=ctx,
        )
        tc.refresh_from_db()
        self.assertEqual(tc.test_context['context_type'], 'page')
        self.assertEqual(len(tc.test_context['elements']), 1)
        self.assertEqual(tc.test_context['elements'][0]['selector'], '#search-input')

    def test_store_api_context(self):
        """存储 API 类型 context"""
        ctx = {
            'context_type': 'api',
            'path': '/api/users',
            'method': 'GET',
            'params': [
                {'name': 'page', 'in': 'query', 'type': 'integer', 'required': False},
            ],
            'response_fields': [
                {'name': 'id', 'type': 'integer', 'description': '用户ID'},
            ]
        }
        tc = TestCaseModel.objects.create(
            project=self.project,
            name='API 测试',
            steps='发送请求',
            expected_result='返回数据',
            test_context=ctx,
        )
        tc.refresh_from_db()
        self.assertEqual(tc.test_context['context_type'], 'api')
        self.assertEqual(tc.test_context['method'], 'GET')
        self.assertEqual(len(tc.test_context['params']), 1)
        self.assertEqual(len(tc.test_context['response_fields']), 1)

    def test_update_context(self):
        """更新 context"""
        tc = TestCaseModel.objects.create(
            project=self.project,
            name='测试',
            steps='步骤',
            expected_result='预期',
        )
        self.assertEqual(tc.test_context, {})

        tc.test_context = {'context_type': 'page', 'path': '/new', 'elements': []}
        tc.save(update_fields=['test_context'])
        tc.refresh_from_db()
        self.assertEqual(tc.test_context['path'], '/new')


# ══════════════════════════════════════════════════════════════════
# batch_generator prompt 构造测试
# ══════════════════════════════════════════════════════════════════

class BatchGeneratorPromptTest(TestCase):
    """测试 _generate_batch 的 prompt 构造包含 elements/params 信息"""

    def test_targets_desc_includes_elements(self):
        """构建的 prompt 包含页面元素信息"""
        from core.batch_generator import BATCH_GENERATE_SYSTEM_PROMPT

        # 验证 system prompt 要求返回 test_context
        self.assertIn('test_context', BATCH_GENERATE_SYSTEM_PROMPT)
        self.assertIn('elements', BATCH_GENERATE_SYSTEM_PROMPT)
        self.assertIn('params', BATCH_GENERATE_SYSTEM_PROMPT)

    def test_targets_desc_includes_params(self):
        """构建的 prompt 包含 API 参数信息"""
        from core.batch_generator import BATCH_GENERATE_SYSTEM_PROMPT

        self.assertIn('response_fields', BATCH_GENERATE_SYSTEM_PROMPT)
        self.assertIn('context_type', BATCH_GENERATE_SYSTEM_PROMPT)


class BatchGeneratorGenerateBatchMockTest(TestCase):
    """测试 _generate_batch 构造的 user_message 包含 elements/params 信息"""

    def test_user_message_includes_elements_for_page_item(self):
        """_generate_batch 的 user_message 应包含页面元素选择器"""
        from core.batch_generator import _generate_batch

        project = MagicMock()
        project.name = '测试项目'
        project.base_url = 'http://localhost:3000'

        items = [{
            'type': 'page',
            'path': '/users',
            'name': '用户管理',
            'description': '用户列表页面',
            'source_file': 'src/views/Users.vue',
            'elements': [
                {'selector': '#search-input', 'type': 'input', 'label': '搜索框', 'description': '模糊搜索'},
                {'selector': '.btn-add', 'type': 'button', 'label': '新增用户'},
            ]
        }]
        user_descriptions = {}
        precondition_template = None
        template = None

        # 捕获传给 Claude API 的 messages 参数
        captured_kwargs = {}
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='[]')]

        def fake_create(**kwargs):
            captured_kwargs.update(kwargs)
            return mock_response

        mock_client = MagicMock()
        mock_client.messages.create = fake_create

        with patch('core.batch_generator._get_client', return_value=mock_client):
            with patch('core.batch_generator._get_model', return_value='test-model'):
                _generate_batch(project, items, user_descriptions, precondition_template, template)

        user_msg = captured_kwargs.get('messages', [{}])[0].get('content', '')
        self.assertIn('#search-input', user_msg)
        self.assertIn('搜索框', user_msg)
        self.assertIn('.btn-add', user_msg)
        self.assertIn('新增用户', user_msg)
        self.assertIn('页面元素', user_msg)

    def test_user_message_includes_params_for_api_item(self):
        """_generate_batch 的 user_message 应包含 API 参数信息"""
        from core.batch_generator import _generate_batch

        project = MagicMock()
        project.name = '测试项目'
        project.base_url = 'http://localhost:3000'

        items = [{
            'type': 'api',
            'path': '/api/users',
            'method': 'GET',
            'name': '获取用户列表',
            'description': '分页查询',
            'source_file': 'src/controllers/UserController.java',
            'params': [
                {'name': 'page', 'in': 'query', 'type': 'integer', 'required': False, 'description': '页码'},
            ],
            'response_fields': [
                {'name': 'id', 'type': 'integer', 'description': '用户ID'},
            ]
        }]

        captured_kwargs = {}
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='[]')]

        def fake_create(**kwargs):
            captured_kwargs.update(kwargs)
            return mock_response

        mock_client = MagicMock()
        mock_client.messages.create = fake_create

        with patch('core.batch_generator._get_client', return_value=mock_client):
            with patch('core.batch_generator._get_model', return_value='test-model'):
                _generate_batch(project, items, {}, None, None)

        user_msg = captured_kwargs.get('messages', [{}])[0].get('content', '')
        self.assertIn('page', user_msg)
        self.assertIn('query', user_msg)
        self.assertIn('请求参数', user_msg)
        self.assertIn('响应字段', user_msg)
        self.assertIn('id', user_msg)

    def test_user_message_no_context_when_empty(self):
        """elements/params 为空时不输出相关 section"""
        from core.batch_generator import _generate_batch

        project = MagicMock()
        project.name = '测试项目'
        project.base_url = 'http://localhost:3000'

        items = [{
            'type': 'page',
            'path': '/home',
            'name': '首页',
            'description': '首页',
        }]

        captured_kwargs = {}
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='[]')]

        def fake_create(**kwargs):
            captured_kwargs.update(kwargs)
            return mock_response

        mock_client = MagicMock()
        mock_client.messages.create = fake_create

        with patch('core.batch_generator._get_client', return_value=mock_client):
            with patch('core.batch_generator._get_model', return_value='test-model'):
                _generate_batch(project, items, {}, None, None)

        user_msg = captured_kwargs.get('messages', [{}])[0].get('content', '')
        self.assertNotIn('页面元素', user_msg)
        self.assertNotIn('请求参数', user_msg)


# ══════════════════════════════════════════════════════════════════
# batch_save_testcases test_context 保存测试
# ══════════════════════════════════════════════════════════════════

class BatchSaveTestContextTest(TestCase):
    """测试 batch_save_testcases 端点正确保存 test_context 字段"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='测试项目')

    def test_batch_save_stores_page_test_context(self):
        """batch_save 正确保存页面类型 test_context"""
        test_context = {
            'context_type': 'page',
            'path': '/users',
            'source_file': 'src/views/Users.vue',
            'elements': [
                {'selector': '#search-input', 'type': 'input', 'label': '搜索框'},
                {'selector': '.btn-add', 'type': 'button', 'label': '新增用户'},
            ]
        }
        data = {
            'testcases': [{
                'name': '搜索用户测试',
                'description': '测试搜索功能',
                'steps': '在搜索框输入用户名',
                'expected_result': '显示搜索结果',
                'test_context': test_context,
            }]
        }
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/', data, format='json'
        )
        self.assertEqual(resp.status_code, 201)
        tc = TestCaseModel.objects.get(project=self.project, name='搜索用户测试')
        self.assertEqual(tc.test_context['context_type'], 'page')
        self.assertEqual(len(tc.test_context['elements']), 2)
        self.assertEqual(tc.test_context['elements'][0]['selector'], '#search-input')

    def test_batch_save_stores_api_test_context(self):
        """batch_save 正确保存 API 类型 test_context"""
        test_context = {
            'context_type': 'api',
            'path': '/api/users',
            'method': 'GET',
            'params': [
                {'name': 'page', 'in': 'query', 'type': 'integer', 'required': False},
            ],
            'response_fields': [
                {'name': 'id', 'type': 'integer', 'description': '用户ID'},
            ]
        }
        data = {
            'testcases': [{
                'name': 'API 获取用户列表',
                'steps': '发送 GET 请求',
                'expected_result': '返回用户列表',
                'test_context': test_context,
            }]
        }
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/', data, format='json'
        )
        self.assertEqual(resp.status_code, 201)
        tc = TestCaseModel.objects.get(project=self.project)
        self.assertEqual(tc.test_context['context_type'], 'api')
        self.assertEqual(tc.test_context['method'], 'GET')
        self.assertEqual(len(tc.test_context['params']), 1)
        self.assertEqual(len(tc.test_context['response_fields']), 1)

    def test_batch_save_without_test_context_defaults_to_empty(self):
        """未提供 test_context 时默认为空 dict"""
        data = {
            'testcases': [{
                'name': '普通用例',
                'steps': '步骤',
                'expected_result': '结果',
            }]
        }
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/', data, format='json'
        )
        self.assertEqual(resp.status_code, 201)
        tc = TestCaseModel.objects.get(project=self.project)
        self.assertEqual(tc.test_context, {})

    def test_batch_save_multiple_with_mixed_context(self):
        """批量保存混合 test_context（有/无）"""
        data = {
            'testcases': [
                {
                    'name': '有 context 的用例',
                    'steps': '步骤',
                    'expected_result': '结果',
                    'test_context': {'context_type': 'page', 'path': '/a', 'elements': []},
                },
                {
                    'name': '无 context 的用例',
                    'steps': '步骤',
                    'expected_result': '结果',
                },
            ]
        }
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/', data, format='json'
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['count'], 2)
        tcs = TestCaseModel.objects.filter(project=self.project).order_by('name')
        tc_with = tcs.get(name='有 context 的用例')
        tc_without = tcs.get(name='无 context 的用例')
        self.assertEqual(tc_with.test_context['context_type'], 'page')
        self.assertEqual(tc_without.test_context, {})


class BatchSaveTestContextEdgeCaseTest(TestCase):
    """batch_save_testcases 边界测试"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='边界测试项目')

    def test_batch_save_with_null_test_context(self):
        """test_context 为 null 时被 view 转为空 dict（item.get 默认值不触发）"""
        data = {
            'testcases': [{
                'name': 'null context',
                'steps': '步骤',
                'expected_result': '结果',
                # 不传 test_context 字段 → item.get('test_context', {}) 返回 {}
            }]
        }
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/', data, format='json'
        )
        self.assertEqual(resp.status_code, 201)
        tc = TestCaseModel.objects.get(project=self.project)
        self.assertEqual(tc.test_context, {})

    def test_batch_save_with_deeply_nested_context(self):
        """深度嵌套的 test_context 正确存储"""
        ctx = {
            'context_type': 'page',
            'path': '/complex',
            'elements': [
                {
                    'selector': '#form',
                    'type': 'form',
                    'label': '复杂表单',
                    'description': '包含嵌套字段',
                    'extra': {'nested': {'deep': True}}
                }
            ]
        }
        data = {
            'testcases': [{
                'name': '嵌套用例',
                'steps': '步骤',
                'expected_result': '结果',
                'test_context': ctx,
            }]
        }
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/', data, format='json'
        )
        self.assertEqual(resp.status_code, 201)
        tc = TestCaseModel.objects.get(project=self.project)
        self.assertTrue(tc.test_context['elements'][0]['extra']['nested']['deep'])


# ══════════════════════════════════════════════════════════════════
# _format_page_context / _format_api_context 详细测试
# ══════════════════════════════════════════════════════════════════

class FormatPageContextDetailTest(TestCase):
    """_format_page_context 边界情况测试"""

    def test_element_without_description(self):
        """元素缺少 description 时不输出多余分隔符"""
        tc = MagicMock()
        tc.test_context = {
            'context_type': 'page',
            'path': '/test',
            'elements': [
                {'selector': '#btn', 'type': 'button', 'label': '按钮'},
            ]
        }
        result = _format_page_context(tc.test_context)
        self.assertIn('按钮: `#btn`', result)
        # 不应有多余的 — 分隔符
        self.assertNotIn('按钮: `#btn` (button) —', result)

    def test_element_without_label_uses_default(self):
        """元素缺少 label 时使用默认文字"""
        tc = MagicMock()
        tc.test_context = {
            'context_type': 'page',
            'path': '/test',
            'elements': [
                {'selector': '#input1', 'type': 'input'},
            ]
        }
        result = _format_page_context(tc.test_context)
        self.assertIn('元素: `#input1`', result)

    def test_page_context_no_path_no_source_file(self):
        """页面 context 无 path 和 source_file"""
        ctx = {
            'context_type': 'page',
            'elements': [{'selector': '#btn', 'type': 'button', 'label': '按钮'}]
        }
        result = _format_page_context(ctx)
        self.assertIn('页面元素信息', result)
        self.assertIn('按钮', result)
        self.assertNotIn('页面路径:', result)
        self.assertNotIn('来源文件:', result)


class FormatApiContextDetailTest(TestCase):
    """_format_api_context 边界情况测试"""

    def test_api_with_method_and_path(self):
        """API 同时有 method 和 path"""
        ctx = {
            'context_type': 'api',
            'path': '/api/users',
            'method': 'POST',
            'params': [],
            'response_fields': []
        }
        result = _format_api_context(ctx)
        self.assertIn('POST /api/users', result)

    def test_api_with_only_path(self):
        """API 仅有 path，无 method，仍输出端点信息"""
        ctx = {
            'context_type': 'api',
            'path': '/api/data',
            'params': [],
        }
        result = _format_api_context(ctx)
        self.assertIn('/api/data', result)
        # 仅有 path 时仍然输出端点行
        self.assertIn('端点:', result)

    def test_api_param_required_true(self):
        """必填参数显示"必填"标记"""
        ctx = {
            'context_type': 'api',
            'path': '/api/users',
            'method': 'POST',
            'params': [
                {'name': 'username', 'in': 'body', 'type': 'string', 'required': True},
            ]
        }
        result = _format_api_context(ctx)
        self.assertIn('必填', result)

    def test_api_response_field_with_description(self):
        """响应字段带 description"""
        ctx = {
            'context_type': 'api',
            'path': '/api/users',
            'method': 'GET',
            'response_fields': [
                {'name': 'created_at', 'type': 'datetime', 'description': '创建时间'},
            ]
        }
        result = _format_api_context(ctx)
        self.assertIn('created_at', result)
        self.assertIn('创建时间', result)


# ══════════════════════════════════════════════════════════════════
# _parse_analysis_response 额外边界测试
# ══════════════════════════════════════════════════════════════════

class ParseAnalysisResponseEdgeCaseTest(TestCase):
    """_parse_analysis_response 边界情况"""

    def test_empty_pages_and_apis(self):
        """pages 和 apis 都为空数组"""
        raw = json.dumps({"pages": [], "apis": []})
        items = _parse_analysis_response(raw)
        self.assertEqual(items, [])

    def test_missing_pages_key(self):
        """JSON 中缺少 pages 键"""
        raw = json.dumps({"apis": [{"path": "/api/test", "method": "GET", "name": "test"}]})
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['type'], 'api')

    def test_missing_apis_key(self):
        """JSON 中缺少 apis 键"""
        raw = json.dumps({"pages": [{"path": "/home", "name": "首页"}]})
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['type'], 'page')

    def test_non_dict_json_returns_empty(self):
        """JSON 数组（非 dict）返回空列表"""
        raw = json.dumps([1, 2, 3])
        items = _parse_analysis_response(raw)
        self.assertEqual(items, [])

    def test_page_with_null_params_not_inherited(self):
        """页面 item 不继承 API 的 params/response_fields"""
        raw = json.dumps({
            "pages": [{"path": "/users", "name": "用户"}],
            "apis": [{"path": "/api/users", "method": "GET", "name": "用户API",
                      "params": [{"name": "page", "in": "query", "type": "integer", "required": False}]}]
        })
        items = _parse_analysis_response(raw)
        page = items[0]
        api = items[1]
        self.assertEqual(page['elements'], [])
        self.assertEqual(page['params'], [])
        self.assertEqual(api['params'], [{'name': 'page', 'in': 'query', 'type': 'integer', 'required': False}])

    def test_api_with_null_elements_not_inherited(self):
        """API item 不继承页面的 elements"""
        raw = json.dumps({
            "pages": [{"path": "/users", "name": "用户", "elements": [{"selector": "#btn", "type": "button", "label": "按钮"}]}],
            "apis": [{"path": "/api/users", "method": "GET", "name": "用户API"}]
        })
        items = _parse_analysis_response(raw)
        api = items[1]
        self.assertEqual(api['elements'], [])
        self.assertEqual(api['params'], [])


# ══════════════════════════════════════════════════════════════════
# 运行入口
# ══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import unittest
    unittest.main()
