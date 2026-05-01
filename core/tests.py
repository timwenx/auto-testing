"""
Tests for:
- ExecutionRecordListSerializer.testcase_feature_group field
- batch_convert_scripts API endpoint
"""
import json
from django.test import TestCase as DjangoTestCase, override_settings
from rest_framework.test import APIClient
from .models import (
    Project, TestCase as TCModel, ExecutionRecord, Script,
)


@override_settings(
    MEDIA_ROOT='/tmp/mytest_test_media/',
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
)
class ExecutionRecordListSerializerTest(DjangoTestCase):
    """测试 ExecutionRecordListSerializer 包含 testcase_feature_group 字段"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(
            name='测试项目', base_url='https://example.com',
        )

    def test_list_serializer_includes_feature_group(self):
        """列表接口应返回 testcase_feature_group 字段"""
        tc = TCModel.objects.create(
            project=self.project, name='用例1', steps='步骤', expected_result='结果',
            feature_group='用户登录',
        )
        record = ExecutionRecord.objects.create(
            project=self.project, testcase=tc, status='passed',
            execution_mode='agent', duration=10.5,
        )
        resp = self.client.get('/api/executions/')
        data = resp.json()
        results = data.get('results', data)
        self.assertTrue(len(results) > 0)
        found = results[0]
        self.assertEqual(found['testcase_feature_group'], '用户登录')

    def test_list_serializer_empty_feature_group(self):
        """无功能点的用例应返回空字符串"""
        tc = TCModel.objects.create(
            project=self.project, name='用例2', steps='步骤', expected_result='结果',
            feature_group='',
        )
        record = ExecutionRecord.objects.create(
            project=self.project, testcase=tc, status='failed',
            execution_mode='agent',
        )
        resp = self.client.get('/api/executions/')
        data = resp.json()
        results = data.get('results', data)
        found = next(r for r in results if r['id'] == record.id)
        self.assertEqual(found['testcase_feature_group'], '')

    def test_list_serializer_no_testcase(self):
        """无关联用例的执行记录应返回空字符串"""
        record = ExecutionRecord.objects.create(
            project=self.project, status='error',
            execution_mode='agent',
        )
        resp = self.client.get('/api/executions/')
        data = resp.json()
        results = data.get('results', data)
        found = next(r for r in results if r['id'] == record.id)
        self.assertEqual(found['testcase_feature_group'], '')


@override_settings(
    MEDIA_ROOT='/tmp/mytest_test_media/',
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
)
class BatchConvertScriptsTest(DjangoTestCase):
    """测试批量脚本转换 API"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(
            name='批量转换项目', base_url='https://example.com',
        )
        self.tc_login = TCModel.objects.create(
            project=self.project, name='登录测试', steps='步骤', expected_result='结果',
            feature_group='用户登录',
        )
        self.tc_order = TCModel.objects.create(
            project=self.project, name='下单测试', steps='步骤', expected_result='结果',
            feature_group='订单管理',
        )

    def _make_record(self, testcase, status='passed', mode='agent'):
        """创建一个带 tool_calls_log 的执行记录"""
        record = ExecutionRecord.objects.create(
            project=self.project, testcase=testcase,
            status=status, execution_mode=mode, duration=5.0,
        )
        # 写入合法的 tool_calls_log 使 convert_execution_to_script 可解析
        record.log = json.dumps({
            'tool_calls': [
                {'tool': 'browser_navigate', 'input': {'url': 'https://example.com/login'}},
                {'tool': 'browser_fill', 'input': {'selector': '#username', 'value': 'admin'}},
                {'tool': 'browser_click', 'input': {'selector': '#submit'}},
            ]
        })
        record.save(update_fields=['log'])
        return record

    def test_batch_convert_creates_scripts(self):
        """批量转换应为指定功能点的所有 Agent 执行记录创建 Script"""
        self._make_record(self.tc_login)
        self._make_record(self.tc_login, status='failed')

        resp = self.client.post('/api/scripts/batch-convert/', {
            'project_id': self.project.id,
            'feature_group': '用户登录',
        }, format='json')

        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['created'], 2)
        self.assertEqual(data['skipped'], 0)
        self.assertEqual(len(data['scripts']), 2)

        # 验证 Script 记录存在于数据库
        scripts = Script.objects.filter(project=self.project, feature_group='用户登录')
        self.assertEqual(scripts.count(), 2)

    def test_batch_convert_skips_existing_scripts(self):
        """已有 Script 的执行记录应跳过"""
        record = self._make_record(self.tc_login)
        # 先手动创建一个 Script
        Script.objects.create(
            project=self.project, testcase=self.tc_login,
            source_execution=record, name='已有脚本',
            feature_group='用户登录', script_data={}, status='active', version=1,
        )

        resp = self.client.post('/api/scripts/batch-convert/', {
            'project_id': self.project.id,
            'feature_group': '用户登录',
        }, format='json')

        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['created'], 0)
        self.assertEqual(data['skipped'], 1)

    def test_batch_convert_different_feature_groups(self):
        """不同功能点的执行记录互不影响"""
        self._make_record(self.tc_login)  # 用户登录
        self._make_record(self.tc_order)  # 订单管理

        # 只转换用户登录
        resp = self.client.post('/api/scripts/batch-convert/', {
            'project_id': self.project.id,
            'feature_group': '用户登录',
        }, format='json')

        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['scripts'][0]['feature_group'], '用户登录')

        # 订单管理不应被转换
        self.assertFalse(Script.objects.filter(feature_group='订单管理').exists())

    def test_batch_convert_no_records(self):
        """没有可转换记录时应返回 400"""
        resp = self.client.post('/api/scripts/batch-convert/', {
            'project_id': self.project.id,
            'feature_group': '不存在的功能点',
        }, format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())

    def test_batch_convert_invalid_project(self):
        """不存在的项目应返回 404"""
        resp = self.client.post('/api/scripts/batch-convert/', {
            'project_id': 99999,
            'feature_group': '用户登录',
        }, format='json')

        self.assertEqual(resp.status_code, 404)

    def test_batch_convert_empty_feature_group(self):
        """空功能点（未分组）应正确筛选"""
        tc_no_group = TCModel.objects.create(
            project=self.project, name='无分组用例', steps='步骤', expected_result='结果',
            feature_group='',
        )
        self._make_record(tc_no_group)

        resp = self.client.post('/api/scripts/batch-convert/', {
            'project_id': self.project.id,
            'feature_group': '',
        }, format='json')

        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['created'], 1)

    def test_batch_convert_only_agent_mode(self):
        """只应转换 agent 模式的执行记录"""
        # 创建一个 script 模式的记录
        record = ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc_login,
            status='passed', execution_mode='script', duration=5.0,
        )
        record.log = json.dumps({'tool_calls': [{'tool': 'browser_navigate', 'input': {'url': 'https://example.com'}}]})
        record.save(update_fields=['log'])

        resp = self.client.post('/api/scripts/batch-convert/', {
            'project_id': self.project.id,
            'feature_group': '用户登录',
        }, format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())

    def test_batch_convert_only_terminal_status(self):
        """只应转换已完成状态的执行记录"""
        # 创建一个 running 状态的记录
        ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc_login,
            status='running', execution_mode='agent',
        )

        resp = self.client.post('/api/scripts/batch-convert/', {
            'project_id': self.project.id,
            'feature_group': '用户登录',
        }, format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())

    def test_batch_convert_idempotent(self):
        """重复调用不应创建重复脚本"""
        self._make_record(self.tc_login)

        # 第一次调用
        resp1 = self.client.post('/api/scripts/batch-convert/', {
            'project_id': self.project.id,
            'feature_group': '用户登录',
        }, format='json')
        self.assertEqual(resp1.json()['created'], 1)

        # 第二次调用 — 应全部跳过
        resp2 = self.client.post('/api/scripts/batch-convert/', {
            'project_id': self.project.id,
            'feature_group': '用户登录',
        }, format='json')
        self.assertEqual(resp2.json()['created'], 0)
        self.assertEqual(resp2.json()['skipped'], 1)

        # 数据库中只有 1 条 Script
        self.assertEqual(Script.objects.filter(project=self.project).count(), 1)

    def test_batch_convert_missing_project_id(self):
        """缺少 project_id 应返回 400"""
        resp = self.client.post('/api/scripts/batch-convert/', {
            'feature_group': '用户登录',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
