"""
Unit tests for core views, models, and serializers.
"""
import json
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
