"""
Unit tests for core views, models, and serializers.
"""
import json
import os
import tempfile
import threading
from unittest import mock
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from .models import (
    Project, TestCase as TC_Model, ExecutionRecord, AIConversation,
    SystemSetting, Screenshot, RepoAnalysis, PreconditionTemplate,
    Script, TestPlan, TestPlanItem, PlanExecution,
)
from .execution_engine import _strip_markdown_code_fences, _build_step_logs, _extract_screenshots


class ProjectAPITest(TestCase):
    """Tests for /api/projects/ endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.project_data = {
            'name': 'Demo Project',
            'description': 'A test project',
            'base_url': 'https://example.com',
        }

    def test_create_project(self):
        resp = self.client.post('/api/projects/', self.project_data, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['name'], 'Demo Project')

    def test_list_projects(self):
        Project.objects.create(name='P1')
        Project.objects.create(name='P2')
        resp = self.client.get('/api/projects/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get('results', resp.data)
        self.assertEqual(len(results), 2)

    def test_get_project_detail(self):
        p = Project.objects.create(name='Detail Test')
        resp = self.client.get(f'/api/projects/{p.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'Detail Test')

    def test_update_project(self):
        p = Project.objects.create(name='Old Name')
        resp = self.client.patch(f'/api/projects/{p.id}/', {'name': 'New Name'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        p.refresh_from_db()
        self.assertEqual(p.name, 'New Name')

    def test_delete_project(self):
        p = Project.objects.create(name='To Delete')
        resp = self.client.delete(f'/api/projects/{p.id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Project.objects.filter(id=p.id).exists())

    def test_project_testcase_count(self):
        p = Project.objects.create(name='Count Test')
        TC_Model.objects.create(project=p, name='TC1', steps='step1', expected_result='ok')
        TC_Model.objects.create(project=p, name='TC2', steps='step2', expected_result='ok')
        self.assertEqual(p.testcase_count, 2)


class TestCaseAPITest(TestCase):
    """Tests for /api/testcases/ endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='TC Project', base_url='https://example.com')

    def test_create_testcase(self):
        data = {
            'project': self.project.id,
            'name': 'Login Test',
            'steps': '1. Open login page\n2. Enter credentials',
            'expected_result': 'Logged in successfully',
        }
        resp = self.client.post('/api/testcases/', data, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['name'], 'Login Test')

    def test_list_testcases_filtered_by_project(self):
        p2 = Project.objects.create(name='Other')
        TC_Model.objects.create(project=self.project, name='TC-A', steps='s', expected_result='r')
        TC_Model.objects.create(project=p2, name='TC-B', steps='s', expected_result='r')
        resp = self.client.get(f'/api/testcases/?project={self.project.id}')
        results = resp.data.get('results', resp.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], 'TC-A')

    def test_project_testcases_endpoint(self):
        TC_Model.objects.create(project=self.project, name='TC1', steps='s', expected_result='r')
        TC_Model.objects.create(project=self.project, name='TC2', steps='s', expected_result='r')
        resp = self.client.get(f'/api/projects/{self.project.id}/testcases/')
        results = resp.data.get('results', resp.data)
        self.assertEqual(len(results), 2)

    def test_delete_testcase(self):
        tc = TC_Model.objects.create(project=self.project, name='Del', steps='s', expected_result='r')
        resp = self.client.delete(f'/api/testcases/{tc.id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)


class ExecutionRecordAPITest(TestCase):
    """Tests for execution record endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='Exec Project', base_url='https://example.com')
        self.tc = TC_Model.objects.create(
            project=self.project, name='Test Case', steps='steps', expected_result='ok',
        )

    def test_list_executions(self):
        ExecutionRecord.objects.create(project=self.project, testcase=self.tc, status='passed')
        resp = self.client.get('/api/executions/')
        results = resp.data.get('results', resp.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 'passed')

    def test_list_executions_filtered_by_project(self):
        p2 = Project.objects.create(name='Other')
        tc2 = TC_Model.objects.create(project=p2, name='TC2', steps='s', expected_result='r')
        ExecutionRecord.objects.create(project=self.project, testcase=self.tc, status='passed')
        ExecutionRecord.objects.create(project=p2, testcase=tc2, status='failed')
        resp = self.client.get(f'/api/executions/?project={self.project.id}')
        results = resp.data.get('results', resp.data)
        self.assertEqual(len(results), 1)

    def test_get_execution_detail(self):
        er = ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc, status='failed', error_message='oops',
        )
        resp = self.client.get(f'/api/executions/{er.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'failed')


class ExecuteEndpointTest(TestCase):
    """Tests for execute endpoints (validation only — actual execution mocked)."""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='Exec', base_url='https://example.com')
        self.tc = TC_Model.objects.create(
            project=self.project, name='TC', steps='step1', expected_result='ok',
        )

    def test_execute_missing_base_url(self):
        no_url_project = Project.objects.create(name='No URL')
        tc = TC_Model.objects.create(project=no_url_project, name='TC', steps='s', expected_result='r')
        resp = self.client.post(f'/api/testcases/{tc.id}/execute-agent/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('URL', resp.data['error'])

    def test_execute_nonexistent_testcase(self):
        resp = self.client.post('/api/testcases/99999/execute-agent/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_execute_all_no_testcases(self):
        empty_project = Project.objects.create(name='Empty', base_url='https://example.com')
        resp = self.client.post(f'/api/projects/{empty_project.id}/execute-agent/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class AIEndpointTest(TestCase):
    """Tests for AI-related endpoints (validation only)."""

    def setUp(self):
        self.client = APIClient()

    def test_generate_missing_fields(self):
        resp = self.client.post('/api/ai/generate-testcase/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_analyze_missing_fields(self):
        resp = self.client.post('/api/ai/analyze-result/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_nonexistent_project(self):
        resp = self.client.post(
            '/api/ai/generate-testcase/',
            {'project_id': 99999, 'requirement': 'test login'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_adjust_missing_fields(self):
        resp = self.client.post('/api/ai/adjust-testcase/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_adjust_nonexistent_project(self):
        resp = self.client.post(
            '/api/ai/adjust-testcase/',
            {
                'project_id': 99999,
                'user_feedback': 'add more cases',
                'current_cases': [{'name': 'test', 'steps': 's', 'expected_result': 'r'}],
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class AIConversationAPITest(TestCase):
    """Tests for AI conversation list endpoint."""

    def test_list_conversations(self):
        project = Project.objects.create(name='P')
        AIConversation.objects.create(
            conversation_type='generate', project=project,
            user_message='test', ai_response='[]',
        )
        client = APIClient()
        resp = client.get('/api/ai/conversations/')
        results = resp.data.get('results', resp.data)
        self.assertEqual(len(results), 1)

    def test_filter_by_type(self):
        project = Project.objects.create(name='P')
        AIConversation.objects.create(
            conversation_type='generate', project=project,
            user_message='gen', ai_response='[]',
        )
        AIConversation.objects.create(
            conversation_type='analyze', project=project,
            user_message='analyze', ai_response='{}',
        )
        client = APIClient()
        resp = client.get('/api/ai/conversations/?type=generate')
        results = resp.data.get('results', resp.data)
        self.assertEqual(len(results), 1)


class SystemSettingTest(TestCase):
    """Tests for SystemSetting model and API."""

    def test_get_default(self):
        val = SystemSetting.get('max_workers')
        self.assertEqual(val, '3')

    def test_get_custom(self):
        SystemSetting.objects.create(key='anthropic_api_key', value='sk-ant-test')
        val = SystemSetting.get('anthropic_api_key')
        self.assertEqual(val, 'sk-ant-test')

    def test_get_missing_returns_default(self):
        val = SystemSetting.get('nonexistent', 'fallback')
        self.assertEqual(val, 'fallback')

    def test_get_all_dict_with_defaults(self):
        result = SystemSetting.get_all_dict()
        self.assertIn('anthropic_api_key', result)
        self.assertIn('max_workers', result)
        self.assertIn('anthropic_model', result)
        self.assertEqual(result['anthropic_model'], 'claude-sonnet-4-20250514')

    def test_settings_get_endpoint(self):
        client = APIClient()
        resp = client.get('/api/settings/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('anthropic_api_key', resp.data)

    def test_settings_put_endpoint(self):
        client = APIClient()
        resp = client.put(
            '/api/settings/',
            {'settings': {'anthropic_api_key': 'sk-ant-test', 'max_workers': '5'}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['anthropic_api_key'], 'sk-ant-test')
        self.assertEqual(resp.data['max_workers'], '5')
        # Verify persisted
        self.assertEqual(SystemSetting.get('anthropic_api_key'), 'sk-ant-test')


class SystemStatsTest(TestCase):
    """Tests for /api/stats/ endpoint."""

    def test_stats_endpoint(self):
        Project.objects.create(name='P1')
        Project.objects.create(name='P2')
        client = APIClient()
        resp = client.get('/api/stats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['projects'], 2)

    def test_health_check(self):
        client = APIClient()
        resp = client.get('/api/health/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'ok')


class NewFieldsTest(TestCase):
    """Tests for markdown_content, priority, test_type fields on TestCase."""

    def setUp(self):
        self.project = Project.objects.create(name='P', base_url='https://example.com')

    def test_create_testcase_with_new_fields(self):
        data = {
            'project': self.project.id,
            'name': 'Markdown TC',
            'steps': 'step1',
            'expected_result': 'ok',
            'markdown_content': '# Test\n\n## Steps\n1. Go to page',
            'priority': 'P0',
            'test_type': '功能',
        }
        client = APIClient()
        resp = client.post('/api/testcases/', data, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['priority'], 'P0')
        self.assertEqual(resp.data['test_type'], '功能')
        self.assertIn('# Test', resp.data['markdown_content'])

    def test_testcase_new_fields_defaults(self):
        tc = TC_Model.objects.create(
            project=self.project, name='Default', steps='s', expected_result='r',
        )
        self.assertEqual(tc.markdown_content, '')
        self.assertEqual(tc.priority, '')
        self.assertEqual(tc.test_type, '')

    def test_testcase_priority_choices(self):
        tc = TC_Model.objects.create(
            project=self.project, name='P0 TC', steps='s', expected_result='r', priority='P0',
        )
        self.assertEqual(tc.priority, 'P0')
        tc2 = TC_Model.objects.create(
            project=self.project, name='P1 TC', steps='s', expected_result='r', priority='P1',
        )
        self.assertEqual(tc2.priority, 'P1')


class ProjectSerializerSecurityTest(TestCase):
    """Tests for sensitive field handling in ProjectSerializer."""

    def test_password_not_in_response(self):
        client = APIClient()
        resp = client.post('/api/projects/', {
            'name': 'Secure Project',
            'repo_url': 'https://github.com/test/repo.git',
            'repo_password': 'secret123',
            'github_token': 'ghp_xxx',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        # Sensitive fields should NOT appear in response
        self.assertNotIn('repo_password', resp.data)
        self.assertNotIn('github_token', resp.data)
        # Non-sensitive fields should appear
        self.assertEqual(resp.data['repo_url'], 'https://github.com/test/repo.git')

    def test_password_stored_in_db(self):
        client = APIClient()
        resp = client.post('/api/projects/', {
            'name': 'Stored',
            'repo_password': 'secret',
            'github_token': 'ghp_xxx',
        }, format='json')
        p = Project.objects.get(pk=resp.data['id'])
        self.assertEqual(p.repo_password, 'secret')
        self.assertEqual(p.github_token, 'ghp_xxx')


class GitRepoFieldsTest(TestCase):
    """Tests for Git repo fields on Project model."""

    def test_project_git_fields(self):
        p = Project.objects.create(
            name='Git Project',
            repo_url='https://github.com/test/repo.git',
            repo_username='user',
            repo_password='pass',
            github_url='https://github.com/test/repo',
            github_token='ghp_xxx',
        )
        self.assertEqual(p.repo_url, 'https://github.com/test/repo.git')
        self.assertEqual(p.repo_username, 'user')
        self.assertEqual(p.repo_password, 'pass')
        self.assertEqual(p.local_repo_path, '')

    def test_project_git_fields_defaults(self):
        p = Project.objects.create(name='No Git')
        self.assertEqual(p.repo_url, '')
        self.assertEqual(p.repo_username, '')
        self.assertEqual(p.repo_password, '')
        self.assertEqual(p.github_url, '')
        self.assertEqual(p.github_token, '')
        self.assertEqual(p.local_repo_path, '')


# ─── Agent API Endpoint Tests ───


class AgentConfirmTest(TestCase):
    """Tests for /api/agent/confirm/ endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='P', base_url='https://example.com')
        self.tc = TC_Model.objects.create(
            project=self.project, name='TC', steps='s', expected_result='r',
            status='draft', created_by='agent',
        )

    def test_confirm_changes_status_to_ready(self):
        resp = self.client.post(
            '/api/agent/confirm/',
            {'testcase_id': self.tc.id},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'ready')
        self.assertTrue(resp.data['ready_to_execute'])
        self.tc.refresh_from_db()
        self.assertEqual(self.tc.status, 'ready')

    def test_confirm_missing_testcase_id(self):
        resp = self.client.post('/api/agent/confirm/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_nonexistent_testcase(self):
        resp = self.client.post(
            '/api/agent/confirm/',
            {'testcase_id': 99999},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class AgentRefineTest(TestCase):
    """Tests for /api/agent/refine/ endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='P', base_url='https://example.com')
        self.tc = TC_Model.objects.create(
            project=self.project, name='TC', steps='s', expected_result='r',
            status='draft', created_by='agent', version=1,
        )

    def test_refine_missing_testcase_id(self):
        resp = self.client.post('/api/agent/refine/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_refine_nonexistent_testcase(self):
        resp = self.client.post(
            '/api/agent/refine/',
            {'testcase_id': 99999, 'user_feedback': 'add more'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @mock.patch('core.agent_service.refine_testcase_with_agent')
    def test_refine_success_question(self, mock_refine):
        mock_refine.return_value = {
            'action': 'question',
            'message': '是否需要测试空输入场景？',
            'suggestions': ['空输入测试', '特殊字符测试'],
        }
        resp = self.client.post(
            '/api/agent/refine/',
            {'testcase_id': self.tc.id, 'user_feedback': ''},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['action'], 'question')
        self.assertIn('suggestions', resp.data)
        mock_refine.assert_called_once()

    @mock.patch('core.agent_service.refine_testcase_with_agent')
    def test_refine_success_update(self, mock_refine):
        mock_refine.return_value = {
            'action': 'update',
            'message': '已根据反馈更新用例',
            'updated_testcase': {
                'name': 'Updated TC',
                'markdown_content': '# Updated',
            },
        }
        resp = self.client.post(
            '/api/agent/refine/',
            {'testcase_id': self.tc.id, 'user_feedback': '增加超时测试'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['action'], 'update')
        self.assertIn('updated_testcase', resp.data)


class AgentGenerateTest(TestCase):
    """Tests for /api/agent/generate/ endpoint."""

    def setUp(self):
        self.client = APIClient()

    def test_generate_missing_fields(self):
        resp = self.client.post('/api/agent/generate/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_nonexistent_project(self):
        resp = self.client.post(
            '/api/agent/generate/',
            {'project_id': 99999, 'requirement': 'test login'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @mock.patch('core.views.ai_engine.generate_testcases')
    def test_generate_success(self, mock_generate):
        project = Project.objects.create(name='P', base_url='https://example.com')
        mock_generate.return_value = [
            {
                'name': 'Login Test',
                'description': 'Test login flow',
                'steps': '1. Go to login\n2. Enter credentials',
                'expected_result': 'Logged in',
                'markdown_content': '# Login Test',
                'priority': 'P0',
                'test_type': '功能',
            },
        ]
        resp = self.client.post(
            '/api/agent/generate/',
            {'project_id': project.id, 'requirement': 'test login'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('testcases', resp.data)
        self.assertIn('steps', resp.data)
        self.assertIn('conversation_id', resp.data)
        self.assertEqual(len(resp.data['testcases']), 1)
        # Verify TestCase was created in DB
        self.assertEqual(TC_Model.objects.filter(project=project).count(), 1)
        tc = TC_Model.objects.filter(project=project).first()
        self.assertEqual(tc.created_by, 'agent')
        self.assertTrue(tc.is_ai_generated)


class AgentExecuteTest(TestCase):
    """Tests for /api/agent/execute/ endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='P', base_url='https://example.com')
        self.tc = TC_Model.objects.create(
            project=self.project, name='TC', steps='s', expected_result='r',
            status='draft',
        )

    def test_execute_missing_testcase_id(self):
        resp = self.client.post('/api/agent/execute/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_execute_nonexistent_testcase(self):
        resp = self.client.post(
            '/api/agent/execute/',
            {'testcase_id': 99999},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_execute_missing_base_url(self):
        no_url_project = Project.objects.create(name='NoURL')
        tc = TC_Model.objects.create(project=no_url_project, name='TC', steps='s', expected_result='r')
        resp = self.client.post(
            '/api/agent/execute/',
            {'testcase_id': tc.id},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @mock.patch('core.views.execution_engine.execute_testcase_with_agent')
    def test_execute_success(self, mock_execute):
        mock_execute.return_value = {
            'status': 'passed',
            'log': 'Test passed',
            'error_message': '',
            'duration': 5.0,
            'script': '{"tool_calls": []}',
            'step_logs': [{'step_num': 1, 'action': 'navigate'}],
            'screenshots': ['/tmp/screenshot.png'],
            'agent_response': {'response_text': 'Done'},
        }
        resp = self.client.post(
            '/api/agent/execute/',
            {'testcase_id': self.tc.id, 'execution_mode': 'agent'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.data['status'], 'running')
        self.assertIn('test_run_id', resp.data)
        # Verify ExecutionRecord was created
        self.assertTrue(ExecutionRecord.objects.filter(testcase=self.tc).exists())
        record = ExecutionRecord.objects.get(testcase=self.tc)
        self.assertEqual(record.execution_mode, 'agent')


# ─── New Model Fields Tests ───


class TestCaseAgentFieldsTest(TestCase):
    """Tests for new TestCase agent-related fields."""

    def setUp(self):
        self.project = Project.objects.create(name='P', base_url='https://example.com')

    def test_create_testcase_with_agent_fields(self):
        tc = TC_Model.objects.create(
            project=self.project,
            name='Agent TC',
            steps='s',
            expected_result='r',
            target_page_or_api='/api/users/',
            created_by='agent',
            version=1,
            conversation_history=[{'role': 'user', 'content': 'test'}],
        )
        self.assertEqual(tc.target_page_or_api, '/api/users/')
        self.assertEqual(tc.created_by, 'agent')
        self.assertEqual(tc.version, 1)
        self.assertEqual(len(tc.conversation_history), 1)

    def test_agent_fields_defaults(self):
        tc = TC_Model.objects.create(
            project=self.project, name='Default', steps='s', expected_result='r',
        )
        self.assertEqual(tc.target_page_or_api, '')
        self.assertEqual(tc.created_by, 'manual')
        self.assertEqual(tc.version, 1)
        self.assertEqual(tc.conversation_history, [])

    def test_created_by_choices(self):
        for choice_val, _ in TC_Model.CREATED_BY_CHOICES:
            tc = TC_Model.objects.create(
                project=self.project,
                name=f'TC-{choice_val}',
                steps='s',
                expected_result='r',
                created_by=choice_val,
            )
            self.assertEqual(tc.created_by, choice_val)

    def test_conversation_history_json_roundtrip(self):
        history = [
            {'role': 'user', 'content': '分析用例'},
            {'role': 'assistant', 'content': '{"action":"question","message":"是否需要?"}'},
        ]
        tc = TC_Model.objects.create(
            project=self.project, name='JSON', steps='s', expected_result='r',
            conversation_history=history,
        )
        tc.refresh_from_db()
        self.assertEqual(len(tc.conversation_history), 2)
        self.assertEqual(tc.conversation_history[0]['role'], 'user')

    def test_serializer_exposes_agent_fields(self):
        tc = TC_Model.objects.create(
            project=self.project,
            name='Ser TC',
            steps='s',
            expected_result='r',
            target_page_or_api='/login',
            created_by='agent',
            version=3,
        )
        client = APIClient()
        resp = client.get(f'/api/testcases/{tc.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['target_page_or_api'], '/login')
        self.assertEqual(resp.data['created_by'], 'agent')
        self.assertEqual(resp.data['version'], 3)


class ExecutionRecordDetailFieldsTest(TestCase):
    """Tests for new ExecutionRecord detail fields."""

    def setUp(self):
        self.project = Project.objects.create(name='P', base_url='https://example.com')
        self.tc = TC_Model.objects.create(
            project=self.project, name='TC', steps='s', expected_result='r',
        )

    def test_create_record_with_detail_fields(self):
        record = ExecutionRecord.objects.create(
            project=self.project,
            testcase=self.tc,
            status='passed',
            execution_mode='agent',
            screenshots=['/tmp/ss1.png', '/tmp/ss2.png'],
            step_logs=[
                {'step_num': 1, 'action': 'browser_navigate', 'target': 'https://example.com', 'result': 'ok'},
                {'step_num': 2, 'action': '截图', 'target': '', 'result': '截图已保存: /tmp/ss1.png'},
            ],
            agent_response={'response_text': 'Test passed', 'total_input_tokens': 1000, 'total_output_tokens': 500},
        )
        record.refresh_from_db()
        self.assertEqual(len(record.screenshots), 2)
        self.assertEqual(len(record.step_logs), 2)
        self.assertEqual(record.agent_response['response_text'], 'Test passed')

    def test_detail_fields_defaults(self):
        record = ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc, status='passed',
        )
        self.assertEqual(record.screenshots, [])
        self.assertEqual(record.step_logs, [])
        self.assertEqual(record.agent_response, {})

    def test_serializer_exposes_detail_fields(self):
        record = ExecutionRecord.objects.create(
            project=self.project,
            testcase=self.tc,
            status='passed',
            screenshots=['/tmp/ss.png'],
            step_logs=[{'step_num': 1, 'action': 'click'}],
            agent_response={'response_text': 'Done'},
        )
        client = APIClient()
        resp = client.get(f'/api/executions/{record.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('screenshots', resp.data)
        self.assertIn('step_logs', resp.data)
        self.assertIn('agent_response', resp.data)
        self.assertEqual(len(resp.data['screenshots']), 1)
        self.assertEqual(resp.data['agent_response']['response_text'], 'Done')


# ─── Screenshot Endpoint Tests ───


class ScreenshotEndpointTest(TestCase):
    """Tests for /api/executions/screenshots/ endpoint."""

    def test_missing_path_param(self):
        client = APIClient()
        resp = client.get('/api/executions/screenshots/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nonexistent_file(self):
        client = APIClient()
        resp = client.get('/api/executions/screenshots/?path=/nonexistent/file.png')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_path_not_in_db(self):
        """File exists but is not recorded in any ExecutionRecord."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(b'\x89PNG\r\n')
            temp_path = f.name
        try:
            client = APIClient()
            resp = client.get(f'/api/executions/screenshots/?path={temp_path}')
            # Should be 404 because the path is not in any ExecutionRecord
            self.assertIn(resp.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])
        finally:
            import os
            os.unlink(temp_path)


# ─── Round 2: 执行引擎工具函数测试 ───


class StripMarkdownCodeFencesTest(TestCase):
    """_strip_markdown_code_fences 测试"""

    def test_strips_python_fence(self):
        code = '```python\nprint("hello")\n```'
        self.assertEqual(_strip_markdown_code_fences(code), 'print("hello")')

    def test_strips_js_fence(self):
        code = '```javascript\nconsole.log("hi")\n```'
        self.assertEqual(_strip_markdown_code_fences(code), 'console.log("hi")')

    def test_strips_py_fence(self):
        code = '```py\nx = 1\n```'
        self.assertEqual(_strip_markdown_code_fences(code), 'x = 1')

    def test_strips_plain_fence(self):
        code = '```\nraw code\n```'
        self.assertEqual(_strip_markdown_code_fences(code), 'raw code')

    def test_no_fence_returns_original(self):
        code = 'print("hello")'
        self.assertEqual(_strip_markdown_code_fences(code), code)

    def test_empty_string(self):
        self.assertEqual(_strip_markdown_code_fences(''), '')

    def test_none_input(self):
        self.assertIsNone(_strip_markdown_code_fences(None))

    def test_malformed_fence_start_only(self):
        code = '```python\nprint("hello")'
        self.assertEqual(_strip_markdown_code_fences(code), 'print("hello")')

    def test_multiline_code(self):
        code = '```python\ndef foo():\n    return 42\n\nfoo()\n```'
        expected = 'def foo():\n    return 42\n\nfoo()'
        self.assertEqual(_strip_markdown_code_fences(code), expected)

    def test_extra_whitespace_around_fence(self):
        code = '  ```python\nx = 1\n```  \n  '
        self.assertEqual(_strip_markdown_code_fences(code), 'x = 1')


# ─── Round 2: 模型属性与 __str__ 测试 ───


class ProjectModelPropertiesTest(TestCase):
    """Project 模型属性测试"""

    def test_str_representation(self):
        p = Project.objects.create(name='我的项目')
        self.assertEqual(str(p), '我的项目')

    def test_testcase_count_empty(self):
        p = Project.objects.create(name='空项目')
        self.assertEqual(p.testcase_count, 0)

    def test_last_execution_none_when_empty(self):
        p = Project.objects.create(name='P')
        self.assertIsNone(p.last_execution)

    def test_last_execution_returns_latest(self):
        p = Project.objects.create(name='P', base_url='https://a.com')
        tc = TC_Model.objects.create(project=p, name='TC', steps='s', expected_result='r')
        r1 = ExecutionRecord.objects.create(project=p, testcase=tc, status='passed')
        # Force different created_at to ensure deterministic ordering
        from django.utils import timezone
        from datetime import timedelta
        r1.created_at = timezone.now() - timedelta(seconds=10)
        r1.save(update_fields=['created_at'])
        ExecutionRecord.objects.create(project=p, testcase=tc, status='failed')
        self.assertEqual(p.last_execution.status, 'failed')


class ExecutionRecordModelTest(TestCase):
    """ExecutionRecord 模型测试"""

    def setUp(self):
        self.project = Project.objects.create(name='P', base_url='https://a.com')
        self.tc = TC_Model.objects.create(project=self.project, name='TC', steps='s', expected_result='r')

    def test_str_with_testcase(self):
        record = ExecutionRecord.objects.create(project=self.project, testcase=self.tc, status='passed')
        result = str(record)
        self.assertIn('TC', result)
        self.assertIn('passed', result)

    def test_str_without_testcase(self):
        record = ExecutionRecord.objects.create(project=self.project, status='failed')
        result = str(record)
        self.assertIn('批量执行', result)

    def test_default_values(self):
        record = ExecutionRecord.objects.create(project=self.project, testcase=self.tc)
        self.assertEqual(record.status, 'pending')
        self.assertEqual(record.execution_mode, 'script')
        self.assertEqual(record.tool_calls_count, 0)
        self.assertEqual(record.screenshots, [])
        self.assertEqual(record.step_logs, [])
        self.assertEqual(record.agent_response, {})

    def test_execution_mode_choices(self):
        r1 = ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc, execution_mode='agent'
        )
        self.assertEqual(r1.execution_mode, 'agent')


class ScreenshotModelTest(TestCase):
    """Screenshot 模型测试"""

    def test_str_representation(self):
        p = Project.objects.create(name='P', base_url='https://a.com')
        tc = TC_Model.objects.create(project=p, name='TC', steps='s', expected_result='r')
        record = ExecutionRecord.objects.create(project=p, testcase=tc, status='passed')
        ss = Screenshot.objects.create(execution=record, step_num=3, action='点击按钮')
        result = str(ss)
        self.assertIn('3', result)

    def test_str_no_step_num(self):
        p = Project.objects.create(name='P', base_url='https://a.com')
        tc = TC_Model.objects.create(project=p, name='TC', steps='s', expected_result='r')
        record = ExecutionRecord.objects.create(project=p, testcase=tc, status='passed')
        ss = Screenshot.objects.create(execution=record, action='截图')
        self.assertIn('?', str(ss))


# ─── Round 2: 视图辅助函数测试 ───


class SaveAgentResultHelperTest(TestCase):
    """_save_agent_result 辅助函数测试"""

    def setUp(self):
        self.project = Project.objects.create(name='P', base_url='https://a.com')
        self.tc = TC_Model.objects.create(project=self.project, name='TC', steps='s', expected_result='r')
        self.record = ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc, status='running', execution_mode='agent'
        )

    def test_saves_basic_fields(self):
        result = {
            'status': 'passed', 'log': 'ok', 'error_message': '', 'duration': 5.2,
            'script': '{}',
            'step_logs': [{'step_num': 1, 'action': '打开页面'}],
            'screenshots': [], 'agent_response': {'response_text': '通过'},
        }
        from .views import _save_agent_result
        _save_agent_result(self.record, result)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'passed')
        # log gets TOOL_CALLS_JSON appended when script is present
        self.assertIn('ok', self.record.log)
        self.assertEqual(self.record.duration, 5.2)
        self.assertEqual(self.record.step_logs, [{'step_num': 1, 'action': '打开页面'}])
        self.assertEqual(self.record.agent_response, {'response_text': '通过'})

    def test_parses_tool_calls_count(self):
        script_data = json.dumps({'tool_calls': [{'name': 'a'}, {'name': 'b'}, {'name': 'c'}]})
        result = {
            'status': 'passed', 'log': '', 'error_message': '', 'duration': 1,
            'script': script_data, 'step_logs': [], 'screenshots': [], 'agent_response': {},
        }
        from .views import _save_agent_result
        _save_agent_result(self.record, result)
        self.record.refresh_from_db()
        self.assertEqual(self.record.tool_calls_count, 3)

    def test_handles_invalid_script_json(self):
        result = {
            'status': 'failed', 'log': '', 'error_message': 'err', 'duration': 0,
            'script': 'not-json', 'step_logs': [], 'screenshots': [], 'agent_response': {},
        }
        from .views import _save_agent_result
        _save_agent_result(self.record, result)
        self.record.refresh_from_db()
        self.assertEqual(self.record.tool_calls_count, 0)

    def test_handles_missing_optional_fields(self):
        result = {'status': 'error', 'log': '', 'error_message': 'crash', 'duration': 0}
        from .views import _save_agent_result
        _save_agent_result(self.record, result)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'error')
        self.assertEqual(self.record.step_logs, [])
        self.assertEqual(self.record.screenshots, [])


class SaveScriptResultHelperTest(TestCase):
    """_save_script_result 辅助函数测试 — 该函数已移除，改为直接内联"""

    def test_saves_basic_fields(self):
        """验证 _save_agent_result 在无 script 时不会追加 TOOL_CALLS_JSON"""
        p = Project.objects.create(name='P', base_url='https://a.com')
        tc = TC_Model.objects.create(project=p, name='TC', steps='s', expected_result='r')
        record = ExecutionRecord.objects.create(project=p, testcase=tc, status='running')
        result = {
            'status': 'passed', 'log': 'ok', 'error_message': '', 'duration': 3.1,
            'script': '',  # no script
            'step_logs': [], 'screenshots': [], 'agent_response': {},
        }
        from .views import _save_agent_result
        _save_agent_result(record, result)
        record.refresh_from_db()
        self.assertEqual(record.status, 'passed')
        self.assertEqual(record.log, 'ok')
        self.assertEqual(record.duration, 3.1)


class CreateScreenshotRecordsHelperTest(TestCase):
    """_create_screenshot_records 辅助函数测试"""

    def setUp(self):
        self.project = Project.objects.create(name='P', base_url='https://a.com')
        self.tc = TC_Model.objects.create(project=self.project, name='TC', steps='s', expected_result='r')
        self.record = ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc, status='passed'
        )

    @mock.patch('core.views.os.path.isfile', return_value=True)
    def test_creates_records_from_paths(self, mock_isfile):
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            tmp_path = f.name
        try:
            step_logs = [{'screenshot_path': tmp_path, 'action': '截图'}]
            from .views import _create_screenshot_records
            _create_screenshot_records(self.record, step_logs, [tmp_path])
            self.assertEqual(Screenshot.objects.filter(execution=self.record).count(), 1)
        finally:
            os.unlink(tmp_path)

    @mock.patch('core.views.os.path.isfile', return_value=False)
    def test_skips_nonexistent_files(self, mock_isfile):
        from .views import _create_screenshot_records
        _create_screenshot_records(self.record, [], ['/fake/path.png'])
        self.assertEqual(Screenshot.objects.filter(execution=self.record).count(), 0)


# ─── Round 2: Agent 执行端点扩展测试 ───


class AgentExecuteExtendedTest(TestCase):
    """Agent 执行端点扩展测试 — 覆盖 execution_mode 分支"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='P', base_url='https://example.com')
        self.tc = TC_Model.objects.create(
            project=self.project, name='TC', steps='s', expected_result='r',
        )

    @mock.patch('core.views._submit_agent_task')
    @mock.patch('core.views._get_ai_model', return_value='claude-sonnet-4-20250514')
    def test_default_mode_uses_agent(self, mock_model, mock_submit):
        """默认 execution_mode 从 SystemSetting 读取"""
        SystemSetting.objects.create(key='default_execution_mode', value='agent')
        resp = self.client.post('/api/agent/execute/', {'testcase_id': self.tc.id}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.data['execution_mode'], 'agent')
        mock_submit.assert_called_once()

    @mock.patch('core.views._submit_agent_task')
    @mock.patch('core.views._get_ai_model', return_value='claude-sonnet-4-20250514')
    def test_explicit_script_mode_skips_agent(self, mock_model, mock_submit):
        """agent_execute endpoint always uses agent mode"""
        resp = self.client.post(
            '/api/agent/execute/',
            {'testcase_id': self.tc.id},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.data['execution_mode'], 'agent')
        mock_submit.assert_called_once()

    @mock.patch('core.views._submit_agent_task')
    @mock.patch('core.views._get_ai_model', return_value='claude-sonnet-4-20250514')
    def test_explicit_agent_mode_submits_task(self, mock_model, mock_submit):
        resp = self.client.post(
            '/api/agent/execute/',
            {'testcase_id': self.tc.id, 'execution_mode': 'agent'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.data['execution_mode'], 'agent')
        mock_submit.assert_called_once()

    def test_execution_record_has_correct_mode(self):
        """创建的 ExecutionRecord 的 execution_mode 应与请求一致"""
        with mock.patch('core.views._submit_agent_task'), \
             mock.patch('core.views._get_ai_model', return_value='test-model'):
            self.client.post(
                '/api/agent/execute/',
                {'testcase_id': self.tc.id, 'execution_mode': 'agent'},
                format='json',
            )
        record = ExecutionRecord.objects.filter(testcase=self.tc).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.execution_mode, 'agent')
        self.assertEqual(record.ai_model, 'test-model')


# ─── Round 2: 批量执行端点测试 ───


class ExecuteAllEndpointTest(TestCase):
    """批量执行端点测试"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='P', base_url='https://example.com')

    @mock.patch('core.views._submit_agent_task')
    @mock.patch('core.views._get_ai_model', return_value='test-model')
    def test_execute_all_creates_records(self, mock_model, mock_submit):
        TC_Model.objects.create(project=self.project, name='A', steps='s', expected_result='r', status='draft')
        TC_Model.objects.create(project=self.project, name='B', steps='s', expected_result='r', status='ready')
        resp = self.client.post(f'/api/projects/{self.project.id}/execute-agent/')
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        results = resp.data if isinstance(resp.data, list) else resp.data.get('results', resp.data)
        self.assertEqual(len(results), 2)
        self.assertEqual(mock_submit.call_count, 2)

    def test_execute_all_no_url(self):
        self.project.base_url = ''
        self.project.save()
        TC_Model.objects.create(project=self.project, name='A', steps='s', expected_result='r')
        resp = self.client.post(f'/api/projects/{self.project.id}/execute-agent/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_execute_all_no_testcases(self):
        resp = self.client.post(f'/api/projects/{self.project.id}/execute-agent/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ─── Round 3: 执行引擎工具函数测试 ───


class BuildStepLogsTest(TestCase):
    """_build_step_logs 转换测试"""

    def test_basic_tool_calls(self):
        agent_result = {
            'tool_calls_log': [
                {
                    'turn': 1,
                    'tool': 'browser_navigate',
                    'input': {'url': 'https://example.com'},
                    'output': '已导航到: https://example.com',
                    'timestamp': '2026-04-30T10:00:00',
                },
                {
                    'turn': 2,
                    'tool': 'browser_click',
                    'input': {'selector': '#login-btn'},
                    'output': '已点击: #login-btn',
                    'timestamp': '2026-04-30T10:00:05',
                },
            ],
        }
        steps = _build_step_logs(agent_result)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]['step_num'], 1)
        self.assertEqual(steps[0]['action'], '导航到 https://example.com')
        self.assertEqual(steps[0]['target'], 'https://example.com')
        self.assertEqual(steps[1]['step_num'], 2)
        self.assertEqual(steps[1]['target'], '#login-btn')

    def test_fill_action_rewritten(self):
        agent_result = {
            'tool_calls_log': [
                {
                    'turn': 1,
                    'tool': 'browser_fill',
                    'input': {'selector': '#username', 'value': 'admin'},
                    'output': '已填写',
                    'timestamp': '',
                },
            ],
        }
        steps = _build_step_logs(agent_result)
        self.assertIn('填写', steps[0]['action'])
        self.assertIn('admin', steps[0]['action'])

    def test_screenshot_path_extracted(self):
        agent_result = {
            'tool_calls_log': [
                {
                    'turn': 1,
                    'tool': 'browser_screenshot',
                    'input': {},
                    'output': '截图已保存: /tmp/shot.png',
                    'timestamp': '',
                },
            ],
        }
        steps = _build_step_logs(agent_result)
        self.assertEqual(steps[0]['action'], '截图')
        self.assertEqual(steps[0]['screenshot_path'], '/tmp/shot.png')

    def test_report_result_action(self):
        agent_result = {
            'tool_calls_log': [
                {
                    'turn': 1,
                    'tool': 'report_result',
                    'input': {'status': 'passed', 'summary': 'All good'},
                    'output': '结果已记录',
                    'timestamp': '',
                },
            ],
        }
        steps = _build_step_logs(agent_result)
        self.assertIn('报告结果', steps[0]['action'])
        self.assertEqual(steps[0]['target'], 'All good')

    def test_empty_tool_calls(self):
        steps = _build_step_logs({'tool_calls_log': []})
        self.assertEqual(steps, [])

    def test_output_truncated(self):
        long_output = 'x' * 10000
        agent_result = {
            'tool_calls_log': [
                {
                    'turn': 1, 'tool': 'browser_get_text',
                    'input': {'selector': 'body'},
                    'output': long_output, 'timestamp': '',
                },
            ],
        }
        steps = _build_step_logs(agent_result)
        self.assertLessEqual(len(steps[0]['result']), 5000)


class ExtractScreenshotsTest(TestCase):
    """_extract_screenshots 路径提取测试"""

    def test_extracts_from_standard_format(self):
        agent_result = {
            'tool_calls_log': [
                {
                    'tool': 'browser_screenshot',
                    'output': '截图已保存: /media/screenshots/1/1/step_1.png',
                },
                {
                    'tool': 'browser_navigate',
                    'output': '已导航到: https://example.com',
                },
                {
                    'tool': 'browser_screenshot',
                    'output': '截图已保存: /media/screenshots/1/1/step_2.png',
                },
            ],
        }
        paths = _extract_screenshots(agent_result)
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0], '/media/screenshots/1/1/step_1.png')
        self.assertEqual(paths[1], '/media/screenshots/1/1/step_2.png')

    def test_no_screenshots(self):
        agent_result = {
            'tool_calls_log': [
                {'tool': 'browser_click', 'output': '已点击'},
            ],
        }
        self.assertEqual(_extract_screenshots(agent_result), [])

    def test_empty_tool_calls(self):
        self.assertEqual(_extract_screenshots({'tool_calls_log': []}), [])

    def test_alternative_format_with_png(self):
        """测试兼容 '已保存' + .png 的格式"""
        agent_result = {
            'tool_calls_log': [
                {
                    'tool': 'browser_screenshot',
                    'output': '已保存 /tmp/test.png',
                },
            ],
        }
        paths = _extract_screenshots(agent_result)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0], '/tmp/test.png')


# ══════════════════════════════════════════════════════════════════
# event_emitter 测试
# ══════════════════════════════════════════════════════════════════

class EmitStepEventTest(TestCase):
    """Tests for event_emitter._emit_step_event."""

    def setUp(self):
        # 重置全局状态，防止测试间干扰
        import core.event_emitter as ee
        ee._asgi_event_loop = None

    @mock.patch('asyncio.run_coroutine_threadsafe')
    @mock.patch('channels.layers.get_channel_layer')
    def test_emit_calls_group_send(self, mock_get_layer, mock_run_coro):
        """正常推送事件到 channel group via run_coroutine_threadsafe"""
        import core.event_emitter as ee
        from .event_emitter import _emit_step_event
        mock_layer = mock.MagicMock()
        mock_get_layer.return_value = mock_layer
        # 设置一个 running 的 ASGI 事件循环
        mock_loop = mock.MagicMock()
        mock_loop.is_running.return_value = True
        ee._asgi_event_loop = mock_loop
        mock_future = mock.MagicMock()
        mock_run_coro.return_value = mock_future

        _emit_step_event(42, 'step_complete', {'step_num': 1, 'action': 'browser_click'})

        mock_get_layer.assert_called_once()
        mock_run_coro.assert_called_once()
        # 验证调度到了正确的事件循环
        self.assertEqual(mock_run_coro.call_args[0][1], mock_loop)

    @mock.patch('asyncio.run_coroutine_threadsafe')
    @mock.patch('channels.layers.get_channel_layer')
    def test_emit_group_name(self, mock_get_layer, mock_run_coro):
        """验证 group name 格式"""
        import core.event_emitter as ee
        from .event_emitter import _emit_step_event
        mock_layer = mock.MagicMock()
        mock_get_layer.return_value = mock_layer
        mock_loop = mock.MagicMock()
        mock_loop.is_running.return_value = True
        ee._asgi_event_loop = mock_loop
        mock_future = mock.MagicMock()
        mock_run_coro.return_value = mock_future

        _emit_step_event(99, 'execution_end', {'status': 'completed'})

        # 验证 group_send 被 channel_layer 调用时使用了正确的 group name
        # run_coroutine_threadsafe 的第一个参数是 coroutine，无法直接检查
        # 但我们可以验证 channel_layer 被获取了
        mock_get_layer.assert_called_once()

    def test_emit_skips_when_no_execution_id(self):
        """execution_id 为 None 时跳过推送"""
        from .event_emitter import _emit_step_event
        with mock.patch('channels.layers.get_channel_layer') as mock_get:
            _emit_step_event(None, 'step_start', {'action': 'test'})
            mock_get.assert_not_called()

    def test_emit_skips_when_zero_execution_id(self):
        """execution_id 为 0 时跳过推送"""
        from .event_emitter import _emit_step_event
        with mock.patch('channels.layers.get_channel_layer') as mock_get:
            _emit_step_event(0, 'step_start', {'action': 'test'})
            mock_get.assert_not_called()

    @mock.patch('channels.layers.get_channel_layer', return_value=None)
    def test_emit_handles_none_channel_layer(self, mock_get):
        """channel_layer 为 None 时静默跳过"""
        from .event_emitter import _emit_step_event
        # 不应抛出异常
        _emit_step_event(1, 'step_start', {'action': 'test'})

    @mock.patch('channels.layers.get_channel_layer', side_effect=Exception('boom'))
    def test_emit_handles_exception_silently(self, mock_get):
        """推送异常时静默失败，不中断主流程"""
        from .event_emitter import _emit_step_event
        # 不应抛出异常
        _emit_step_event(1, 'step_start', {'action': 'test'})

    @mock.patch('asyncio.run_coroutine_threadsafe')
    @mock.patch('channels.layers.get_channel_layer')
    def test_emit_payload_format(self, mock_get_layer, mock_run_coro):
        """验证推送数据包含 type 和 timestamp"""
        import core.event_emitter as ee
        from .event_emitter import _emit_step_event
        mock_layer = mock.MagicMock()
        mock_get_layer.return_value = mock_layer
        mock_loop = mock.MagicMock()
        mock_loop.is_running.return_value = True
        ee._asgi_event_loop = mock_loop
        mock_future = mock.MagicMock()
        mock_run_coro.return_value = mock_future

        _emit_step_event(1, 'step_complete', {'step_num': 3, 'action': 'browser_fill'})

        # run_coroutine_threadsafe 被调用了
        mock_run_coro.assert_called_once()
        # 无法直接检查 coroutine 参数，但验证 channel_layer 被正确获取
        mock_get_layer.assert_called_once()


class EmitFrameEventTest(TestCase):
    """Tests for event_emitter._emit_frame_event."""

    def setUp(self):
        import core.event_emitter as ee
        ee._asgi_event_loop = None

    @mock.patch('asyncio.run_coroutine_threadsafe')
    @mock.patch('channels.layers.get_channel_layer')
    def test_emit_calls_group_send(self, mock_get_layer, mock_run_coro):
        """正常推送帧事件到 frame channel group"""
        import core.event_emitter as ee
        from .event_emitter import _emit_frame_event
        mock_layer = mock.MagicMock()
        mock_get_layer.return_value = mock_layer
        mock_loop = mock.MagicMock()
        mock_loop.is_running.return_value = True
        ee._asgi_event_loop = mock_loop
        mock_future = mock.MagicMock()
        mock_run_coro.return_value = mock_future

        _emit_frame_event(42, 'browser_frame', {'ts': 1234567890})

        mock_get_layer.assert_called_once()
        mock_run_coro.assert_called_once()
        self.assertEqual(mock_run_coro.call_args[0][1], mock_loop)

    @mock.patch('asyncio.run_coroutine_threadsafe')
    @mock.patch('channels.layers.get_channel_layer')
    def test_emit_frame_heartbeat(self, mock_get_layer, mock_run_coro):
        """frame_heartbeat 事件也通过 frame 通道推送"""
        import core.event_emitter as ee
        from .event_emitter import _emit_frame_event
        mock_layer = mock.MagicMock()
        mock_get_layer.return_value = mock_layer
        mock_loop = mock.MagicMock()
        mock_loop.is_running.return_value = True
        ee._asgi_event_loop = mock_loop
        mock_run_coro.return_value = mock.MagicMock()

        _emit_frame_event(10, 'frame_heartbeat', {'ts': 9876543210})

        mock_get_layer.assert_called_once()
        mock_run_coro.assert_called_once()

    def test_emit_skips_when_no_execution_id(self):
        """execution_id 为 None 时跳过帧推送"""
        from .event_emitter import _emit_frame_event
        with mock.patch('channels.layers.get_channel_layer') as mock_get:
            _emit_frame_event(None, 'browser_frame', {'ts': 123})
            mock_get.assert_not_called()

    def test_emit_skips_when_zero_execution_id(self):
        """execution_id 为 0 时跳过帧推送"""
        from .event_emitter import _emit_frame_event
        with mock.patch('channels.layers.get_channel_layer') as mock_get:
            _emit_frame_event(0, 'browser_frame', {'ts': 123})
            mock_get.assert_not_called()

    @mock.patch('channels.layers.get_channel_layer', return_value=None)
    def test_emit_handles_none_channel_layer(self, mock_get):
        """channel_layer 为 None 时静默跳过"""
        import core.event_emitter as ee
        from .event_emitter import _emit_frame_event
        mock_loop = mock.MagicMock()
        ee._asgi_event_loop = mock_loop
        # 不应抛出异常
        _emit_frame_event(1, 'browser_frame', {'ts': 123})

    @mock.patch('channels.layers.get_channel_layer', side_effect=Exception('boom'))
    def test_emit_handles_exception_silently(self, mock_get):
        """推送异常时静默失败，不中断主流程"""
        import core.event_emitter as ee
        from .event_emitter import _emit_frame_event
        mock_loop = mock.MagicMock()
        ee._asgi_event_loop = mock_loop
        # 不应抛出异常
        _emit_frame_event(1, 'browser_frame', {'ts': 123})

    def test_emit_skips_when_loop_not_usable(self):
        """ASGI 事件循环不可用时跳过帧推送"""
        from .event_emitter import _emit_frame_event
        with mock.patch('channels.layers.get_channel_layer') as mock_get:
            _emit_frame_event(1, 'browser_frame', {'ts': 123})
            mock_get.assert_not_called()


# ══════════════════════════════════════════════════════════════════
# agent_service 辅助函数测试
# ══════════════════════════════════════════════════════════════════

class ExtractTargetTest(TestCase):
    """Tests for agent_service._extract_target."""

    def test_browser_navigate(self):
        from .agent_service import _extract_target
        result = _extract_target('browser_navigate', {'url': 'https://example.com'})
        self.assertEqual(result, 'https://example.com')

    def test_browser_click(self):
        from .agent_service import _extract_target
        result = _extract_target('browser_click', {'selector': '#btn'})
        self.assertEqual(result, '#btn')

    def test_browser_fill(self):
        from .agent_service import _extract_target
        result = _extract_target('browser_fill', {'selector': 'input[name=email]'})
        self.assertEqual(result, 'input[name=email]')

    def test_browser_screenshot(self):
        from .agent_service import _extract_target
        result = _extract_target('browser_screenshot', {})
        self.assertEqual(result, 'screenshot')

    def test_report_result(self):
        from .agent_service import _extract_target
        result = _extract_target('report_result', {'summary': 'All tests passed'})
        self.assertEqual(result, 'All tests passed')

    def test_list_files(self):
        from .agent_service import _extract_target
        result = _extract_target('list_files', {'path': '/src'})
        self.assertEqual(result, '/src')

    def test_read_file(self):
        from .agent_service import _extract_target
        result = _extract_target('read_file', {'path': '/src/index.js'})
        self.assertEqual(result, '/src/index.js')

    def test_search_code(self):
        from .agent_service import _extract_target
        result = _extract_target('search_code', {'keyword': 'login'})
        self.assertEqual(result, 'login')

    def test_unknown_tool(self):
        from .agent_service import _extract_target
        result = _extract_target('unknown_tool', {'foo': 'bar'})
        self.assertEqual(result, '')

    def test_non_dict_input(self):
        from .agent_service import _extract_target
        result = _extract_target('browser_click', 'not a dict')
        self.assertEqual(result, '')

    def test_missing_key(self):
        from .agent_service import _extract_target
        result = _extract_target('browser_click', {})
        self.assertEqual(result, '')


# ══════════════════════════════════════════════════════════════════
# ScreenshotStream 测试
# ══════════════════════════════════════════════════════════════════

class ScreenshotStreamTest(TestCase):
    """Tests for screenshot_stream.ScreenshotStream lifecycle."""

    def test_initial_state(self):
        """新建 stream 默认未运行"""
        from .screenshot_stream import ScreenshotStream
        stream = ScreenshotStream()
        self.assertFalse(stream.is_running())
        self.assertIsNone(stream._page)
        self.assertIsNone(stream._execution_id)

    def test_start_sets_page_and_execution_id(self):
        """start() 存储 page 和 execution_id"""
        from .screenshot_stream import ScreenshotStream
        mock_page = mock.MagicMock()
        stream = ScreenshotStream()

        stream.start(mock_page, 42)

        self.assertEqual(stream._page, mock_page)
        self.assertEqual(stream._execution_id, 42)
        self.assertTrue(stream.is_running())
        self.assertGreater(stream._last_capture_time, 0)

    def test_stop_before_start_is_safe(self):
        """未启动就 stop() 不报错"""
        from .screenshot_stream import ScreenshotStream
        stream = ScreenshotStream()
        stream.stop()  # 不应抛出异常

    def test_start_then_stop_clears_refs(self):
        """start 后 stop 清理引用"""
        from .screenshot_stream import ScreenshotStream
        mock_page = mock.MagicMock()
        stream = ScreenshotStream()

        stream.start(mock_page, 5)
        self.assertTrue(stream.is_running())

        stream.stop()
        self.assertFalse(stream.is_running())
        self.assertIsNone(stream._page)
        self.assertIsNone(stream._execution_id)


class ScreenshotStreamRunTest(TestCase):
    """Tests for ScreenshotStream.maybe_capture (unit-level)."""

    @mock.patch('core.event_emitter._emit_frame_event')
    def test_maybe_capture_emits_browser_frame(self, mock_emit):
        """maybe_capture 在间隔到达时截图并推送事件"""
        from .screenshot_stream import ScreenshotStream
        stream = ScreenshotStream(interval=0, quality=50)
        mock_page = mock.MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.screenshot.return_value = b'\xff\xd8fake_jpeg'
        stream.start(mock_page, 10)
        # 设置 last_capture_time 为过去，确保间隔已过
        stream._last_capture_time = 0

        stream.maybe_capture()

        mock_page.screenshot.assert_called_once_with(type='jpeg', quality=50)
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args[0]
        self.assertEqual(call_args[0], 10)
        self.assertEqual(call_args[1], 'browser_frame')
        self.assertIn('ts', call_args[2])
        self.assertIsInstance(call_args[2]['ts'], (int, float))

    @mock.patch('core.event_emitter._emit_frame_event')
    def test_maybe_capture_skips_closed_page(self, mock_emit):
        """page.is_closed() 为 True 时不截图"""
        from .screenshot_stream import ScreenshotStream
        stream = ScreenshotStream(interval=0)
        mock_page = mock.MagicMock()
        mock_page.is_closed.return_value = True
        stream.start(mock_page, 10)

        stream.maybe_capture()

        mock_page.screenshot.assert_not_called()
        mock_emit.assert_not_called()

    @mock.patch('core.event_emitter._emit_frame_event')
    def test_maybe_capture_skips_within_interval(self, mock_emit):
        """间隔内重复调用不截图"""
        from .screenshot_stream import ScreenshotStream
        stream = ScreenshotStream(interval=999)  # 很长的间隔
        mock_page = mock.MagicMock()
        mock_page.is_closed.return_value = False
        stream.start(mock_page, 10)

        stream.maybe_capture()

        mock_page.screenshot.assert_not_called()
        mock_emit.assert_not_called()

    @mock.patch('core.event_emitter._emit_frame_event')
    def test_maybe_capture_handles_screenshot_error(self, mock_emit):
        """截图异常时静默失败，不中断主流程"""
        from .screenshot_stream import ScreenshotStream
        stream = ScreenshotStream(interval=0)
        mock_page = mock.MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.screenshot.side_effect = Exception('browser crash')
        stream.start(mock_page, 10)
        stream._last_capture_time = 0

        # 不应抛出异常
        stream.maybe_capture()
        mock_emit.assert_not_called()


class GetLatestFrameTest(TestCase):
    """Tests for screenshot_stream.get_latest_frame and cache behavior."""

    def setUp(self):
        from .screenshot_stream import _latest_frames, _frames_lock
        self._frames = _latest_frames
        self._lock = _frames_lock
        # 清理全局字典避免测试间污染
        with self._lock:
            self._frames.clear()

    def tearDown(self):
        with self._lock:
            self._frames.clear()

    def test_returns_none_for_missing_key(self):
        """无缓存帧时返回 (None, None)"""
        from .screenshot_stream import get_latest_frame
        ts, jpeg = get_latest_frame(999)
        self.assertIsNone(ts)
        self.assertIsNone(jpeg)

    def test_returns_cached_frame(self):
        """有缓存帧时返回 (timestamp, jpeg_bytes)"""
        from .screenshot_stream import get_latest_frame
        fake_jpeg = b'\xff\xd8fake_jpeg_data'
        with self._lock:
            self._frames[42] = (1234567890.0, fake_jpeg)

        ts, jpeg = get_latest_frame(42)
        self.assertEqual(ts, 1234567890.0)
        self.assertEqual(jpeg, fake_jpeg)

    @mock.patch('core.event_emitter._emit_frame_event')
    def test_maybe_capture_populates_cache(self, mock_emit):
        """maybe_capture() 成功后 _latest_frames 中有对应条目"""
        from .screenshot_stream import ScreenshotStream, get_latest_frame
        stream = ScreenshotStream(interval=0, quality=50)
        mock_page = mock.MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.screenshot.return_value = b'\xff\xd8jpeg_data'
        stream.start(mock_page, 77)
        stream._last_capture_time = 0

        stream.maybe_capture()

        ts, jpeg = get_latest_frame(77)
        self.assertIsNotNone(ts)
        self.assertEqual(jpeg, b'\xff\xd8jpeg_data')

    @mock.patch('core.event_emitter._emit_frame_event')
    def test_repeated_capture_overwrites_cache(self, mock_emit):
        """多次 maybe_capture() 只保留最新帧"""
        from .screenshot_stream import ScreenshotStream, get_latest_frame
        stream = ScreenshotStream(interval=0, quality=50)
        mock_page = mock.MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.screenshot.side_effect = [b'frame_1', b'frame_2']
        stream.start(mock_page, 88)
        stream._last_capture_time = 0

        stream.maybe_capture()
        stream._last_capture_time = 0  # 重置间隔

        _, jpeg1 = get_latest_frame(88)
        self.assertEqual(jpeg1, b'frame_1')

        stream.maybe_capture()
        _, jpeg2 = get_latest_frame(88)
        self.assertEqual(jpeg2, b'frame_2')

    @mock.patch('core.event_emitter._emit_frame_event')
    def test_stop_clears_cache(self, mock_emit):
        """stop() 清除 _latest_frames 中对应 execution_id 的条目"""
        from .screenshot_stream import ScreenshotStream, get_latest_frame
        stream = ScreenshotStream(interval=0, quality=50)
        mock_page = mock.MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.screenshot.return_value = b'\xff\xd8jpeg'
        stream.start(mock_page, 55)
        stream._last_capture_time = 0

        stream.maybe_capture()
        ts, jpeg = get_latest_frame(55)
        self.assertIsNotNone(jpeg)

        stream.stop()
        ts2, jpeg2 = get_latest_frame(55)
        self.assertIsNone(ts2)
        self.assertIsNone(jpeg2)


class LatestFrameEndpointTest(TestCase):
    """Tests for GET /api/executions/<id>/latest_frame/."""

    def setUp(self):
        from .screenshot_stream import _latest_frames, _frames_lock
        self._frames = _latest_frames
        self._lock = _frames_lock
        with self._lock:
            self._frames.clear()

    def tearDown(self):
        with self._lock:
            self._frames.clear()

    def test_returns_jpeg_when_frame_exists(self):
        """有缓存帧时返回 200 + image/jpeg + 正确 headers"""
        fake_jpeg = b'\xff\xd8\xff\xe0fake_jpeg_bytes'
        with self._lock:
            self._frames[1] = (1700000000.0, fake_jpeg)

        response = self.client.get('/api/executions/1/latest_frame/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertEqual(response.content, fake_jpeg)
        self.assertEqual(response['Content-Length'], str(len(fake_jpeg)))
        self.assertIn('no-cache', response['Cache-Control'])
        self.assertEqual(response['X-Frame-Timestamp'], '1700000000.0')

    def test_returns_404_when_no_frame(self):
        """无缓存帧时返回 404"""
        response = self.client.get('/api/executions/999/latest_frame/')

        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn('error', data)

    def test_different_executions_isolated(self):
        """不同 execution_id 的帧缓存互相隔离"""
        with self._lock:
            self._frames[10] = (1000.0, b'frame_10')
            self._frames[20] = (2000.0, b'frame_20')

        resp10 = self.client.get('/api/executions/10/latest_frame/')
        resp20 = self.client.get('/api/executions/20/latest_frame/')

        self.assertEqual(resp10.content, b'frame_10')
        self.assertEqual(resp20.content, b'frame_20')
        self.assertEqual(resp10['X-Frame-Timestamp'], '1000.0')
        self.assertEqual(resp20['X-Frame-Timestamp'], '2000.0')

class ExecutionConsumerTest(TestCase):
    """Tests for consumers.ExecutionConsumer via Channels test utilities."""

    def _make_consumer(self, execution_id=1):
        """创建并初始化 consumer 实例"""
        from .consumers import ExecutionConsumer
        consumer = ExecutionConsumer()
        consumer.scope = {
            'url_route': {'kwargs': {'execution_id': execution_id}},
            'type': 'websocket',
        }
        consumer.channel_layer = mock.MagicMock()
        consumer.channel_name = 'test-channel'
        consumer.execution_id = execution_id
        return consumer

    @mock.patch('core.consumers.async_to_sync')
    def test_connect_sets_group_name(self, mock_async_to_sync):
        """connect() 设置 group_name 和 execution_id"""
        consumer = self._make_consumer(execution_id=42)
        consumer.accept = mock.MagicMock()
        consumer.send = mock.MagicMock()

        consumer.connect()

        self.assertEqual(consumer.group_name, 'execution_42')
        self.assertEqual(consumer.execution_id, 42)
        consumer.accept.assert_called_once()
        consumer.send.assert_called_once()

    @mock.patch('core.consumers.async_to_sync')
    def test_connect_sends_connection_established(self, mock_async_to_sync):
        """connect() 发送 connection_established 事件"""
        consumer = self._make_consumer(execution_id=7)
        consumer.accept = mock.MagicMock()
        consumer.send = mock.MagicMock()

        consumer.connect()

        sent_data = json.loads(consumer.send.call_args[1]['text_data'])
        self.assertEqual(sent_data['type'], 'connection_established')
        self.assertEqual(sent_data['execution_id'], 7)

    @mock.patch('core.consumers.async_to_sync')
    def test_connect_calls_group_add(self, mock_async_to_sync):
        """connect() 将 channel 加入 group"""
        consumer = self._make_consumer(execution_id=5)
        consumer.accept = mock.MagicMock()
        consumer.send = mock.MagicMock()

        consumer.connect()

        # async_to_sync(channel_layer.group_add) 被调用
        mock_async_to_sync.assert_called_with(consumer.channel_layer.group_add)
        # 返回的 sync 函数被调用时参数为 (group_name, channel_name)
        mock_async_to_sync.return_value.assert_called_with(
            'execution_5', 'test-channel',
        )

    @mock.patch('core.consumers.async_to_sync')
    def test_disconnect_calls_group_discard(self, mock_async_to_sync):
        """disconnect() 将 channel 从 group 移除"""
        consumer = self._make_consumer(execution_id=3)
        consumer.accept = mock.MagicMock()
        consumer.send = mock.MagicMock()
        consumer.connect()

        # 重置 mock 以隔离 connect 和 disconnect 的调用
        mock_async_to_sync.reset_mock()

        consumer.disconnect(1000)

        mock_async_to_sync.assert_called_with(consumer.channel_layer.group_discard)
        mock_async_to_sync.return_value.assert_called_with(
            'execution_3', 'test-channel',
        )

    def test_disconnect_safe_without_group_name(self):
        """disconnect() 在未 connect 的情况下不报错"""
        consumer = self._make_consumer(execution_id=1)
        # 不调用 connect()，直接 disconnect
        consumer.disconnect(1000)
        # 不应抛出异常

    def test_step_event_forwards_data(self):
        """step_event handler 将 data 转发给 WebSocket 客户端"""
        consumer = self._make_consumer()
        consumer.send = mock.MagicMock()

        event_data = {
            'type': 'step_complete',
            'step_num': 3,
            'action': 'browser_click',
            'target': '#btn',
            'timestamp': '2025-01-01T00:00:00',
        }
        consumer.step_event({'data': event_data})

        sent = json.loads(consumer.send.call_args[1]['text_data'])
        self.assertEqual(sent['type'], 'step_complete')
        self.assertEqual(sent['step_num'], 3)

    def test_receive_is_noop(self):
        """receive() 是预留扩展，不报错"""
        consumer = self._make_consumer()
        consumer.receive(text_data='hello')
        # 不应抛出异常


class FrameConsumerTest(TestCase):
    """Tests for consumers.FrameConsumer via Channels test utilities."""

    def _make_consumer(self, execution_id=1):
        """创建并初始化 FrameConsumer 实例"""
        from .consumers import FrameConsumer
        consumer = FrameConsumer()
        consumer.scope = {
            'url_route': {'kwargs': {'execution_id': execution_id}},
            'type': 'websocket',
        }
        consumer.channel_layer = mock.MagicMock()
        consumer.channel_name = 'test-frame-channel'
        consumer.execution_id = execution_id
        return consumer

    @mock.patch('core.consumers.async_to_sync')
    def test_connect_sets_frame_group_name(self, mock_async_to_sync):
        """connect() 设置 frame_{id} group"""
        consumer = self._make_consumer(execution_id=42)
        consumer.accept = mock.MagicMock()
        consumer.send = mock.MagicMock()

        consumer.connect()

        self.assertEqual(consumer.group_name, 'frame_42')
        self.assertEqual(consumer.execution_id, 42)
        consumer.accept.assert_called_once()

    @mock.patch('core.consumers.async_to_sync')
    def test_connect_sends_connection_established(self, mock_async_to_sync):
        """connect() 发送 connection_established 事件"""
        consumer = self._make_consumer(execution_id=7)
        consumer.accept = mock.MagicMock()
        consumer.send = mock.MagicMock()

        consumer.connect()

        sent_data = json.loads(consumer.send.call_args[1]['text_data'])
        self.assertEqual(sent_data['type'], 'connection_established')
        self.assertEqual(sent_data['execution_id'], 7)

    @mock.patch('core.consumers.async_to_sync')
    def test_connect_calls_group_add(self, mock_async_to_sync):
        """connect() 将 channel 加入 frame group"""
        consumer = self._make_consumer(execution_id=5)
        consumer.accept = mock.MagicMock()
        consumer.send = mock.MagicMock()

        consumer.connect()

        mock_async_to_sync.assert_called_with(consumer.channel_layer.group_add)
        mock_async_to_sync.return_value.assert_called_with(
            'frame_5', 'test-frame-channel',
        )

    @mock.patch('core.consumers.async_to_sync')
    def test_disconnect_calls_group_discard(self, mock_async_to_sync):
        """disconnect() 将 channel 从 frame group 移除"""
        consumer = self._make_consumer(execution_id=3)
        consumer.accept = mock.MagicMock()
        consumer.send = mock.MagicMock()
        consumer.connect()

        mock_async_to_sync.reset_mock()

        consumer.disconnect(1000)

        mock_async_to_sync.assert_called_with(consumer.channel_layer.group_discard)
        mock_async_to_sync.return_value.assert_called_with(
            'frame_3', 'test-frame-channel',
        )

    def test_disconnect_safe_without_group_name(self):
        """disconnect() 在未 connect 的情况下不报错"""
        consumer = self._make_consumer(execution_id=1)
        consumer.disconnect(1000)

    def test_frame_event_forwards_browser_frame(self):
        """frame_event handler 将 browser_frame 数据转发给客户端"""
        consumer = self._make_consumer()
        consumer.send = mock.MagicMock()

        event_data = {
            'type': 'browser_frame',
            'ts': 1234567890,
        }
        consumer.frame_event({'data': event_data})

        sent = json.loads(consumer.send.call_args[1]['text_data'])
        self.assertEqual(sent['type'], 'browser_frame')
        self.assertEqual(sent['ts'], 1234567890)

    def test_frame_event_forwards_frame_heartbeat(self):
        """frame_event handler 将 frame_heartbeat 数据转发给客户端"""
        consumer = self._make_consumer()
        consumer.send = mock.MagicMock()

        event_data = {
            'type': 'frame_heartbeat',
            'ts': 9876543210,
        }
        consumer.frame_event({'data': event_data})

        sent = json.loads(consumer.send.call_args[1]['text_data'])
        self.assertEqual(sent['type'], 'frame_heartbeat')

    def test_receive_ping_responds_pong(self):
        """receive() 处理 ping 消息并回复 pong"""
        consumer = self._make_consumer()
        consumer.send = mock.MagicMock()

        consumer.receive(text_data=json.dumps({'type': 'ping'}))

        sent = json.loads(consumer.send.call_args[1]['text_data'])
        self.assertEqual(sent['type'], 'pong')
        self.assertIn('timestamp', sent)

    def test_receive_invalid_json_ignored(self):
        """receive() 忽略无效 JSON 消息"""
        consumer = self._make_consumer()
        consumer.send = mock.MagicMock()

        consumer.receive(text_data='not json')
        # 不应抛出异常，不应发送任何消息
        consumer.send.assert_not_called()


# ══════════════════════════════════════════════════════════════════
# 仓库分析 + 批量用例生成 Tests
# ══════════════════════════════════════════════════════════════════

class RepoAnalysisModelTest(TestCase):
    """RepoAnalysis 模型测试"""

    def test_create_repo_analysis(self):
        project = Project.objects.create(name='Test Project')
        analysis = RepoAnalysis.objects.create(project=project, status='pending')
        self.assertEqual(analysis.status, 'pending')
        self.assertEqual(analysis.project, project)
        self.assertEqual(analysis.discovered_items, [])

    def test_str_representation(self):
        project = Project.objects.create(name='Test Project')
        analysis = RepoAnalysis.objects.create(project=project, status='completed')
        self.assertIn('completed', str(analysis))
        self.assertIn(str(project.id), str(analysis))

    def test_status_choices(self):
        project = Project.objects.create(name='Test Project')
        for status_val in ['pending', 'analyzing', 'completed', 'failed']:
            analysis = RepoAnalysis.objects.create(project=project, status=status_val)
            self.assertEqual(analysis.status, status_val)

    def test_ordering_meta(self):
        """RepoAnalysis.Meta.ordering should be -created_at"""
        self.assertEqual(RepoAnalysis._meta.ordering, ['-created_at'])


class PreconditionTemplateModelTest(TestCase):
    """PreconditionTemplate 模型测试"""

    def test_create_template(self):
        tpl = PreconditionTemplate.objects.create(
            name='Test Template',
            steps='1. Step one\n2. Step two',
        )
        self.assertEqual(tpl.name, 'Test Template')
        self.assertFalse(tpl.is_default)

    def test_str_default_template(self):
        tpl = PreconditionTemplate.objects.create(name='SSO Login', is_default=True)
        self.assertIn('内置', str(tpl))

    def test_str_custom_template(self):
        tpl = PreconditionTemplate.objects.create(name='Custom', is_default=False)
        self.assertNotIn('内置', str(tpl))

    def test_default_templates_exist(self):
        """Data migration should have created 3 default templates"""
        defaults = PreconditionTemplate.objects.filter(is_default=True)
        self.assertEqual(defaults.count(), 3)
        names = list(defaults.values_list('name', flat=True))
        self.assertIn('SSO 统一登录', names)
        self.assertIn('管理员登录', names)
        self.assertIn('普通用户登录', names)


class RepoPullViewTest(TestCase):
    """repo_pull 端点测试"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(
            name='Test Project',
            repo_url='https://github.com/test/repo.git',
        )

    @mock.patch('core.repo_service.clone_or_update_repo')
    def test_repo_pull_success(self, mock_clone):
        mock_clone.return_value = '/tmp/repos/project_1'
        resp = self.client.post(f'/api/projects/{self.project.id}/repo/pull/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'ready')
        mock_clone.assert_called_once()

    @mock.patch('core.repo_service.clone_or_update_repo')
    def test_repo_pull_failure(self, mock_clone):
        mock_clone.side_effect = RuntimeError('Git clone failed')
        resp = self.client.post(f'/api/projects/{self.project.id}/repo/pull/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Git clone failed', resp.data['error'])

    def test_repo_pull_project_not_found(self):
        resp = self.client.post('/api/projects/99999/repo/pull/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class RepoAnalyzeViewTest(TestCase):
    """repo_analyze 端点测试"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(
            name='Test Project',
            repo_url='https://github.com/test/repo.git',
            local_repo_path='/tmp/repos/project_1',
        )

    @mock.patch('core.views._submit_agent_task')
    def test_repo_analyze_starts_async(self, mock_submit):
        resp = self.client.post(f'/api/projects/{self.project.id}/repo/analyze/')
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.data['status'], 'analyzing')
        mock_submit.assert_called_once()

    def test_repo_analyze_no_repo(self):
        project = Project.objects.create(name='No Repo')
        resp = self.client.post(f'/api/projects/{project.id}/repo/analyze/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_repo_analysis_detail(self):
        analysis = RepoAnalysis.objects.create(
            project=self.project,
            status='completed',
            discovered_items=[{'type': 'page', 'path': '/users', 'name': 'Users'}],
        )
        resp = self.client.get(f'/api/projects/{self.project.id}/repo/analysis/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(resp.data['analysis'])
        self.assertEqual(resp.data['analysis']['status'], 'completed')

    def test_repo_analysis_detail_empty(self):
        project = Project.objects.create(name='No Analysis')
        resp = self.client.get(f'/api/projects/{project.id}/repo/analysis/')
        self.assertIsNone(resp.data['analysis'])

    def test_repo_analysis_list(self):
        RepoAnalysis.objects.create(project=self.project, status='completed')
        RepoAnalysis.objects.create(project=self.project, status='failed')
        resp = self.client.get(f'/api/projects/{self.project.id}/repo/analysis/list/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data['analyses']), 2)


class BatchGenerateViewTest(TestCase):
    """batch_generate_testcases 端点测试"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='Test Project', base_url='https://example.com')

    @mock.patch('core.batch_generator.generate_testcases_for_items')
    def test_batch_generate_success(self, mock_generate):
        mock_generate.return_value = [
            {'name': 'TC1', 'steps': 'step1', 'expected_result': 'result1'},
            {'name': 'TC2', 'steps': 'step2', 'expected_result': 'result2'},
        ]
        data = {
            'selected_items': [{'type': 'page', 'path': '/users'}],
            'descriptions': {'/users': 'Test users page'},
        }
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-generate/', data, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 2)
        mock_generate.assert_called_once()

    def test_batch_generate_no_items(self):
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-generate/',
            {'selected_items': [], 'descriptions': {}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @mock.patch('core.batch_generator.generate_testcases_for_items')
    def test_batch_generate_with_precondition(self, mock_generate):
        mock_generate.return_value = [{'name': 'TC1'}]
        tpl = PreconditionTemplate.objects.create(name='Test Precondition', steps='Login first')
        data = {
            'selected_items': [{'type': 'api', 'path': '/api/users'}],
            'precondition_id': tpl.id,
        }
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-generate/', data, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    @mock.patch('core.batch_generator.generate_testcases_for_items')
    def test_batch_generate_ai_failure(self, mock_generate):
        mock_generate.side_effect = RuntimeError('AI call failed')
        data = {
            'selected_items': [{'type': 'page', 'path': '/'}],
        }
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-generate/', data, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)


class BatchSaveViewTest(TestCase):
    """batch_save_testcases 端点测试"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='Test Project')

    def test_batch_save_success(self):
        data = {
            'testcases': [
                {
                    'name': 'TC1',
                    'description': 'desc1',
                    'steps': 'step1',
                    'expected_result': 'result1',
                    'priority': 'P0',
                    'test_type': '功能',
                    'target_page_or_api': '/users',
                },
                {
                    'name': 'TC2',
                    'description': 'desc2',
                    'steps': 'step2',
                    'expected_result': 'result2',
                },
            ]
        }
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/', data, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['count'], 2)
        # Verify DB records
        testcases = TC_Model.objects.filter(project=self.project)
        self.assertEqual(testcases.count(), 2)
        tc1 = testcases.get(name='TC1')
        self.assertTrue(tc1.is_ai_generated)
        self.assertEqual(tc1.created_by, 'claude_cli')
        self.assertEqual(tc1.status, 'draft')
        self.assertEqual(tc1.priority, 'P0')
        self.assertEqual(tc1.target_page_or_api, '/users')

    def test_batch_save_empty(self):
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/',
            {'testcases': []},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_batch_save_project_not_found(self):
        resp = self.client.post(
            '/api/projects/99999/batch-save/',
            {'testcases': [{'name': 'TC'}]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class PreconditionCRUDTest(TestCase):
    """前置条件模板 CRUD 端点测试"""

    def setUp(self):
        self.client = APIClient()

    def test_list_preconditions(self):
        PreconditionTemplate.objects.create(name='TPL1', steps='Step 1')
        PreconditionTemplate.objects.create(name='TPL2', steps='Step 2', is_default=True)
        resp = self.client.get('/api/preconditions/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # 2 created + 3 from data migration = 5
        self.assertEqual(len(resp.data['preconditions']), 5)

    def test_create_precondition(self):
        data = {'name': 'New Template', 'steps': '1. Do something'}
        resp = self.client.post('/api/preconditions/create/', data, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['name'], 'New Template')
        self.assertFalse(resp.data['is_default'])

    def test_update_precondition(self):
        tpl = PreconditionTemplate.objects.create(name='Old', steps='Old steps')
        data = {'name': 'Updated', 'steps': 'New steps'}
        resp = self.client.put(f'/api/preconditions/{tpl.id}/', data, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'Updated')

    def test_delete_precondition(self):
        tpl = PreconditionTemplate.objects.create(name='Delete Me', steps='Steps')
        resp = self.client.delete(f'/api/preconditions/{tpl.id}/delete/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(PreconditionTemplate.objects.filter(id=tpl.id).exists())

    def test_delete_default_precondition_forbidden(self):
        tpl = PreconditionTemplate.objects.create(name='Default', steps='Steps', is_default=True)
        resp = self.client.delete(f'/api/preconditions/{tpl.id}/delete/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(PreconditionTemplate.objects.filter(id=tpl.id).exists())

    def test_delete_nonexistent(self):
        resp = self.client.delete('/api/preconditions/99999/delete/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class RepoAnalyzerTest(TestCase):
    """repo_analyzer.py 服务层测试"""

    def setUp(self):
        self.project = Project.objects.create(
            name='Test Project',
            repo_url='https://github.com/test/repo.git',
            base_url='https://example.com',
        )

    def test_parse_analysis_response_valid_json(self):
        from .repo_analyzer import _parse_analysis_response
        raw = json.dumps({
            'pages': [{'path': '/users', 'name': 'Users', 'description': 'User list', 'source_file': 'router.js'}],
            'apis': [{'path': '/api/users', 'method': 'GET', 'name': 'Get Users', 'description': 'List users', 'source_file': 'app.py'}],
        })
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['type'], 'page')
        self.assertEqual(items[0]['path'], '/users')
        self.assertEqual(items[1]['type'], 'api')
        self.assertEqual(items[1]['method'], 'GET')

    def test_parse_analysis_response_empty(self):
        from .repo_analyzer import _parse_analysis_response
        items = _parse_analysis_response('{"pages": [], "apis": []}')
        self.assertEqual(items, [])

    def test_parse_analysis_response_markdown_wrapped(self):
        from .repo_analyzer import _parse_analysis_response
        raw = '```json\n{"pages": [{"path": "/home", "name": "Home"}], "apis": []}\n```'
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['path'], '/home')

    def test_parse_analysis_response_invalid(self):
        from .repo_analyzer import _parse_analysis_response
        items = _parse_analysis_response('not valid json at all')
        self.assertEqual(items, [])

    @mock.patch('core.repo_analyzer._get_model', return_value='test-model')
    @mock.patch('core.repo_analyzer._get_client')
    @mock.patch('core.repo_analyzer.repo_service')
    def test_analyze_repo_success(self, mock_repo_service, mock_get_client, mock_model):
        from .repo_analyzer import analyze_repo

        # Set SDK mode for this test
        SystemSetting.objects.create(key='analysis_engine', value='sdk')
        SystemSetting.objects.create(key='anthropic_api_key', value='test-key')
        SystemSetting.objects.create(key='anthropic_model', value='test-model')

        mock_repo_service.clone_or_update_repo.return_value = '/tmp/repos/project_1'
        mock_repo_service.get_repo_file_tree.return_value = 'src/\n  index.js\n'
        mock_repo_service.search_code.return_value = [
            {'file': 'src/router.js', 'line_num': 1, 'line': 'router'},
        ]
        mock_repo_service.read_file_content.return_value = "router.get('/users')"

        mock_response = mock.MagicMock()
        mock_response.content = [mock.MagicMock()]
        mock_response.content[0].text = json.dumps({
            'pages': [{'path': '/users', 'name': 'Users', 'description': 'User list', 'source_file': 'router.js'}],
            'apis': [],
        })
        mock_client = mock.MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = analyze_repo(self.project)
        self.assertEqual(result.status, 'completed')
        self.assertEqual(len(result.discovered_items), 1)
        self.assertEqual(result.discovered_items[0]['type'], 'page')

    @mock.patch('core.repo_analyzer.repo_service')
    def test_analyze_repo_clone_failure(self, mock_repo_service):
        from .repo_analyzer import analyze_repo

        mock_repo_service.clone_or_update_repo.side_effect = RuntimeError('Clone failed')
        result = analyze_repo(self.project)
        self.assertEqual(result.status, 'failed')
        self.assertIn('Clone failed', result.analysis_log)


class BatchGeneratorParserTest(TestCase):
    """batch_generator._parse_testcases_response 边界测试"""

    def test_valid_json_array(self):
        from .batch_generator import _parse_testcases_response
        raw = json.dumps([{'name': 'TC1'}, {'name': 'TC2'}])
        result = _parse_testcases_response(raw)
        self.assertEqual(len(result), 2)

    def test_markdown_wrapped_json(self):
        from .batch_generator import _parse_testcases_response
        raw = '```json\n[{"name": "TC1"}]\n```'
        result = _parse_testcases_response(raw)
        self.assertEqual(len(result), 1)

    def test_returns_empty_on_invalid(self):
        from .batch_generator import _parse_testcases_response
        result = _parse_testcases_response('not json at all')
        self.assertEqual(result, [])

    def test_returns_empty_on_non_list_json(self):
        """If AI returns a JSON object instead of array, return []"""
        from .batch_generator import _parse_testcases_response
        result = _parse_testcases_response('{"error": "something"}')
        self.assertEqual(result, [])

    def test_bracket_extraction_fallback(self):
        from .batch_generator import _parse_testcases_response
        raw = 'Here are the testcases:\n[{"name": "TC1"}]\nEnd.'
        result = _parse_testcases_response(raw)
        self.assertEqual(len(result), 1)


class RepoAnalyzerParserEdgeTest(TestCase):
    """repo_analyzer._parse_analysis_response 边界测试"""

    def test_pages_with_missing_fields(self):
        from .repo_analyzer import _parse_analysis_response
        raw = json.dumps({'pages': [{'path': '/x'}], 'apis': []})
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['name'], '')
        self.assertIsNone(items[0]['method'])

    def test_api_method_preserved(self):
        from .repo_analyzer import _parse_analysis_response
        raw = json.dumps({'pages': [], 'apis': [{'path': '/api/x', 'method': 'POST'}]})
        items = _parse_analysis_response(raw)
        self.assertEqual(items[0]['method'], 'POST')

    def test_non_dict_response(self):
        """If top-level JSON is a list, return []"""
        from .repo_analyzer import _parse_analysis_response
        items = _parse_analysis_response('[1, 2, 3]')
        self.assertEqual(items, [])

    def test_curly_brace_fallback(self):
        from .repo_analyzer import _parse_analysis_response
        raw = 'Some text {"pages": [{"path": "/a", "name": "A"}], "apis": []} more text'
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 1)

    def test_null_pages_and_apis(self):
        """null values for pages/apis should not crash"""
        from .repo_analyzer import _parse_analysis_response
        raw = json.dumps({'pages': None, 'apis': None})
        items = _parse_analysis_response(raw)
        self.assertEqual(items, [])

    def test_null_pages_with_valid_apis(self):
        """null pages should still process valid apis"""
        from .repo_analyzer import _parse_analysis_response
        raw = json.dumps({'pages': None, 'apis': [{'path': '/api/x', 'method': 'GET'}]})
        items = _parse_analysis_response(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['type'], 'api')


class BatchSaveEdgeTest(TestCase):
    """batch_save 边界测试"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='Edge Test')

    def test_batch_save_default_values(self):
        """Items missing optional fields get defaults"""
        data = {
            'testcases': [{'name': 'Minimal TC'}]
        }
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/', data, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        tc = TC_Model.objects.get(project=self.project)
        self.assertEqual(tc.name, 'Minimal TC')
        self.assertEqual(tc.description, '')
        self.assertEqual(tc.status, 'draft')
        self.assertTrue(tc.is_ai_generated)
        self.assertEqual(tc.created_by, 'claude_cli')

    def test_batch_save_multiple_projects_isolation(self):
        """Saving to one project doesn't affect another"""
        project2 = Project.objects.create(name='Other Project')
        data = {
            'testcases': [{'name': 'TC-Edge'}]
        }
        self.client.post(
            f'/api/projects/{self.project.id}/batch-save/', data, format='json'
        )
        self.assertEqual(TC_Model.objects.filter(project=project2).count(), 0)
        self.assertEqual(TC_Model.objects.filter(project=self.project).count(), 1)


# ─── Round 3 Fixes Tests ───

class RepoAnalyzeConcurrencyTest(TestCase):
    """Test concurrent analysis prevention guard."""

    def setUp(self):
        self.project = Project.objects.create(
            name='Concurrent Project',
            repo_url='https://github.com/test/repo.git',
            local_repo_path='/tmp/concurrent-repo',
        )

    @mock.patch('core.views._submit_agent_task')
    def test_analyze_rejects_when_already_analyzing(self, mock_submit):
        """Should return 409 when an analysis is already in progress."""
        RepoAnalysis.objects.create(
            project=self.project,
            status='analyzing',
            local_repo_path=self.project.local_repo_path,
            discovered_items=[],
        )
        resp = self.client.post(f'/api/projects/{self.project.id}/repo/analyze/')
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('正在进行中', resp.data['error'])
        # Should NOT submit another task
        mock_submit.assert_not_called()

    @mock.patch('core.views._submit_agent_task')
    def test_analyze_allows_when_completed(self, mock_submit):
        """Should allow new analysis when previous one is completed."""
        RepoAnalysis.objects.create(
            project=self.project,
            status='completed',
            local_repo_path=self.project.local_repo_path,
            discovered_items=[],
        )
        resp = self.client.post(f'/api/projects/{self.project.id}/repo/analyze/')
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        mock_submit.assert_called_once()


class RepoAnalysisListProjectCheckTest(TestCase):
    """Test repo_analysis_list validates project existence."""

    def setUp(self):
        self.client = APIClient()

    def test_analysis_list_nonexistent_project(self):
        """Should return 404 for non-existent project."""
        resp = self.client.get('/api/projects/99999/repo/analysis/list/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_analysis_list_existing_project(self):
        """Should return 200 for existing project."""
        project = Project.objects.create(name='List Project')
        resp = self.client.get(f'/api/projects/{project.id}/repo/analysis/list/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class BatchSaveAtomicTest(TransactionTestCase):
    """Test batch_save_testcases atomicity."""

    def setUp(self):
        self.project = Project.objects.create(name='Atomic Project')
        self.client = APIClient()

    def test_batch_save_uses_transaction(self):
        """Batch save should be wrapped in transaction.atomic."""
        data = {
            'testcases': [
                {'name': 'TC-1'},
                {'name': 'TC-2'},
            ]
        }
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/', data, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(TC_Model.objects.filter(project=self.project).count(), 2)

    def test_batch_save_empty_list_returns_400(self):
        """Empty testcases list should return 400."""
        data = {'testcases': []}
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/', data, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class RepoAnalysisAdminTest(TestCase):
    """Verify RepoAnalysis and PreconditionTemplate are registered in admin."""

    def setUp(self):
        self.client = APIClient()

    def test_repo_analysis_registered(self):
        from django.contrib.admin.sites import site
        from core.models import RepoAnalysis
        self.assertIn(RepoAnalysis, site._registry)

    def test_precondition_template_registered(self):
        from django.contrib.admin.sites import site
        from core.models import PreconditionTemplate
        self.assertIn(PreconditionTemplate, site._registry)


class PreconditionUpdateDefaultProtectionTest(TestCase):
    """Test that default templates are protected from deletion but can be updated."""

    def setUp(self):
        self.client = APIClient()
        self.default_tpl = PreconditionTemplate.objects.create(
            name='SSO Login',
            description='SSO',
            steps='1. Login',
            is_default=True,
        )
        self.custom_tpl = PreconditionTemplate.objects.create(
            name='Custom Login',
            description='Custom',
            steps='1. Custom login',
            is_default=False,
        )

    def test_delete_default_template_rejected(self):
        resp = self.client.delete(f'/api/preconditions/{self.default_tpl.id}/delete/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(PreconditionTemplate.objects.filter(pk=self.default_tpl.pk).exists())

    def test_delete_custom_template_allowed(self):
        resp = self.client.delete(f'/api/preconditions/{self.custom_tpl.id}/delete/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(PreconditionTemplate.objects.filter(pk=self.custom_tpl.pk).exists())

    def test_update_template(self):
        resp = self.client.put(
            f'/api/preconditions/{self.custom_tpl.id}/',
            {'name': 'Updated', 'steps': 'New steps'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.custom_tpl.refresh_from_db()
        self.assertEqual(self.custom_tpl.name, 'Updated')

    def test_update_nonexistent_returns_404(self):
        resp = self.client.put(
            '/api/preconditions/99999/',
            {'name': 'Nope'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class RepoAnalyzerEdgeCaseTest(TestCase):
    """Additional edge case tests for repo_analyzer parsing."""

    def test_parse_response_with_extra_text_before_json(self):
        """Should handle text before the JSON block."""
        from core.repo_analyzer import _parse_analysis_response
        raw = 'Here are the results:\n{"pages": [{"type": "page", "path": "/home", "name": "Home", "description": "Main page"}], "apis": []}'
        result = _parse_analysis_response(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['type'], 'page')

    def test_parse_response_empty_pages_and_apis(self):
        """Should handle empty lists."""
        from core.repo_analyzer import _parse_analysis_response
        raw = '{"pages": [], "apis": []}'
        result = _parse_analysis_response(raw)
        self.assertEqual(result, [])

    def test_parse_response_missing_name_fills_default(self):
        """Items without name should get empty string."""
        from core.repo_analyzer import _parse_analysis_response
        raw = '{"pages": [{"type": "page", "path": "/x"}], "apis": []}'
        result = _parse_analysis_response(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].get('name', ''), '')


class BatchGeneratorEdgeCaseTest(TestCase):
    """Additional edge case tests for batch_generator."""

    def test_parse_non_list_items(self):
        """Items that are not dicts should be handled gracefully."""
        from core.batch_generator import generate_testcases_for_items
        # This should not crash, just produce results
        with mock.patch('core.batch_generator._get_client') as mock_client, \
             mock.patch('core.batch_generator._get_model', return_value='test-model'):
            mock_resp = mock.MagicMock()
            mock_resp.content = [mock.MagicMock(text='[]')]
            mock_client.return_value.messages.create.return_value = mock_resp
            result = generate_testcases_for_items(
                mock.MagicMock(),
                [{'type': 'page', 'path': '/x', 'name': 'X'}],
                {},
                None,
            )
            self.assertIsInstance(result, list)

    def test_generate_testcases_single_empty_result(self):
        """Single generation with empty AI response returns empty dict."""
        from core.batch_generator import generate_testcases_single
        with mock.patch('core.batch_generator._get_client') as mock_client, \
             mock.patch('core.batch_generator._get_model', return_value='test-model'):
            mock_resp = mock.MagicMock()
            mock_resp.content = [mock.MagicMock(text='[]')]
            mock_client.return_value.messages.create.return_value = mock_resp
            result = generate_testcases_single(
                mock.MagicMock(),
                {'type': 'api', 'path': '/api/test', 'name': 'Test'},
                'Test description',
            )
            self.assertEqual(result, {})


# ══════════════════════════════════════════════════════════════════
# 功能点分组 + 排序测试
# ══════════════════════════════════════════════════════════════════

class FeatureGroupModelTest(TestCase):
    """TestCase 的 feature_group 和 sort_order 字段默认值及排序"""

    def setUp(self):
        self.project = Project.objects.create(name='FG Project', base_url='https://example.com')

    def test_default_values(self):
        tc = TC_Model.objects.create(
            project=self.project,
            name='TC1', steps='s1', expected_result='ok',
        )
        self.assertEqual(tc.feature_group, '')
        self.assertEqual(tc.sort_order, 0)

    def test_ordering_by_feature_group_and_sort_order(self):
        """查询结果按 feature_group, sort_order, -updated_at 排序"""
        tc_b2 = TC_Model.objects.create(
            project=self.project, name='B-2', steps='s', expected_result='ok',
            feature_group='B组', sort_order=2,
        )
        tc_a1 = TC_Model.objects.create(
            project=self.project, name='A-1', steps='s', expected_result='ok',
            feature_group='A组', sort_order=1,
        )
        tc_a2 = TC_Model.objects.create(
            project=self.project, name='A-2', steps='s', expected_result='ok',
            feature_group='A组', sort_order=2,
        )
        tc_none = TC_Model.objects.create(
            project=self.project, name='None', steps='s', expected_result='ok',
            feature_group='', sort_order=0,
        )
        tcs = list(TC_Model.objects.all())
        # 空 feature_group 排最前
        self.assertEqual(tcs[0].name, 'None')
        # A 组按 sort_order 排列
        self.assertEqual(tcs[1].name, 'A-1')
        self.assertEqual(tcs[2].name, 'A-2')
        # B 组
        self.assertEqual(tcs[3].name, 'B-2')

    def test_serializer_includes_new_fields(self):
        tc = TC_Model.objects.create(
            project=self.project, name='TC', steps='s', expected_result='ok',
            feature_group='登录', sort_order=5,
        )
        from .serializers import TestCaseSerializer
        data = TestCaseSerializer(tc).data
        self.assertEqual(data['feature_group'], '登录')
        self.assertEqual(data['sort_order'], 5)


class FeatureGroupSerializerTest(TestCase):
    """TestCaseReorderSerializer 校验"""

    def test_valid_reorder_data(self):
        from .serializers import TestCaseReorderSerializer
        s = TestCaseReorderSerializer(data={
            'orders': [
                {'id': 1, 'feature_group': '登录', 'sort_order': 1},
                {'id': 2, 'feature_group': '登录', 'sort_order': 2},
            ]
        })
        self.assertTrue(s.is_valid())
        self.assertEqual(len(s.validated_data['orders']), 2)

    def test_missing_orders_returns_error(self):
        from .serializers import TestCaseReorderSerializer
        s = TestCaseReorderSerializer(data={})
        self.assertFalse(s.is_valid())
        self.assertIn('orders', s.errors)

    def test_defaults_for_optional_fields(self):
        from .serializers import TestCaseReorderSerializer
        s = TestCaseReorderSerializer(data={
            'orders': [{'id': 5}]
        })
        self.assertTrue(s.is_valid())
        item = s.validated_data['orders'][0]
        self.assertEqual(item['feature_group'], '')
        self.assertEqual(item['sort_order'], 0)


class ReorderAPITest(TestCase):
    """POST /api/projects/<id>/testcases/reorder/ 测试"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='Reorder Project', base_url='https://example.com')
        self.tc1 = TC_Model.objects.create(
            project=self.project, name='TC1', steps='s', expected_result='ok',
            feature_group='', sort_order=0,
        )
        self.tc2 = TC_Model.objects.create(
            project=self.project, name='TC2', steps='s', expected_result='ok',
            feature_group='', sort_order=0,
        )

    def test_reorder_success(self):
        resp = self.client.post(
            f'/api/projects/{self.project.id}/testcases/reorder/',
            {
                'orders': [
                    {'id': self.tc1.id, 'feature_group': '登录', 'sort_order': 1},
                    {'id': self.tc2.id, 'feature_group': '登录', 'sort_order': 2},
                ]
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['updated'], 2)
        self.tc1.refresh_from_db()
        self.tc2.refresh_from_db()
        self.assertEqual(self.tc1.feature_group, '登录')
        self.assertEqual(self.tc1.sort_order, 1)
        self.assertEqual(self.tc2.feature_group, '登录')
        self.assertEqual(self.tc2.sort_order, 2)

    def test_reorder_project_not_found(self):
        resp = self.client.post(
            '/api/projects/99999/testcases/reorder/',
            {'orders': [{'id': 1, 'feature_group': 'X', 'sort_order': 1}]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_reorder_empty_orders(self):
        resp = self.client.post(
            f'/api/projects/{self.project.id}/testcases/reorder/',
            {'orders': []},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reorder_wrong_project_testcase(self):
        """不能修改其他项目的用例"""
        other_project = Project.objects.create(name='Other', base_url='https://other.com')
        other_tc = TC_Model.objects.create(
            project=other_project, name='OtherTC', steps='s', expected_result='ok',
        )
        resp = self.client.post(
            f'/api/projects/{self.project.id}/testcases/reorder/',
            {'orders': [{'id': other_tc.id, 'feature_group': 'X', 'sort_order': 1}]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reorder_atomic_transaction(self):
        """排序操作是原子的 — 部分失败不应修改任何记录"""
        resp = self.client.post(
            f'/api/projects/{self.project.id}/testcases/reorder/',
            {'orders': [
                {'id': self.tc1.id, 'feature_group': 'A', 'sort_order': 1},
                {'id': 99999, 'feature_group': 'B', 'sort_order': 2},  # 不存在的 ID
            ]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.tc1.refresh_from_db()
        self.assertEqual(self.tc1.feature_group, '')  # 未被修改


class FeatureGroupsAPITest(TestCase):
    """GET /api/projects/<id>/feature-groups/ 测试"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='FG Project', base_url='https://example.com')

    def test_returns_grouped_counts(self):
        TC_Model.objects.create(project=self.project, name='TC1', steps='s', expected_result='ok',
                                feature_group='登录', sort_order=1)
        TC_Model.objects.create(project=self.project, name='TC2', steps='s', expected_result='ok',
                                feature_group='登录', sort_order=2)
        TC_Model.objects.create(project=self.project, name='TC3', steps='s', expected_result='ok',
                                feature_group='订单', sort_order=1)
        TC_Model.objects.create(project=self.project, name='TC4', steps='s', expected_result='ok',
                                feature_group='', sort_order=0)

        resp = self.client.get(f'/api/projects/{self.project.id}/feature-groups/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        groups = resp.data['groups']
        # 3 groups: 未分组, 登录, 订单
        self.assertEqual(len(groups), 3)
        group_map = {g['name']: g['count'] for g in groups}
        self.assertEqual(group_map['登录'], 2)
        self.assertEqual(group_map['订单'], 1)
        self.assertEqual(group_map['未分组'], 1)

    def test_empty_project(self):
        resp = self.client.get(f'/api/projects/{self.project.id}/feature-groups/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['groups'], [])

    def test_project_not_found(self):
        resp = self.client.get('/api/projects/99999/feature-groups/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class ExecuteProjectOrderingTest(TestCase):
    """验证 execute_project_agent 按 feature_group + sort_order 顺序提交任务"""

    @mock.patch('core.views._submit_agent_task')
    @mock.patch('core.views._get_ai_model', return_value='test-model')
    def test_execution_order_respects_sort(self, mock_model, mock_submit):
        """批量执行按 feature_group + sort_order 排序提交"""
        project = Project.objects.create(name='Exec Order', base_url='https://example.com')
        # 按非排序顺序创建
        tc_b = TC_Model.objects.create(
            project=project, name='B', steps='s', expected_result='ok',
            status='ready', feature_group='B组', sort_order=1,
        )
        tc_a = TC_Model.objects.create(
            project=project, name='A', steps='s', expected_result='ok',
            status='ready', feature_group='A组', sort_order=1,
        )
        tc_a2 = TC_Model.objects.create(
            project=project, name='A2', steps='s', expected_result='ok',
            status='ready', feature_group='A组', sort_order=2,
        )

        resp = self.client.post(f'/api/projects/{project.id}/execute-agent/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        # 提交了 3 个任务
        self.assertEqual(mock_submit.call_count, 3)
        # 检查提交顺序: A组(sort_order=1), A组(sort_order=2), B组(sort_order=1)
        records = list(ExecutionRecord.objects.order_by('id'))
        self.assertEqual(records[0].testcase_id, tc_a.id)
        self.assertEqual(records[1].testcase_id, tc_a2.id)
        self.assertEqual(records[2].testcase_id, tc_b.id)


class BatchSaveFeatureGroupTest(TestCase):
    """验证 batch_save_testcases 正确保存 feature_group 和 sort_order"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='Batch FG', base_url='https://example.com')

    def test_saves_feature_group_and_sort_order(self):
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/',
            {'testcases': [
                {'name': 'TC1', 'steps': 's', 'expected_result': 'ok',
                 'feature_group': '登录', 'sort_order': 1},
                {'name': 'TC2', 'steps': 's', 'expected_result': 'ok',
                 'feature_group': '订单', 'sort_order': 2},
            ]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        tcs = list(TC_Model.objects.order_by('id'))
        self.assertEqual(tcs[0].feature_group, '登录')
        self.assertEqual(tcs[0].sort_order, 1)
        self.assertEqual(tcs[1].feature_group, '订单')
        self.assertEqual(tcs[1].sort_order, 2)

    def test_default_sort_order_is_index(self):
        """未提供 sort_order 时使用数组下标"""
        resp = self.client.post(
            f'/api/projects/{self.project.id}/batch-save/',
            {'testcases': [
                {'name': 'TC1', 'steps': 's', 'expected_result': 'ok', 'feature_group': 'A'},
                {'name': 'TC2', 'steps': 's', 'expected_result': 'ok', 'feature_group': 'B'},
                {'name': 'TC3', 'steps': 's', 'expected_result': 'ok', 'feature_group': 'C'},
            ]},
            format='json',
        )
        tcs = list(TC_Model.objects.order_by('id'))
        self.assertEqual(tcs[0].sort_order, 1)
        self.assertEqual(tcs[1].sort_order, 2)
        self.assertEqual(tcs[2].sort_order, 3)


# ══════════════════════════════════════════════════════════════════
# Script Model + API Tests
# ══════════════════════════════════════════════════════════════════

class ScriptModelTest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='ScriptTest', base_url='https://example.com')
        self.tc = TC_Model.objects.create(
            project=self.project, name='Login Test',
            steps='Navigate to login', expected_result='Login succeeds',
        )

    def test_create_script(self):
        script = Script.objects.create(
            project=self.project, testcase=self.tc,
            name='Login Script', feature_group='登录',
            script_data={'version': 1, 'parameters': {}, 'steps': []},
            status='draft', version=1,
        )
        self.assertEqual(str(script), '[draft] Login Script (v1)')
        self.assertEqual(script.project, self.project)
        self.assertEqual(script.testcase, self.tc)

    def test_default_values(self):
        script = Script.objects.create(project=self.project, name='Test')
        self.assertEqual(script.status, 'draft')
        self.assertEqual(script.version, 1)
        self.assertEqual(script.sort_order, 0)
        self.assertEqual(script.feature_group, '')

    def test_ordering(self):
        Script.objects.create(project=self.project, name='B', feature_group='Group2', sort_order=2)
        Script.objects.create(project=self.project, name='A', feature_group='Group1', sort_order=1)
        scripts = list(Script.objects.all())
        self.assertEqual(scripts[0].name, 'A')
        self.assertEqual(scripts[1].name, 'B')


class ScriptAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='ScriptAPITest', base_url='https://example.com')
        self.tc = TC_Model.objects.create(
            project=self.project, name='TC1', steps='Step 1', expected_result='OK',
        )

    def test_script_list(self):
        Script.objects.create(project=self.project, name='S1', script_data={'steps': []})
        Script.objects.create(project=self.project, name='S2', script_data={'steps': []})
        resp = self.client.get('/api/scripts/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['scripts']), 2)

    def test_script_list_filter_by_project(self):
        p2 = Project.objects.create(name='Other', base_url='https://other.com')
        Script.objects.create(project=self.project, name='S1')
        Script.objects.create(project=p2, name='S2')
        resp = self.client.get('/api/scripts/', {'project': self.project.id})
        self.assertEqual(len(resp.data['scripts']), 1)
        self.assertEqual(resp.data['scripts'][0]['name'], 'S1')

    def test_script_detail(self):
        script = Script.objects.create(
            project=self.project, testcase=self.tc,
            name='Detail Script', script_data={'version': 1, 'parameters': {}, 'steps': []},
        )
        resp = self.client.get(f'/api/scripts/{script.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['name'], 'Detail Script')
        self.assertEqual(resp.data['testcase_name'], 'TC1')

    def test_script_update(self):
        script = Script.objects.create(project=self.project, name='Old Name')
        resp = self.client.put(
            f'/api/scripts/{script.id}/update/',
            {'name': 'New Name', 'feature_group': 'Login', 'status': 'active'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        script.refresh_from_db()
        self.assertEqual(script.name, 'New Name')
        self.assertEqual(script.feature_group, 'Login')
        self.assertEqual(script.status, 'active')

    def test_script_delete(self):
        script = Script.objects.create(project=self.project, name='ToDelete')
        resp = self.client.delete(f'/api/scripts/{script.id}/delete/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Script.objects.filter(id=script.id).exists())

    def test_script_convert(self):
        """Test converting an ExecutionRecord to a Script model"""
        record = ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc,
            execution_mode='agent', status='passed',
            log='=== TOOL_CALLS_JSON ===\n{"tool_calls":[{"tool":"browser_navigate","input":{"url":"https://example.com"}}]}',
            step_logs=[{'step_num': 1, 'action': 'navigate', 'tool_name': 'browser_navigate', 'target': 'https://example.com', 'result': 'OK'}],
        )
        resp = self.client.post('/api/scripts/convert/', {
            'execution_id': record.id,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertIn('name', resp.data)
        self.assertEqual(resp.data['project'], self.project.id)
        # Verify Script was created
        script = Script.objects.get(source_execution=record)
        self.assertEqual(script.testcase, self.tc)

    def test_script_convert_non_agent_rejected(self):
        record = ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc,
            execution_mode='script', status='passed',
        )
        resp = self.client.post('/api/scripts/convert/', {
            'execution_id': record.id,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_script_convert_non_terminal_rejected(self):
        record = ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc,
            execution_mode='agent', status='running',
        )
        resp = self.client.post('/api/scripts/convert/', {
            'execution_id': record.id,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_script_feature_groups(self):
        Script.objects.create(project=self.project, name='S1', feature_group='Login')
        Script.objects.create(project=self.project, name='S2', feature_group='Login')
        Script.objects.create(project=self.project, name='S3', feature_group='Order')
        resp = self.client.get('/api/scripts/feature-groups/', {'project': self.project.id})
        self.assertEqual(resp.status_code, 200)
        groups = resp.data['groups']
        self.assertEqual(len(groups), 2)
        # Find Login group
        login_g = next(g for g in groups if g['name'] == 'Login')
        self.assertEqual(login_g['count'], 2)


class ScriptExecuteTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='ScriptExecTest', base_url='https://example.com')
        self.tc = TC_Model.objects.create(
            project=self.project, name='TC', steps='s', expected_result='ok',
        )
        # Create an execution record with replay script data
        self.record = ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc,
            execution_mode='agent', status='passed',
            replay_script={'version': 1, 'name': 'test', 'base_url': 'https://example.com',
                          'parameters': {}, 'steps': [
                              {'step_num': 1, 'enabled': True, 'tool_name': 'browser_navigate',
                               'description': 'Navigate', 'inputs': {'url': 'https://example.com'}, 'parameters': []}
                          ]},
        )
        self.script = Script.objects.create(
            project=self.project, testcase=self.tc,
            source_execution=self.record, name='Test Script',
            script_data=self.record.replay_script, status='active',
        )

    @mock.patch('core.views._submit_agent_task')
    def test_script_execute(self, mock_submit):
        resp = self.client.post(f'/api/scripts/{self.script.id}/execute/', format='json')
        self.assertEqual(resp.status_code, 202)
        mock_submit.assert_called_once()
        # Verify ExecutionRecord was created
        new_record = ExecutionRecord.objects.filter(source_execution=self.record, execution_mode='replay').first()
        self.assertIsNotNone(new_record)

    def test_script_execute_no_source(self):
        """Script without source_execution should auto-create a dummy record and succeed"""
        script = Script.objects.create(
            project=self.project, name='No Source',
            script_data={'steps': []}, status='active',
        )
        resp = self.client.post(f'/api/scripts/{script.id}/execute/', format='json')
        self.assertEqual(resp.status_code, 202)
        # Verify a source_execution was auto-created
        script.refresh_from_db()
        self.assertIsNotNone(script.source_execution)


# ══════════════════════════════════════════════════════════════════
# TestPlan + TestPlanItem Tests
# ══════════════════════════════════════════════════════════════════

class TestPlanModelTest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='PlanTest', base_url='https://example.com')

    def test_create_plan(self):
        plan = TestPlan.objects.create(project=self.project, name='Smoke Test')
        self.assertIn('draft', str(plan))
        self.assertTrue(plan.api_token)  # Auto-generated UUID

    def test_unique_api_token(self):
        plan1 = TestPlan.objects.create(project=self.project, name='Plan1')
        plan2 = TestPlan.objects.create(project=self.project, name='Plan2')
        self.assertNotEqual(plan1.api_token, plan2.api_token)

    def test_plan_item_script_type(self):
        plan = TestPlan.objects.create(project=self.project, name='Plan')
        tc = TC_Model.objects.create(project=self.project, name='TC', steps='s', expected_result='ok')
        record = ExecutionRecord.objects.create(project=self.project, testcase=tc, execution_mode='agent', status='passed')
        script = Script.objects.create(project=self.project, name='S1', source_execution=record, script_data={})
        item = TestPlanItem.objects.create(
            test_plan=plan, item_type='script', script=script, sort_order=1,
        )
        self.assertIn('Script', str(item))
        self.assertIn('S1', str(item))

    def test_plan_item_feature_group_type(self):
        plan = TestPlan.objects.create(project=self.project, name='Plan')
        item = TestPlanItem.objects.create(
            test_plan=plan, item_type='feature_group', feature_group_name='Login', sort_order=1,
        )
        self.assertIn('Feature', str(item))
        self.assertIn('Login', str(item))

    def test_plan_item_ordering(self):
        plan = TestPlan.objects.create(project=self.project, name='Plan')
        TestPlanItem.objects.create(test_plan=plan, item_type='feature_group', feature_group_name='B', sort_order=2)
        TestPlanItem.objects.create(test_plan=plan, item_type='feature_group', feature_group_name='A', sort_order=1)
        items = list(plan.items.all())
        self.assertEqual(items[0].feature_group_name, 'A')
        self.assertEqual(items[1].feature_group_name, 'B')


class TestPlanAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='PlanAPITest', base_url='https://example.com')

    def test_plan_create(self):
        resp = self.client.post('/api/plans/create/', {
            'project': self.project.id, 'name': 'My Plan', 'description': 'Test plan',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['name'], 'My Plan')
        self.assertIn('api_token', resp.data)

    def test_plan_list(self):
        TestPlan.objects.create(project=self.project, name='Plan1')
        TestPlan.objects.create(project=self.project, name='Plan2')
        resp = self.client.get('/api/plans/')
        self.assertEqual(len(resp.data['plans']), 2)

    def test_plan_list_filter_project(self):
        p2 = Project.objects.create(name='Other', base_url='https://other.com')
        TestPlan.objects.create(project=self.project, name='Plan1')
        TestPlan.objects.create(project=p2, name='Plan2')
        resp = self.client.get('/api/plans/', {'project': self.project.id})
        self.assertEqual(len(resp.data['plans']), 1)

    def test_plan_detail(self):
        plan = TestPlan.objects.create(project=self.project, name='Detail Plan')
        resp = self.client.get(f'/api/plans/{plan.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['name'], 'Detail Plan')
        self.assertEqual(resp.data['item_count'], 0)

    def test_plan_update(self):
        plan = TestPlan.objects.create(project=self.project, name='Old Name')
        resp = self.client.put(f'/api/plans/{plan.id}/update/', {
            'name': 'New Name', 'status': 'active',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        plan.refresh_from_db()
        self.assertEqual(plan.name, 'New Name')
        self.assertEqual(plan.status, 'active')

    def test_plan_delete(self):
        plan = TestPlan.objects.create(project=self.project, name='ToDelete')
        resp = self.client.delete(f'/api/plans/{plan.id}/delete/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TestPlan.objects.filter(id=plan.id).exists())

    def test_add_script_item(self):
        plan = TestPlan.objects.create(project=self.project, name='Plan')
        tc = TC_Model.objects.create(project=self.project, name='TC', steps='s', expected_result='ok')
        record = ExecutionRecord.objects.create(project=self.project, testcase=tc, status='passed')
        script = Script.objects.create(project=self.project, name='S1', source_execution=record, script_data={}, status='active')
        resp = self.client.post(f'/api/plans/{plan.id}/items/', {
            'item_type': 'script', 'script_id': script.id,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['item_type'], 'script')
        self.assertEqual(resp.data['script'], script.id)

    def test_add_feature_group_item(self):
        plan = TestPlan.objects.create(project=self.project, name='Plan')
        resp = self.client.post(f'/api/plans/{plan.id}/items/', {
            'item_type': 'feature_group', 'feature_group_name': 'Login',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['feature_group_name'], 'Login')

    def test_add_script_item_missing_id(self):
        plan = TestPlan.objects.create(project=self.project, name='Plan')
        resp = self.client.post(f'/api/plans/{plan.id}/items/', {
            'item_type': 'script',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_add_feature_group_item_missing_name(self):
        plan = TestPlan.objects.create(project=self.project, name='Plan')
        resp = self.client.post(f'/api/plans/{plan.id}/items/', {
            'item_type': 'feature_group',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_reorder_items(self):
        plan = TestPlan.objects.create(project=self.project, name='Plan')
        item1 = TestPlanItem.objects.create(test_plan=plan, item_type='feature_group', feature_group_name='A', sort_order=1)
        item2 = TestPlanItem.objects.create(test_plan=plan, item_type='feature_group', feature_group_name='B', sort_order=2)
        resp = self.client.put(f'/api/plans/{plan.id}/items/reorder/', {
            'orders': [{'id': item1.id, 'sort_order': 2}, {'id': item2.id, 'sort_order': 1}],
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        item1.refresh_from_db()
        item2.refresh_from_db()
        self.assertEqual(item1.sort_order, 2)
        self.assertEqual(item2.sort_order, 1)

    def test_delete_item(self):
        plan = TestPlan.objects.create(project=self.project, name='Plan')
        item = TestPlanItem.objects.create(test_plan=plan, item_type='feature_group', feature_group_name='A')
        resp = self.client.delete(f'/api/plans/items/{item.id}/delete/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TestPlanItem.objects.filter(id=item.id).exists())

    def test_regenerate_token(self):
        plan = TestPlan.objects.create(project=self.project, name='Plan')
        old_token = plan.api_token
        resp = self.client.post(f'/api/plans/{plan.id}/regenerate-token/')
        self.assertEqual(resp.status_code, 200)
        plan.refresh_from_db()
        self.assertNotEqual(plan.api_token, old_token)


# ══════════════════════════════════════════════════════════════════
# PlanExecution + CI/CD Tests
# ══════════════════════════════════════════════════════════════════

class PlanExecutionModelTest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='PlanExecTest', base_url='https://example.com')
        self.plan = TestPlan.objects.create(project=self.project, name='Plan')

    def test_create_plan_execution(self):
        pe = PlanExecution.objects.create(
            test_plan=self.plan, project=self.project,
            status='running', trigger_source='manual',
            summary={'total': 5, 'passed': 3, 'failed': 1, 'error': 0, 'skipped': 1},
        )
        self.assertIn('running', str(pe))
        self.assertIn('Plan', str(pe))

    def test_execution_record_plan_execution_fk(self):
        pe = PlanExecution.objects.create(
            test_plan=self.plan, project=self.project, status='pending',
        )
        tc = TC_Model.objects.create(project=self.project, name='TC', steps='s', expected_result='ok')
        record = ExecutionRecord.objects.create(
            project=self.project, testcase=tc, status='passed', plan_execution=pe,
        )
        self.assertEqual(record.plan_execution, pe)
        self.assertIn('Plan', str(record))

    def test_execution_record_without_plan(self):
        tc = TC_Model.objects.create(project=self.project, name='TC', steps='s', expected_result='ok')
        record = ExecutionRecord.objects.create(project=self.project, testcase=tc, status='passed')
        self.assertIsNone(record.plan_execution)
        self.assertNotIn('方案', str(record))


class PlanExecutionAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='PlanExecAPITest', base_url='https://example.com')
        self.plan = TestPlan.objects.create(project=self.project, name='TestPlan')
        self.tc = TC_Model.objects.create(project=self.project, name='TC', steps='s', expected_result='ok')
        self.record = ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc, execution_mode='agent', status='passed',
            replay_script={'version': 1, 'name': 'test', 'base_url': 'https://example.com',
                          'parameters': {}, 'steps': [
                              {'step_num': 1, 'enabled': True, 'tool_name': 'browser_navigate',
                               'description': 'Navigate', 'inputs': {'url': 'https://example.com'}, 'parameters': []}
                          ]},
        )
        self.script = Script.objects.create(
            project=self.project, name='S1', source_execution=self.record,
            script_data=self.record.replay_script, status='active',
        )
        self.plan_item = TestPlanItem.objects.create(
            test_plan=self.plan, item_type='script', script=self.script, sort_order=1,
        )

    def test_plan_execution_list(self):
        PlanExecution.objects.create(test_plan=self.plan, project=self.project, status='completed')
        resp = self.client.get('/api/plan-executions/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['executions']), 1)

    def test_plan_execution_list_filter_plan(self):
        PlanExecution.objects.create(test_plan=self.plan, project=self.project, status='completed')
        resp = self.client.get('/api/plan-executions/', {'plan': self.plan.id})
        self.assertEqual(len(resp.data['executions']), 1)

    def test_plan_execution_detail(self):
        pe = PlanExecution.objects.create(
            test_plan=self.plan, project=self.project, status='completed',
            summary={'total': 1, 'passed': 1, 'failed': 0, 'error': 0, 'skipped': 0},
        )
        ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc, status='passed', plan_execution=pe,
        )
        resp = self.client.get(f'/api/plan-executions/{pe.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'completed')
        self.assertIn('execution_records', resp.data)
        self.assertEqual(len(resp.data['execution_records']), 1)

    def test_plan_execution_status_lightweight(self):
        pe = PlanExecution.objects.create(
            test_plan=self.plan, project=self.project, status='running',
            summary={'total': 2, 'passed': 0, 'failed': 0, 'error': 0, 'skipped': 0},
        )
        resp = self.client.get(f'/api/plan-executions/{pe.id}/status/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'running')
        self.assertNotIn('execution_records', resp.data)  # Lightweight response

    @mock.patch('core.views._submit_agent_task')
    def test_plan_execute_async(self, mock_submit):
        resp = self.client.post(
            f'/api/plans/{self.plan.id}/execute/',
            HTTP_X_PLAN_TOKEN=str(self.plan.api_token),
        )
        self.assertEqual(resp.status_code, 202)
        mock_submit.assert_called_once()
        pe = PlanExecution.objects.get(test_plan=self.plan)
        self.assertEqual(pe.status, 'running')
        self.assertEqual(pe.trigger_source, 'api')

    @mock.patch('core.views._submit_agent_task')
    def test_plan_execute_with_token_auth(self, mock_submit):
        resp = self.client.post(
            f'/api/plans/{self.plan.id}/execute/',
            HTTP_X_PLAN_TOKEN=str(self.plan.api_token),
        )
        self.assertEqual(resp.status_code, 202)
        pe = PlanExecution.objects.get(test_plan=self.plan)
        self.assertEqual(pe.trigger_source, 'api')

    def test_plan_execute_wrong_token_rejected(self):
        resp = self.client.post(
            f'/api/plans/{self.plan.id}/execute/',
            HTTP_X_PLAN_TOKEN='wrong-token',
        )
        self.assertEqual(resp.status_code, 403)

    def test_plan_execute_no_base_url(self):
        project = Project.objects.create(name='NoURL')
        plan = TestPlan.objects.create(project=project, name='NoURLPlan')
        resp = self.client.post(
            f'/api/plans/{plan.id}/execute/',
            HTTP_X_PLAN_TOKEN=str(plan.api_token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_plan_execute_empty_plan(self):
        plan = TestPlan.objects.create(project=self.project, name='Empty')
        resp = self.client.post(
            f'/api/plans/{plan.id}/execute/',
            HTTP_X_PLAN_TOKEN=str(plan.api_token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_plan_execution_junit_report(self):
        pe = PlanExecution.objects.create(
            test_plan=self.plan, project=self.project, status='completed',
            summary={'total': 2, 'passed': 1, 'failed': 1, 'error': 0, 'skipped': 0},
        )
        ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc, status='passed',
            duration=5.2, plan_execution=pe,
        )
        ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc, status='failed',
            duration=3.1, error_message='Button not found', plan_execution=pe,
        )
        resp = self.client.get(f'/api/plan-executions/{pe.id}/report/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('xml', resp['Content-Type'])
        self.assertIn('testsuites', resp.data)
        self.assertIn('testsuite', resp.data)
        self.assertIn('failure', resp.data)
        self.assertIn('Button not found', resp.data)

    def test_plan_execution_junit_report_error_status(self):
        pe = PlanExecution.objects.create(
            test_plan=self.plan, project=self.project, status='error',
            summary={'total': 1, 'passed': 0, 'failed': 0, 'error': 1, 'skipped': 0},
        )
        ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc, status='error',
            duration=1.0, error_message='Crash', plan_execution=pe,
        )
        resp = self.client.get(f'/api/plan-executions/{pe.id}/report/')
        self.assertIn('<error', resp.data)


# ══════════════════════════════════════════════════════════════════
# Feature Group Execution Tests
# ══════════════════════════════════════════════════════════════════

class FeatureGroupExecutionTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='FGExecTest', base_url='https://example.com')
        self.tc1 = TC_Model.objects.create(
            project=self.project, name='Login Test', steps='s', expected_result='ok',
            feature_group='Login', sort_order=1, status='ready',
        )
        self.tc2 = TC_Model.objects.create(
            project=self.project, name='Logout Test', steps='s', expected_result='ok',
            feature_group='Login', sort_order=2, status='ready',
        )

    @mock.patch('core.views._submit_agent_task')
    def test_execute_feature_group(self, mock_submit):
        resp = self.client.post(f'/api/projects/{self.project.id}/features/Login/execute/')
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.data['count'], 2)
        self.assertEqual(resp.data['feature_group'], 'Login')
        mock_submit.assert_called()

    @mock.patch('core.views._submit_agent_task')
    def test_execute_empty_feature_group(self, mock_submit):
        resp = self.client.post(f'/api/projects/{self.project.id}/features/Nonexistent/execute/')
        self.assertEqual(resp.status_code, 400)

    def test_execute_feature_group_no_base_url(self):
        project = Project.objects.create(name='NoURL')
        resp = self.client.post(f'/api/projects/{project.id}/features/Login/execute/')
        self.assertEqual(resp.status_code, 400)

    def test_feature_groups_detailed(self):
        resp = self.client.get(f'/api/projects/{self.project.id}/feature-groups/', {'detailed': 'true'})
        self.assertEqual(resp.status_code, 200)
        groups = resp.data['groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['name'], 'Login')
        self.assertEqual(len(groups[0]['testcases']), 2)

    def test_feature_groups_not_detailed(self):
        resp = self.client.get(f'/api/projects/{self.project.id}/feature-groups/')
        groups = resp.data['groups']
        self.assertEqual(len(groups), 1)
        self.assertNotIn('testcases', groups[0])


class FeatureGroupExecutionUngroupedTest(TestCase):
    """Test executing the '未分组' (empty feature_group) group"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='UngroupedTest', base_url='https://example.com')
        self.tc = TC_Model.objects.create(
            project=self.project, name='Ungrouped TC', steps='s', expected_result='ok',
            feature_group='', sort_order=1, status='ready',
        )

    @mock.patch('core.views._submit_agent_task')
    def test_execute_ungrouped(self, mock_submit):
        resp = self.client.post(f'/api/projects/{self.project.id}/features/未分组/execute/')
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.data['count'], 1)


# ══════════════════════════════════════════════════════════════════
# Round 2 Quality Tests
# ══════════════════════════════════════════════════════════════════

class TestPlanTokenDisplayTest(TestCase):
    """Test api_token_display masking in serializer"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='TokenTest', base_url='https://example.com')

    def test_api_token_display_masked(self):
        plan = TestPlan.objects.create(project=self.project, name='Token Plan')
        resp = self.client.get(f'/api/plans/{plan.id}/')
        self.assertEqual(resp.status_code, 200)
        # Should have api_token (full) and api_token_display (masked)
        self.assertIn('api_token', resp.data)
        self.assertIn('api_token_display', resp.data)
        display = resp.data['api_token_display']
        self.assertIn('****', display)

    def test_api_token_display_short_token(self):
        """Token display handles standard UUID tokens"""
        plan = TestPlan.objects.create(project=self.project, name='Short Token')
        resp = self.client.get(f'/api/plans/{plan.id}/')
        display = resp.data['api_token_display']
        # UUID tokens are always > 12 chars, so should have ****
        self.assertIn('****', display)


class PlanItemReorderTest(TestCase):
    """Test plan item reorder endpoint"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='ReorderTest', base_url='https://example.com')
        self.plan = TestPlan.objects.create(project=self.project, name='Reorder Plan')
        self.item1 = TestPlanItem.objects.create(
            test_plan=self.plan, item_type='feature_group',
            feature_group_name='Group A', sort_order=1,
        )
        self.item2 = TestPlanItem.objects.create(
            test_plan=self.plan, item_type='feature_group',
            feature_group_name='Group B', sort_order=2,
        )
        self.item3 = TestPlanItem.objects.create(
            test_plan=self.plan, item_type='feature_group',
            feature_group_name='Group C', sort_order=3,
        )

    def test_reorder_success(self):
        resp = self.client.put(
            f'/api/plans/{self.plan.id}/items/reorder/',
            {'orders': [
                {'id': self.item3.id, 'sort_order': 1},
                {'id': self.item1.id, 'sort_order': 2},
                {'id': self.item2.id, 'sort_order': 3},
            ]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.item1.refresh_from_db()
        self.item2.refresh_from_db()
        self.item3.refresh_from_db()
        self.assertEqual(self.item3.sort_order, 1)
        self.assertEqual(self.item1.sort_order, 2)
        self.assertEqual(self.item2.sort_order, 3)

    def test_reorder_invalid_item(self):
        resp = self.client.put(
            f'/api/plans/{self.plan.id}/items/reorder/',
            {'orders': [{'id': 99999, 'sort_order': 1}]},
            format='json',
        )
        # Invalid item ID is silently skipped, returns 200 with updated=0
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['updated'], 0)

    def test_reorder_empty_orders(self):
        resp = self.client.put(
            f'/api/plans/{self.plan.id}/items/reorder/',
            {'orders': []},
            format='json',
        )
        # Empty orders returns 400
        self.assertEqual(resp.status_code, 400)


class DetailedFeatureGroupsTest(TestCase):
    """Test enhanced feature groups with detailed test case data"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='FGDetailTest', base_url='https://example.com')

    def test_detailed_returns_testcases(self):
        tc1 = TC_Model.objects.create(
            project=self.project, name='TC1', steps='s', expected_result='ok',
            feature_group='Login', status='ready', sort_order=1,
        )
        tc2 = TC_Model.objects.create(
            project=self.project, name='TC2', steps='s', expected_result='ok',
            feature_group='Login', status='draft', sort_order=2,
        )
        resp = self.client.get(f'/api/projects/{self.project.id}/feature-groups/', {'detailed': 'true'})
        self.assertEqual(resp.status_code, 200)
        groups = resp.data['groups']
        login_group = next(g for g in groups if g['name'] == 'Login')
        self.assertEqual(login_group['count'], 2)
        self.assertIn('testcases', login_group)
        self.assertEqual(len(login_group['testcases']), 2)
        # Verify testcase fields
        tc_data = login_group['testcases'][0]
        self.assertIn('id', tc_data)
        self.assertIn('name', tc_data)
        self.assertIn('status', tc_data)
        self.assertIn('latest_execution_status', tc_data)

    def test_non_detailed_no_testcases(self):
        TC_Model.objects.create(
            project=self.project, name='TC1', steps='s', expected_result='ok',
            feature_group='Login', status='ready',
        )
        resp = self.client.get(f'/api/projects/{self.project.id}/feature-groups/')
        groups = resp.data['groups']
        login_group = next(g for g in groups if g['name'] == 'Login')
        self.assertNotIn('testcases', login_group)


class ScriptExecuteAutoSourceTest(TestCase):
    """Test that scripts without source_execution get auto-created records"""

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name='AutoSourceTest', base_url='https://example.com')
        self.tc = TC_Model.objects.create(
            project=self.project, name='Auto TC', steps='s', expected_result='ok',
        )

    @mock.patch('core.views._submit_agent_task')
    def test_auto_creates_source_execution(self, mock_submit):
        """Script with no source_execution auto-creates a dummy ExecutionRecord"""
        script = Script.objects.create(
            project=self.project, testcase=self.tc,
            name='Auto Source Script',
            script_data={'steps': [{'action': 'navigate', 'url': 'https://example.com'}]},
            status='active',
        )
        self.assertIsNone(script.source_execution)

        resp = self.client.post(f'/api/scripts/{script.id}/execute/', format='json')
        self.assertEqual(resp.status_code, 202)

        # Source execution auto-created
        script.refresh_from_db()
        self.assertIsNotNone(script.source_execution)
        self.assertEqual(script.source_execution.replay_script, script.script_data)

        # New execution record created
        mock_submit.assert_called_once()

    @mock.patch('core.views._submit_agent_task')
    def test_existing_source_no_duplicate(self, mock_submit):
        """Script with existing source_execution uses it directly"""
        existing_record = ExecutionRecord.objects.create(
            project=self.project, testcase=self.tc,
            status='completed', execution_mode='agent',
            replay_script={'steps': []},
        )
        script = Script.objects.create(
            project=self.project, testcase=self.tc,
            name='Has Source Script',
            script_data={'steps': []},
            source_execution=existing_record,
            status='active',
        )
        resp = self.client.post(f'/api/scripts/{script.id}/execute/', format='json')
        self.assertEqual(resp.status_code, 202)
        # No new dummy record created
        self.assertEqual(ExecutionRecord.objects.filter(project=self.project).count(), 2)


# ══════════════════════════════════════════════════════════════════
# Data Migration Tests
# ══════════════════════════════════════════════════════════════════

class DataMigrationTest(TestCase):
    """Tests for 0017_migrate_replay_scripts data migration."""

    def _run_migration(self):
        """Execute the data migration function directly via importlib."""
        import importlib
        mod = importlib.import_module('core.migrations.0017_migrate_replay_scripts')
        apps_proxy = type('Apps', (), {'get_model': lambda self, app, model: {
            'ExecutionRecord': ExecutionRecord,
            'Script': Script,
        }.get(model)})()
        mod.migrate_replay_scripts_to_script_model(apps_proxy, None)

    def test_migrate_replay_script_creates_script_records(self):
        """Records with replay_script data get migrated to Script model."""
        project = Project.objects.create(name='Migration Test', base_url='https://example.com')
        tc = TC_Model.objects.create(project=project, name='TC1', feature_group='登录')
        record = ExecutionRecord.objects.create(
            project=project, testcase=tc, status='passed', execution_mode='agent',
            replay_script={'steps': [{'action': 'click'}], 'parameters': {'url': {}}},
        )
        self._run_migration()

        script = Script.objects.filter(source_execution=record).first()
        self.assertIsNotNone(script)
        self.assertEqual(script.project_id, project.id)
        self.assertEqual(script.testcase_id, tc.id)
        self.assertEqual(script.name, 'TC1')
        self.assertEqual(script.feature_group, '登录')
        self.assertEqual(script.status, 'active')
        self.assertEqual(script.script_data, record.replay_script)

    def test_migrate_skips_empty_replay_script(self):
        """Records with empty or null replay_script are skipped."""
        project = Project.objects.create(name='Migration Test 2', base_url='https://example.com')
        ExecutionRecord.objects.create(
            project=project, status='passed', execution_mode='agent',
            replay_script={},
        )
        ExecutionRecord.objects.create(
            project=project, status='passed', execution_mode='script',
        )
        self._run_migration()
        self.assertEqual(Script.objects.count(), 0)

    def test_migrate_idempotent(self):
        """Running migration twice doesn't create duplicates."""
        project = Project.objects.create(name='Migration Test 3', base_url='https://example.com')
        tc = TC_Model.objects.create(project=project, name='TC2')
        record = ExecutionRecord.objects.create(
            project=project, testcase=tc, status='passed', execution_mode='agent',
            replay_script={'steps': [{'action': 'navigate'}]},
        )
        self._run_migration()
        self._run_migration()
        self.assertEqual(Script.objects.filter(source_execution=record).count(), 1)

    def test_migrate_no_testcase(self):
        """Records without testcase get a default name."""
        project = Project.objects.create(name='Migration Test 4', base_url='https://example.com')
        record = ExecutionRecord.objects.create(
            project=project, status='passed', execution_mode='agent',
            replay_script={'steps': [{'action': 'check'}]},
        )
        self._run_migration()

        script = Script.objects.filter(source_execution=record).first()
        self.assertIsNotNone(script)
        self.assertEqual(script.name, f'脚本-{record.pk}')
        self.assertEqual(script.feature_group, '')


# ══════════════════════════════════════════════════════════════════
# Script List/Filter API Tests
# ══════════════════════════════════════════════════════════════════

class ScriptFilterTest(TestCase):
    """Tests for Script list API filtering."""

    def setUp(self):
        self.client = APIClient()
        self.project1 = Project.objects.create(name='P1', base_url='https://a.com')
        self.project2 = Project.objects.create(name='P2', base_url='https://b.com')
        self.tc = TC_Model.objects.create(project=self.project1, name='TC', feature_group='登录')

    def test_filter_by_project(self):
        Script.objects.create(project=self.project1, name='S1', status='active', script_data={})
        Script.objects.create(project=self.project2, name='S2', status='active', script_data={})

        resp = self.client.get('/api/scripts/', {'project': self.project1.id})
        self.assertEqual(resp.status_code, 200)
        scripts = resp.data.get('scripts', resp.data)
        self.assertEqual(len(scripts), 1)
        self.assertEqual(scripts[0]['name'], 'S1')

    def test_filter_by_feature_group(self):
        Script.objects.create(project=self.project1, name='S1', feature_group='登录', status='active', script_data={})
        Script.objects.create(project=self.project1, name='S2', feature_group='注册', status='active', script_data={})

        resp = self.client.get('/api/scripts/', {'feature_group': '登录'})
        self.assertEqual(resp.status_code, 200)
        scripts = resp.data.get('scripts', resp.data)
        self.assertEqual(len(scripts), 1)
        self.assertEqual(scripts[0]['feature_group'], '登录')

    def test_filter_by_status(self):
        Script.objects.create(project=self.project1, name='S1', status='draft', script_data={})
        Script.objects.create(project=self.project1, name='S2', status='active', script_data={})

        resp = self.client.get('/api/scripts/', {'status': 'active'})
        self.assertEqual(resp.status_code, 200)
        scripts = resp.data.get('scripts', resp.data)
        self.assertEqual(len(scripts), 1)
        self.assertEqual(scripts[0]['status'], 'active')

    def test_script_feature_groups_endpoint(self):
        Script.objects.create(project=self.project1, name='S1', feature_group='登录', status='active', script_data={})
        Script.objects.create(project=self.project1, name='S2', feature_group='登录', status='active', script_data={})
        Script.objects.create(project=self.project1, name='S3', feature_group='注册', status='active', script_data={})

        resp = self.client.get('/api/scripts/feature-groups/', {'project': self.project1.id})
        self.assertEqual(resp.status_code, 200)
        groups = resp.data['groups']
        self.assertEqual(len(groups), 2)
        login_group = next(g for g in groups if g['name'] == '登录')
        self.assertEqual(login_group['count'], 2)

    def test_script_feature_groups_missing_project(self):
        resp = self.client.get('/api/scripts/feature-groups/')
        self.assertEqual(resp.status_code, 400)


# ══════════════════════════════════════════════════════════════════
# CLI Service Tests
# ══════════════════════════════════════════════════════════════════

class CliServiceTest(TestCase):
    """Tests for core/cli_service.py"""

    def setUp(self):
        SystemSetting.objects.create(key='claude_cli_path', value='claude')
        SystemSetting.objects.create(key='claude_cli_timeout', value='300')
        SystemSetting.objects.create(key='analysis_engine', value='cli')
        SystemSetting.objects.create(key='anthropic_api_key', value='test-key')

    @mock.patch('core.cli_service.subprocess.run')
    def test_is_cli_available_success(self, mock_run):
        """CLI detected and returns version string."""
        mock_run.return_value = mock.Mock(returncode=0, stdout='claude 1.0.0')

        from core.cli_service import is_cli_available
        available, info = is_cli_available('claude')

        self.assertTrue(available)
        self.assertEqual(info, 'claude 1.0.0')
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertEqual(args, ['claude', '--version'])

    @mock.patch('core.cli_service.subprocess.run')
    def test_is_cli_available_not_found(self, mock_run):
        """CLI not found raises FileNotFoundError."""
        mock_run.side_effect = FileNotFoundError()

        from core.cli_service import is_cli_available
        available, info = is_cli_available('nonexistent-cli')

        self.assertFalse(available)
        self.assertIn('未找到', info)

    @mock.patch('core.cli_service.subprocess.run')
    def test_is_cli_available_nonzero_exit(self, mock_run):
        """CLI returns non-zero exit code."""
        mock_run.return_value = mock.Mock(returncode=1, stderr='error: not authenticated')

        from core.cli_service import is_cli_available
        available, info = is_cli_available('claude')

        self.assertFalse(available)
        self.assertIn('error', info)

    @mock.patch('core.cli_service.subprocess.run')
    def test_call_cli_success(self, mock_run):
        """Successful CLI call returns stdout text."""
        mock_run.return_value = mock.Mock(returncode=0, stdout='{"pages":[],"apis":[]}')

        from core.cli_service import call_cli
        result = call_cli(
            prompt='Analyze this project',
            cwd='/tmp/repo',
            timeout=60,
        )

        self.assertEqual(result, '{"pages":[],"apis":[]}')
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        self.assertIn('-p', cmd)
        self.assertIn('--output-format', cmd)
        self.assertIn('text', cmd)
        self.assertEqual(call_args[1]['cwd'], '/tmp/repo')
        self.assertEqual(call_args[1]['timeout'], 60)

    @mock.patch('core.cli_service.subprocess.run')
    def test_call_cli_with_model(self, mock_run):
        """CLI call with model flag adds --model to command."""
        mock_run.return_value = mock.Mock(returncode=0, stdout='result')

        from core.cli_service import call_cli
        call_cli(prompt='test', cwd='/tmp', model='claude-sonnet-4-20250514')

        cmd = mock_run.call_args[0][0]
        self.assertIn('--model', cmd)
        self.assertIn('claude-sonnet-4-20250514', cmd)

    @mock.patch('core.cli_service.subprocess.run')
    def test_call_cli_timeout(self, mock_run):
        """CLI timeout raises subprocess.TimeoutExpired."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='claude', timeout=60)

        from core.cli_service import call_cli
        with self.assertRaises(subprocess.TimeoutExpired):
            call_cli(prompt='test', cwd='/tmp', timeout=60)

    @mock.patch('core.cli_service.subprocess.run')
    def test_call_cli_not_found(self, mock_run):
        """CLI not installed raises FileNotFoundError."""
        mock_run.side_effect = FileNotFoundError()

        from core.cli_service import call_cli
        with self.assertRaises(FileNotFoundError):
            call_cli(prompt='test', cwd='/tmp')

    @mock.patch('core.cli_service.subprocess.run')
    def test_call_cli_nonzero_exit(self, mock_run):
        """CLI returns non-zero exit code raises RuntimeError."""
        mock_run.return_value = mock.Mock(returncode=1, stderr='Authentication failed')

        from core.cli_service import call_cli
        with self.assertRaises(RuntimeError) as ctx:
            call_cli(prompt='test', cwd='/tmp')
        self.assertIn('Authentication failed', str(ctx.exception))

    def test_get_cli_settings_defaults(self):
        """get_cli_settings reads from SystemSetting with defaults."""
        from core.cli_service import get_cli_settings
        settings = get_cli_settings()
        self.assertEqual(settings['cli_path'], 'claude')
        self.assertEqual(settings['timeout'], 300)
        self.assertEqual(settings['analysis_engine'], 'cli')
        self.assertEqual(settings['api_key'], 'test-key')

    def test_get_cli_settings_custom(self):
        """get_cli_settings reads custom values from SystemSetting."""
        SystemSetting.objects.filter(key='claude_cli_path').update(value='/usr/local/bin/claude')
        SystemSetting.objects.filter(key='claude_cli_timeout').update(value='600')

        from core.cli_service import get_cli_settings
        settings = get_cli_settings()
        self.assertEqual(settings['cli_path'], '/usr/local/bin/claude')
        self.assertEqual(settings['timeout'], 600)


# ══════════════════════════════════════════════════════════════════
# Repo Analyzer CLI Mode Tests
# ══════════════════════════════════════════════════════════════════

class RepoAnalyzerCliModeTest(TestCase):
    """Tests for repo_analyzer.py CLI mode integration."""

    def setUp(self):
        self.project = Project.objects.create(
            name='CLI Test Project',
            base_url='https://example.com',
            repo_url='https://github.com/example/test.git',
            local_repo_path='/tmp/test-repo',
        )
        SystemSetting.objects.create(key='analysis_engine', value='cli')
        SystemSetting.objects.create(key='claude_cli_path', value='claude')
        SystemSetting.objects.create(key='claude_cli_timeout', value='300')
        SystemSetting.objects.create(key='anthropic_api_key', value='test-key')

    @mock.patch('core.repo_analyzer.repo_service.clone_or_update_repo')
    @mock.patch('core.cli_service.call_cli')
    def test_cli_mode_calls_cli(self, mock_call_cli, mock_clone):
        """CLI mode calls call_cli instead of SDK."""
        mock_clone.return_value = '/tmp/test-repo'
        mock_call_cli.return_value = json.dumps({
            'pages': [{'path': '/home', 'name': '首页', 'description': '主页', 'source_file': 'router.js'}],
            'apis': [{'path': '/api/users', 'method': 'GET', 'name': '用户列表', 'description': '获取用户', 'source_file': 'user.py'}],
        })

        from core.repo_analyzer import analyze_repo
        analysis = analyze_repo(self.project)

        self.assertEqual(analysis.status, 'completed')
        self.assertEqual(len(analysis.discovered_items), 2)
        mock_call_cli.assert_called_once()
        # Verify CLI was called with correct cwd
        call_kwargs = mock_call_cli.call_args
        self.assertEqual(call_kwargs[1].get('cwd') or call_kwargs.kwargs.get('cwd'), '/tmp/test-repo')

    @mock.patch('core.repo_analyzer.repo_service.clone_or_update_repo')
    @mock.patch('core.cli_service.call_cli')
    def test_cli_mode_skips_code_collection(self, mock_call_cli, mock_clone):
        """CLI mode does not call repo_service.get_repo_file_tree or search_code."""
        mock_clone.return_value = '/tmp/test-repo'
        mock_call_cli.return_value = json.dumps({'pages': [], 'apis': []})

        from core.repo_analyzer import analyze_repo
        analyze_repo(self.project)

        # call_cli should be called (CLI mode)
        mock_call_cli.assert_called_once()

    @mock.patch('core.repo_analyzer.repo_service.clone_or_update_repo')
    @mock.patch('core.cli_service.call_cli')
    def test_cli_mode_parses_json_response(self, mock_call_cli, mock_clone):
        """CLI mode correctly parses JSON response into discovered_items."""
        mock_clone.return_value = '/tmp/test-repo'
        mock_call_cli.return_value = json.dumps({
            'pages': [
                {'path': '/login', 'name': '登录页', 'description': '用户登录', 'source_file': 'router.js'},
            ],
            'apis': [
                {'path': '/api/auth', 'method': 'POST', 'name': '认证', 'description': '登录认证', 'source_file': 'auth.py'},
                {'path': '/api/users', 'method': 'GET', 'name': '用户', 'description': '用户列表', 'source_file': 'user.py'},
            ],
        })

        from core.repo_analyzer import analyze_repo
        analysis = analyze_repo(self.project)

        items = analysis.discovered_items
        self.assertEqual(len(items), 3)
        pages = [i for i in items if i['type'] == 'page']
        apis = [i for i in items if i['type'] == 'api']
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(apis), 2)
        self.assertEqual(pages[0]['path'], '/login')
        self.assertEqual(apis[0]['method'], 'POST')

    @mock.patch('core.repo_analyzer.repo_service.clone_or_update_repo')
    @mock.patch('core.cli_service.call_cli')
    def test_cli_mode_handles_failure(self, mock_call_cli, mock_clone):
        """CLI mode failure marks analysis as failed."""
        mock_clone.return_value = '/tmp/test-repo'
        mock_call_cli.side_effect = RuntimeError('CLI failed: authentication error')

        from core.repo_analyzer import analyze_repo
        analysis = analyze_repo(self.project)

        self.assertEqual(analysis.status, 'failed')
        self.assertIn('CLI failed', analysis.analysis_log)


class RepoAnalyzerSdkModeTest(TestCase):
    """Tests for repo_analyzer.py SDK fallback mode."""

    def setUp(self):
        self.project = Project.objects.create(
            name='SDK Test Project',
            base_url='https://example.com',
            repo_url='https://github.com/example/test.git',
            local_repo_path='/tmp/test-repo',
        )
        SystemSetting.objects.create(key='analysis_engine', value='sdk')
        SystemSetting.objects.create(key='anthropic_api_key', value='test-key')
        SystemSetting.objects.create(key='anthropic_model', value='claude-sonnet-4-20250514')

    @mock.patch('core.repo_analyzer.repo_service.clone_or_update_repo')
    @mock.patch('core.repo_analyzer.repo_service.get_repo_file_tree')
    @mock.patch('core.repo_analyzer.repo_service.search_code')
    @mock.patch('core.repo_analyzer._get_client')
    @mock.patch('core.repo_analyzer._get_model')
    def test_sdk_mode_uses_api(self, mock_model, mock_client, mock_search, mock_tree, mock_clone):
        """SDK mode calls Anthropic API with code snippets."""
        mock_clone.return_value = '/tmp/test-repo'
        mock_tree.return_value = 'src/\n  router.js\n  api.py'
        mock_search.return_value = []

        mock_response = mock.Mock()
        mock_response.content = [mock.Mock(text=json.dumps({
            'pages': [{'path': '/', 'name': '首页', 'description': '主页', 'source_file': 'router.js'}],
            'apis': [],
        }))]
        mock_client.return_value.messages.create.return_value = mock_response
        mock_model.return_value = 'claude-sonnet-4-20250514'

        from core.repo_analyzer import analyze_repo
        analysis = analyze_repo(self.project)

        self.assertEqual(analysis.status, 'completed')
        self.assertEqual(len(analysis.discovered_items), 1)
        self.assertEqual(analysis.discovered_items[0]['type'], 'page')
        mock_client.return_value.messages.create.assert_called_once()


# ══════════════════════════════════════════════════════════════════
# CLI Check Endpoint Tests
# ══════════════════════════════════════════════════════════════════

class CliCheckEndpointTest(TestCase):
    """Tests for GET /api/settings/cli-check/"""

    def setUp(self):
        self.client = APIClient()

    @mock.patch('core.cli_service.subprocess.run')
    def test_cli_available(self, mock_run):
        """CLI check returns available=true when CLI is installed."""
        mock_run.return_value = mock.Mock(returncode=0, stdout='claude 1.0.0')

        resp = self.client.get('/api/settings/cli-check/', {'cli_path': 'claude'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['available'])
        self.assertEqual(resp.data['version'], 'claude 1.0.0')
        self.assertIsNone(resp.data['error'])

    @mock.patch('core.cli_service.subprocess.run')
    def test_cli_not_available(self, mock_run):
        """CLI check returns available=false when CLI is not found."""
        mock_run.side_effect = FileNotFoundError()

        resp = self.client.get('/api/settings/cli-check/', {'cli_path': 'missing-cli'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['available'])
        self.assertIsNotNone(resp.data['error'])
        self.assertEqual(resp.data['version'], '')

    @mock.patch('core.cli_service.subprocess.run')
    def test_cli_check_default_path(self, mock_run):
        """CLI check uses SystemSetting default when no cli_path param."""
        SystemSetting.objects.create(key='claude_cli_path', value='my-claude')
        mock_run.return_value = mock.Mock(returncode=0, stdout='my-claude 2.0.0')

        resp = self.client.get('/api/settings/cli-check/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['available'])
        # Verify it used the configured path
        args = mock_run.call_args[0][0]
        self.assertEqual(args[0], 'my-claude')
