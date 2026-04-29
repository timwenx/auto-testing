from django.urls import path
from . import views

urlpatterns = [
    # 项目
    path('projects/', views.ProjectListCreateView.as_view(), name='project-list'),
    path('projects/<int:pk>/', views.ProjectDetailView.as_view(), name='project-detail'),

    # 测试用例
    path('testcases/', views.TestCaseListCreateView.as_view(), name='testcase-list'),
    path('testcases/<int:pk>/', views.TestCaseDetailView.as_view(), name='testcase-detail'),
    path('projects/<int:project_id>/testcases/', views.ProjectTestCaseListView.as_view(), name='project-testcases'),

    # 执行记录
    path('executions/', views.ExecutionRecordListView.as_view(), name='execution-list'),
    path('executions/<int:pk>/', views.ExecutionRecordDetailView.as_view(), name='execution-detail'),
    path('testcases/<int:testcase_id>/execute/', views.execute_testcase, name='testcase-execute'),
    path('testcases/<int:testcase_id>/execute-agent/', views.execute_testcase_agent, name='testcase-execute-agent'),
    path('projects/<int:project_id>/execute-all/', views.execute_project, name='project-execute-all'),
    path('projects/<int:project_id>/execute-agent/', views.execute_project_agent, name='project-execute-agent'),

    # AI 对话
    path('ai/conversations/', views.AIConversationListView.as_view(), name='ai-conversations'),
    path('ai/generate-testcase/', views.ai_generate_testcase, name='ai-generate-testcase'),
    path('ai/analyze-result/', views.ai_analyze_result, name='ai-analyze-result'),
    path('ai/adjust-testcase/', views.ai_adjust_testcase, name='ai-adjust-testcase'),

    # Agent API
    path('agent/generate/', views.agent_generate, name='agent-generate'),
    path('agent/refine/', views.agent_refine, name='agent-refine'),
    path('agent/confirm/', views.agent_confirm, name='agent-confirm'),
    path('agent/execute/', views.agent_execute, name='agent-execute'),

    # 系统设置
    path('settings/', views.settings_view, name='settings'),

    # 系统
    path('health/', views.health_check, name='health-check'),
    path('stats/', views.system_stats, name='system-stats'),
]
