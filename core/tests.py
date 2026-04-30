"""
Unit tests for core views, models, and serializers.
"""
import json
import os
import tempfile
import threading
from unittest import mock
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from .models import Project, TestCase as TC_Model, ExecutionRecord, AIConversation, SystemSetting, Screenshot
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
        resp = self.client.post(f'/api/testcases/{tc.id}/execute/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('URL', resp.data['error'])

    def test_execute_nonexistent_testcase(self):
        resp = self.client.post('/api/testcases/99999/execute/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_execute_all_no_testcases(self):
        empty_project = Project.objects.create(name='Empty', base_url='https://example.com')
        resp = self.client.post(f'/api/projects/{empty_project.id}/execute-all/')
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
        self.assertEqual(self.record.log, 'ok')
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
    """_save_script_result 辅助函数测试"""

    def test_saves_basic_fields(self):
        p = Project.objects.create(name='P', base_url='https://a.com')
        tc = TC_Model.objects.create(project=p, name='TC', steps='s', expected_result='r')
        record = ExecutionRecord.objects.create(project=p, testcase=tc, status='running')
        result = {'status': 'passed', 'log': 'ok', 'error_message': '', 'duration': 3.1}
        from .views import _save_script_result
        _save_script_result(record, result)
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
        resp = self.client.post(
            '/api/agent/execute/',
            {'testcase_id': self.tc.id, 'execution_mode': 'script'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.data['execution_mode'], 'script')
        mock_submit.assert_not_called()

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

    @mock.patch('core.execution_engine.execute_testcase_async')
    def test_execute_all_creates_records(self, mock_exec):
        TC_Model.objects.create(project=self.project, name='A', steps='s', expected_result='r', status='draft')
        TC_Model.objects.create(project=self.project, name='B', steps='s', expected_result='r', status='ready')
        resp = self.client.post(f'/api/projects/{self.project.id}/execute-all/')
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        # resp.data may be a ReturnList (list) — handle both
        results = resp.data if isinstance(resp.data, list) else resp.data.get('results', resp.data)
        self.assertEqual(len(results), 2)
        self.assertEqual(mock_exec.call_count, 2)

    def test_execute_all_no_url(self):
        self.project.base_url = ''
        self.project.save()
        TC_Model.objects.create(project=self.project, name='A', steps='s', expected_result='r')
        resp = self.client.post(f'/api/projects/{self.project.id}/execute-all/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_execute_all_no_testcases(self):
        resp = self.client.post(f'/api/projects/{self.project.id}/execute-all/')
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
        self.assertEqual(steps[0]['action'], 'browser_navigate')
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
        long_output = 'x' * 500
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
        self.assertLessEqual(len(steps[0]['result']), 300)


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

    @mock.patch('asgiref.sync.async_to_sync')
    @mock.patch('channels.layers.get_channel_layer')
    def test_emit_calls_group_send(self, mock_get_layer, mock_async_to_sync):
        """正常推送事件到 channel group"""
        from .event_emitter import _emit_step_event
        mock_layer = mock.MagicMock()
        mock_get_layer.return_value = mock_layer
        mock_sync_fn = mock.MagicMock()
        mock_async_to_sync.return_value = mock_sync_fn

        _emit_step_event(42, 'step_complete', {'step_num': 1, 'action': 'browser_click'})

        mock_get_layer.assert_called_once()
        mock_async_to_sync.assert_called_once_with(mock_layer.group_send)

    @mock.patch('asgiref.sync.async_to_sync')
    @mock.patch('channels.layers.get_channel_layer')
    def test_emit_group_name(self, mock_get_layer, mock_async_to_sync):
        """验证 group name 格式"""
        from .event_emitter import _emit_step_event
        mock_layer = mock.MagicMock()
        mock_get_layer.return_value = mock_layer
        mock_sync_fn = mock.MagicMock()
        mock_async_to_sync.return_value = mock_sync_fn

        _emit_step_event(99, 'execution_end', {'status': 'completed'})

        # group_send 通过 async_to_sync 包装后，被调用时参数为 (group_name, payload)
        call_args = mock_sync_fn.call_args
        self.assertEqual(call_args[0][0], 'execution_99')

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

    @mock.patch('asgiref.sync.async_to_sync')
    @mock.patch('channels.layers.get_channel_layer')
    def test_emit_payload_format(self, mock_get_layer, mock_async_to_sync):
        """验证推送数据包含 type 和 timestamp"""
        from .event_emitter import _emit_step_event
        mock_layer = mock.MagicMock()
        mock_get_layer.return_value = mock_layer
        mock_sync_fn = mock.MagicMock()
        mock_async_to_sync.return_value = mock_sync_fn

        _emit_step_event(1, 'step_complete', {'step_num': 3, 'action': 'browser_fill'})

        # async_to_sync(group_send) 被调用时参数为 (group_name, payload)
        payload = mock_sync_fn.call_args[0][1]
        self.assertEqual(payload['type'], 'step_event')
        self.assertIn('data', payload)
        self.assertEqual(payload['data']['type'], 'step_complete')
        self.assertEqual(payload['data']['step_num'], 3)
        self.assertIn('timestamp', payload['data'])


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
        result = _extract_target('read_file', {'file_path': '/src/index.js'})
        self.assertEqual(result, '/src/index.js')

    def test_search_code(self):
        from .agent_service import _extract_target
        result = _extract_target('search_code', {'query': 'login'})
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

    @mock.patch('core.event_emitter._emit_step_event')
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

    @mock.patch('core.event_emitter._emit_step_event')
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

    @mock.patch('core.event_emitter._emit_step_event')
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

    @mock.patch('core.event_emitter._emit_step_event')
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


# ══════════════════════════════════════════════════════════════════
# ExecutionConsumer 测试
# ══════════════════════════════════════════════════════════════════

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
