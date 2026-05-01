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
    path('executions/<int:pk>/steps/', views.execution_steps, name='execution-steps'),
    path('executions/<int:pk>/latest_frame/', views.execution_latest_frame, name='execution-latest-frame'),
    path('executions/screenshots/', views.serve_screenshot, name='serve-screenshot'),
    # 脚本回放
    path('executions/<int:pk>/convert-script/', views.convert_to_script, name='convert-to-script'),
    path('executions/<int:pk>/replay-script/', views.get_replay_script, name='get-replay-script'),
    path('executions/<int:pk>/replay-script/update/', views.update_replay_script, name='update-replay-script'),
    path('executions/<int:pk>/replay-execute/', views.replay_execute, name='replay-execute'),
    path('testcases/<int:testcase_id>/execute-agent/', views.execute_testcase_agent, name='testcase-execute-agent'),
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
    path('settings/cli-check/', views.cli_check, name='cli-check'),

    # 仓库分析 + 批量用例生成
    path('projects/<int:project_id>/repo/pull/', views.repo_pull, name='repo-pull'),
    path('projects/<int:project_id>/repo/analyze/', views.repo_analyze, name='repo-analyze'),
    path('projects/<int:project_id>/repo/analysis/', views.repo_analysis_detail, name='repo-analysis-detail'),
    path('projects/<int:project_id>/repo/analysis/reset/', views.repo_analysis_reset, name='repo-analysis-reset'),
    path('projects/<int:project_id>/repo/analysis/list/', views.repo_analysis_list, name='repo-analysis-list'),
    path('projects/<int:project_id>/batch-generate/', views.batch_generate_testcases, name='batch-generate'),
    path('projects/<int:project_id>/batch-save/', views.batch_save_testcases, name='batch-save'),
    path('projects/<int:project_id>/generation-draft/', views.generation_draft, name='generation-draft'),
    path('projects/<int:project_id>/testcases/reorder/', views.testcase_reorder, name='testcase-reorder'),
    path('projects/<int:project_id>/feature-groups/', views.project_feature_groups, name='feature-groups'),

    # 前置条件模板
    path('preconditions/', views.precondition_list, name='precondition-list'),
    path('preconditions/create/', views.precondition_create, name='precondition-create'),
    path('preconditions/<int:pk>/', views.precondition_update, name='precondition-update'),
    path('preconditions/<int:pk>/delete/', views.precondition_delete, name='precondition-delete'),

    # ─── Script API ───
    path('scripts/', views.script_list, name='script-list'),
    path('scripts/<int:pk>/', views.script_detail, name='script-detail'),
    path('scripts/<int:pk>/update/', views.script_update, name='script-update'),
    path('scripts/<int:pk>/delete/', views.script_delete, name='script-delete'),
    path('scripts/convert/', views.script_convert, name='script-convert'),
    path('scripts/batch-convert/', views.batch_convert_scripts, name='batch-convert-scripts'),
    path('scripts/<int:pk>/execute/', views.script_execute, name='script-execute'),
    path('scripts/feature-groups/', views.script_feature_groups, name='script-feature-groups'),

    # ─── Feature 分组执行 ───
    path('projects/<int:project_id>/features/<str:feature_group>/execute/', views.execute_feature_group, name='execute-feature-group'),

    # ─── TestPlan API ───
    path('plans/', views.plan_list, name='plan-list'),
    path('plans/create/', views.plan_create, name='plan-create'),
    path('plans/<int:pk>/', views.plan_detail, name='plan-detail'),
    path('plans/<int:pk>/update/', views.plan_update, name='plan-update'),
    path('plans/<int:pk>/delete/', views.plan_delete, name='plan-delete'),
    path('plans/<int:pk>/items/', views.plan_add_item, name='plan-add-item'),
    path('plans/<int:pk>/items/reorder/', views.plan_reorder_items, name='plan-reorder-items'),
    path('plans/items/<int:item_pk>/delete/', views.plan_delete_item, name='plan-delete-item'),
    path('plans/<int:pk>/regenerate-token/', views.plan_regenerate_token, name='plan-regenerate-token'),
    path('plans/<int:pk>/parameters/', views.plan_parameters, name='plan-parameters'),

    # ─── PlanExecution API ───
    path('plans/<int:pk>/execute/', views.plan_execute, name='plan-execute'),
    path('plan-executions/', views.plan_execution_list, name='plan-execution-list'),
    path('plan-executions/<int:pk>/', views.plan_execution_detail, name='plan-execution-detail'),
    path('plan-executions/<int:pk>/status/', views.plan_execution_status, name='plan-execution-status'),
    path('plan-executions/<int:pk>/report/', views.plan_execution_report, name='plan-execution-report'),

    # 系统
    path('health/', views.health_check, name='health-check'),
    path('stats/', views.system_stats, name='system-stats'),
]
