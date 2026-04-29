"""
Unit tests for core views, models, and serializers.
"""
import json
from unittest import mock
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from .models import Project, TestCase as TC_Model, ExecutionRecord, AIConversation, SystemSetting


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
            {'testcase_id': self.tc.id},
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
