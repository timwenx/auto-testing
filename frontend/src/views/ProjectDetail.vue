<template>
  <div v-loading="loading">
    <el-tabs v-model="activeTab" type="border-card" @tab-change="handleTabChange">
      <!-- ═══ 概览标签页 ═══ -->
      <el-tab-pane label="概览" name="overview">
        <div v-if="project">
          <!-- 项目信息卡片 -->
          <el-card style="margin-bottom: 16px">
            <template #header>
              <div class="card-header">
                <span>{{ project.name }}</span>
                <div>
                  <el-button size="small" @click="openProjectEditor">
                    <el-icon><Edit /></el-icon> 编辑项目
                  </el-button>
                </div>
              </div>
            </template>
            <el-descriptions :column="2" size="small">
              <el-descriptions-item label="目标 URL">{{ project.base_url || '-' }}</el-descriptions-item>
              <el-descriptions-item label="用例数">{{ testcases.length }}</el-descriptions-item>
              <el-descriptions-item label="Git 仓库">{{ project.repo_url || '-' }}</el-descriptions-item>
              <el-descriptions-item label="描述">{{ project.description || '-' }}</el-descriptions-item>
            </el-descriptions>
          </el-card>

          <!-- 快捷操作 -->
          <el-row :gutter="16" style="margin-bottom: 16px">
            <el-col :span="8">
              <el-card shadow="hover" class="quick-action-card" @click="activeTab = 'testcases'">
                <div style="text-align: center">
                  <el-icon style="font-size: 28px; color: #409eff"><Document /></el-icon>
                  <div style="margin-top: 8px; font-weight: 500">测试用例</div>
                  <div style="color: #909399; font-size: 12px; margin-top: 4px">{{ testcases.length }} 个用例</div>
                </div>
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-card shadow="hover" class="quick-action-card" @click="activeTab = 'analysis'">
                <div style="text-align: center">
                  <el-icon style="font-size: 28px; color: #67c23a"><MagicStick /></el-icon>
                  <div style="margin-top: 8px; font-weight: 500">AI 批量生成</div>
                  <div style="color: #909399; font-size: 12px; margin-top: 4px">代码分析 → 用例</div>
                </div>
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-card shadow="hover" class="quick-action-card" @click="handleExecuteAllAgent" style="cursor: pointer">
                <div style="text-align: center">
                  <el-icon style="font-size: 28px; color: #e6a23c"><Cpu /></el-icon>
                  <div style="margin-top: 8px; font-weight: 500">Agent 批量执行</div>
                  <div style="color: #909399; font-size: 12px; margin-top: 4px">一键执行全部</div>
                </div>
              </el-card>
            </el-col>
          </el-row>

          <!-- 最近执行 -->
          <el-card v-if="recentExecutions.length">
            <template #header><span>最近执行</span></template>
            <el-table :data="recentExecutions" size="small">
              <el-table-column prop="testcase_name" label="用例" show-overflow-tooltip />
              <el-table-column prop="status" label="状态" width="80">
                <template #default="{ row }">
                  <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="execution_mode" label="模式" width="80">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain">{{ row.execution_mode || 'script' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="duration" label="耗时" width="70">
                <template #default="{ row }">{{ row.duration ? row.duration + 's' : '-' }}</template>
              </el-table-column>
              <el-table-column prop="created_at" label="时间" width="160" />
            </el-table>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- ═══ 测试用例标签页 ═══ -->
      <el-tab-pane name="testcases">
        <template #label>
          <span>测试用例 <el-badge :value="testcases.length" type="info" /></span>
        </template>
        <div style="margin-bottom: 12px; display: flex; justify-content: flex-end; align-items: center">
          <div>
            <el-button size="small" type="success" @click="showAIGenerate = true">
              <el-icon><MagicStick /></el-icon> AI 生成
            </el-button>
            <el-button size="small" type="primary" @click="showCreate = true">
              <el-icon><Plus /></el-icon> 新建用例
            </el-button>
          </div>
        </div>

        <!-- 树形视图（唯一视图模式） -->
        <div style="display: flex; gap: 16px; min-height: 400px">
          <div style="width: 320px; flex-shrink: 0; border-right: 1px solid #ebeef5; padding-right: 16px">
            <FeatureTree
              :groups="featureTreeData"
              :executing-feature="executingFeature"
              @select-feature="handleTreeSelectFeature"
              @select-testcase="handleTreeSelectTestcase"
              @execute-feature="handleTreeExecuteFeature"
            />
          </div>
          <div style="flex: 1; overflow-y: auto; max-height: 70vh">
            <template v-if="treeSelection?.type === 'feature'">
              <h4 style="margin: 0 0 12px">{{ treeSelection.label || '未分组' }}</h4>
              <el-descriptions :column="2" size="small" border style="margin-bottom: 12px">
                <el-descriptions-item label="用例数">{{ treeSelection.count }}</el-descriptions-item>
                <el-descriptions-item label="操作">
                  <el-button size="small" type="primary" @click="handleTreeExecuteFeature(treeSelection.rawName)" :loading="executingFeature === treeSelection.rawName">
                    <el-icon><VideoPlay /></el-icon> 执行全部
                  </el-button>
                </el-descriptions-item>
              </el-descriptions>
              <el-table :data="treeSelection.testcases || []" size="small">
                <el-table-column prop="name" label="用例名称" min-width="180" />
                <el-table-column prop="status" label="状态" width="80">
                  <template #default="{ row }">
                    <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="240" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" text type="warning" @click="handleExecuteAgent(row)">Agent</el-button>
                    <el-button size="small" text type="success" @click="handleAgentRefine(row)">调整</el-button>
                    <el-button size="small" text @click="openCaseDrawer(row)">详情</el-button>
                    <el-button size="small" text type="danger" @click="handleDeleteTC(row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </template>
            <template v-else-if="treeSelection?.type === 'testcase'">
              <el-descriptions :column="2" size="small" border style="margin-bottom: 12px">
                <el-descriptions-item label="名称">{{ treeSelection.raw?.name }}</el-descriptions-item>
                <el-descriptions-item label="状态">
                  <el-tag :type="statusType(treeSelection.raw?.status)" size="small">{{ treeSelection.raw?.status }}</el-tag>
                </el-descriptions-item>
              </el-descriptions>
              <div style="margin-bottom: 12px">
                <el-button size="small" type="warning" @click="handleExecuteAgent(treeSelection.raw)">Agent 执行</el-button>
                <el-button size="small" type="success" @click="handleAgentRefine(treeSelection.raw)">AI 调整</el-button>
                <el-button size="small" @click="openEditor(treeSelection.raw)">编辑</el-button>
                <el-button size="small" @click="openCaseDrawer(treeSelection.raw)">查看详情</el-button>
              </div>
              <div v-if="treeSelection.raw?.markdown_content" class="markdown-body" style="max-height: 50vh" v-html="renderCaseMarkdown(treeSelection.raw.markdown_content)" />
              <el-descriptions v-else :column="1" border size="small">
                <el-descriptions-item label="描述">{{ treeSelection.raw?.description || '-' }}</el-descriptions-item>
                <el-descriptions-item label="测试步骤">
                  <pre style="white-space: pre-wrap; margin: 0">{{ treeSelection.raw?.steps }}</pre>
                </el-descriptions-item>
                <el-descriptions-item label="预期结果">
                  <pre style="white-space: pre-wrap; margin: 0">{{ treeSelection.raw?.expected_result }}</pre>
                </el-descriptions-item>
              </el-descriptions>
            </template>
            <el-empty v-else description="选择左侧功能或用例查看详情" :image-size="80" />
          </div>
        </div>
      </el-tab-pane>

      <!-- ═══ 代码分析标签页（集成 TestCaseManager 向导） ═══ -->
      <el-tab-pane label="代码分析" name="analysis">
        <!-- 步骤条 -->
        <el-card style="margin-bottom: 16px">
          <el-steps :active="wizardStep" finish-status="success" align-center>
            <el-step title="拉取仓库" />
            <el-step title="代码分析" />
            <el-step title="选择目标" />
            <el-step title="生成用例" />
            <el-step title="确认保存" />
          </el-steps>
        </el-card>

        <!-- 步骤1: 拉取仓库 -->
        <div v-if="wizardStep === 0">
          <RepoStatusCard
            :project="project"
            @ready="wizardStep = 1"
            @project-updated="data => { if (project) Object.assign(project, data) }"
          />
        </div>

        <!-- 步骤2-3: 代码分析 + 选择目标 -->
        <div v-if="wizardStep >= 1 && wizardStep <= 2">
          <CodeAnalysisPanel
            :key="'analysis-' + analysisKey"
            :project-id="projectId"
            :auto-start="wizardStep === 1"
            @analysis-complete="wizardStep = 2"
            @items-selected="onWizardItemsSelected"
            @back="wizardStep = 0"
          />
        </div>

        <!-- 步骤4: 生成用例 -->
        <div v-if="wizardStep === 3">
          <div style="display: flex; gap: 16px; align-items: flex-start">
            <div style="flex: 1">
              <BatchTestCaseEditor
                :key="'batch-' + batchKey"
                :project-id="projectId"
                :selected-items="wizardSelectedItems"
                :descriptions="wizardItemDescriptions"
                :precondition-id="wizardPreconditionId"
                :initial-cases="wizardDraftCases"
                @back="wizardStep = 2"
                @save-complete="onWizardSaveComplete"
              />
            </div>
            <div style="width: 320px; flex-shrink: 0">
              <PreconditionSelector v-model:selected-id="wizardPreconditionId" />
            </div>
          </div>
        </div>

        <!-- 步骤5: 保存完成 -->
        <div v-if="wizardStep === 4">
          <el-card>
            <el-result icon="success" title="用例保存成功" :sub-title="'已保存 ' + wizardSavedCount + ' 条测试用例'">
              <template #extra>
                <el-button type="primary" @click="wizardStep = 0; wizardSelectedItems = []; loadWizardState()">继续添加</el-button>
              </template>
            </el-result>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- ═══ 执行记录标签页 ═══ -->
      <el-tab-pane label="执行记录" name="executions">
        <el-table :data="projectExecutions" size="small" v-loading="loadingExecutions">
          <el-table-column prop="testcase_name" label="用例" min-width="180" show-overflow-tooltip />
          <el-table-column prop="execution_mode" label="模式" width="80">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ row.execution_mode || 'script' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="duration" label="耗时" width="70">
            <template #default="{ row }">{{ row.duration ? row.duration + 's' : '-' }}</template>
          </el-table-column>
          <el-table-column prop="tool_calls_count" label="工具调用" width="80">
            <template #default="{ row }">{{ row.tool_calls_count || '-' }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="时间" width="170" />
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'running'" size="small" text type="primary"
                @click="router.push({ name: 'ExecutionObserver', params: { id: row.id } })">观察</el-button>
              <el-button size="small" text type="primary" @click="openExecDrawer(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!loadingExecutions && !projectExecutions.length" description="暂无执行记录" />
      </el-tab-pane>
    </el-tabs>

    <!-- ═══ 用例详情抽屉（替代弹窗） ═══ -->
    <el-drawer v-model="showCaseDrawer" title="用例详情" size="55%" :destroy-on-close="true">
      <template v-if="drawerCase">
        <div v-if="drawerCase.markdown_content" class="markdown-body" v-html="renderCaseMarkdown(drawerCase.markdown_content)" />
        <el-descriptions v-else :column="1" border size="small">
          <el-descriptions-item label="名称">{{ drawerCase.name }}</el-descriptions-item>
          <el-descriptions-item label="描述">{{ drawerCase.description || '-' }}</el-descriptions-item>
          <el-descriptions-item label="测试步骤">
            <pre style="white-space: pre-wrap; margin: 0">{{ drawerCase.steps }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="预期结果">
            <pre style="white-space: pre-wrap; margin: 0">{{ drawerCase.expected_result }}</pre>
          </el-descriptions-item>
        </el-descriptions>
        <div style="margin-top: 16px; display: flex; gap: 8px">
          <el-button type="warning" size="small" @click="handleExecuteAgent(drawerCase); showCaseDrawer = false">Agent 执行</el-button>
          <el-button type="success" size="small" @click="handleAgentRefine(drawerCase); showCaseDrawer = false">AI 调整</el-button>
          <el-button size="small" @click="openEditor(drawerCase); showCaseDrawer = false">编辑</el-button>
        </div>
      </template>
    </el-drawer>

    <!-- ═══ 执行详情抽屉 ═══ -->
    <el-drawer v-model="showExecDrawer" title="执行详情" size="60%" :destroy-on-close="true">
      <div v-loading="execDrawerLoading">
        <template v-if="execDrawerData">
          <el-descriptions :column="2" border size="small" style="margin-bottom: 16px">
            <el-descriptions-item label="状态">
              <el-tag :type="statusType(execDrawerData.status)" size="small">{{ execDrawerData.status }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="执行模式">{{ execDrawerData.execution_mode }}</el-descriptions-item>
            <el-descriptions-item label="耗时">{{ execDrawerData.duration ? execDrawerData.duration + 's' : '-' }}</el-descriptions-item>
            <el-descriptions-item label="工具调用">{{ execDrawerData.tool_calls_count }} 次</el-descriptions-item>
            <el-descriptions-item label="AI 模型">{{ execDrawerData.ai_model || '-' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ execDrawerData.created_at }}</el-descriptions-item>
          </el-descriptions>
          <template v-if="execDrawerData.step_logs && execDrawerData.step_logs.length">
            <h4 style="margin: 16px 0 8px">执行步骤</h4>
            <el-timeline>
              <el-timeline-item v-for="step in execDrawerData.step_logs" :key="step.step_num" :timestamp="step.timestamp" placement="top">
                <el-card shadow="never" body-style="padding: 10px 14px">
                  <div style="display: flex; justify-content: space-between; align-items: center">
                    <div>
                      <el-tag size="small" effect="plain">{{ step.action }}</el-tag>
                      <span v-if="step.target" style="margin-left: 8px; font-size: 13px; color: #606266">{{ step.target }}</span>
                    </div>
                    <el-button v-if="step.screenshot_path" size="small" text type="primary"
                      @click="handlePreviewImage('/api/executions/screenshots/?path=' + encodeURIComponent(step.screenshot_path))">截图</el-button>
                  </div>
                  <div v-if="step.result" style="margin-top: 6px; font-size: 12px; color: #909399; word-break: break-all">{{ step.result }}</div>
                </el-card>
              </el-timeline-item>
            </el-timeline>
          </template>
          <ScreenshotGallery :screenshots="execDrawerData.screenshots" :show-title="true" />
          <template v-if="execDrawerData.agent_response && execDrawerData.agent_response.response_text">
            <h4 style="margin: 16px 0 8px">Agent 回复</h4>
            <div class="agent-response-box">
              <pre style="white-space: pre-wrap; margin: 0; font-size: 13px">{{ execDrawerData.agent_response.response_text }}</pre>
            </div>
          </template>
        </template>
      </div>
    </el-drawer>

    <!-- ═══ 用例编辑弹窗（保留但精简） ═══ -->
    <el-dialog v-model="showEditDialog" title="编辑用例" width="1000px" top="3vh">
      <template v-if="editingTC">
        <el-form label-width="80px" size="small">
          <el-form-item label="用例名称">
            <el-input v-model="editingTC.name" />
          </el-form-item>
          <div style="display: flex; gap: 16px">
            <el-form-item label="功能点" style="flex: 1">
              <el-autocomplete v-model="editingTC.feature_group" :fetch-suggestions="queryFeatureGroup" placeholder="输入或选择功能点" clearable style="width: 100%" />
            </el-form-item>
            <el-form-item label="排序序号" style="flex: 0 0 200px">
              <el-input-number v-model="editingTC.sort_order" :min="0" :max="9999" />
            </el-form-item>
          </div>
        </el-form>
        <div class="md-editor-layout">
          <div class="md-editor-left">
            <div class="md-editor-label">Markdown 编辑</div>
            <textarea v-model="editingTC.markdown_content" class="md-textarea" placeholder="输入 Markdown 内容..."></textarea>
          </div>
          <div class="md-editor-right">
            <div class="md-editor-label">预览</div>
            <div class="markdown-body md-preview" v-html="editPreview"></div>
          </div>
        </div>
      </template>
      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSaveTC" :loading="savingTC">保存</el-button>
      </template>
    </el-dialog>

    <!-- ═══ 新建用例弹窗 ═══ -->
    <el-dialog v-model="showCreate" title="新建测试用例" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="用例名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="功能点">
          <el-autocomplete v-model="form.feature_group" :fetch-suggestions="queryFeatureGroup" placeholder="输入或选择功能点" clearable style="width: 100%" />
        </el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="测试步骤"><el-input v-model="form.steps" type="textarea" :rows="4" placeholder="用自然语言描述测试步骤" /></el-form-item>
        <el-form-item label="预期结果"><el-input v-model="form.expected_result" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="handleCreateTC">创建</el-button>
      </template>
    </el-dialog>

    <!-- ═══ AI 生成弹窗 ═══ -->
    <el-dialog v-model="showAIGenerate" title="AI 生成测试用例" width="750px" @close="resetAIDialog">
      <template v-if="!aiGeneratedCases.length && !aiGenerating">
        <el-form label-width="80px">
          <el-form-item label="需求描述">
            <el-input v-model="aiRequirement" type="textarea" :rows="4" placeholder="描述你想测试的功能，例如：用户登录功能，需要测试正常登录、密码错误、账号不存在等场景" />
          </el-form-item>
          <el-form-item label="测试目标">
            <el-input v-model="aiTarget" placeholder="可选，指定页面/接口，如「用户登录页面」「/api/users/」" />
          </el-form-item>
        </el-form>
      </template>
      <template v-else-if="aiGenerating">
        <div style="text-align: center; padding: 40px 0">
          <el-icon class="is-loading" style="font-size: 32px; color: #409eff"><Loading /></el-icon>
          <p style="margin-top: 16px; color: #606266">AI 正在分析源码并生成测试用例，预计 30-60 秒…</p>
        </div>
      </template>
      <template v-else>
        <div style="max-height: 50vh; overflow-y: auto; margin-bottom: 16px">
          <div v-for="(tc, idx) in aiGeneratedCases" :key="idx" class="ai-case-item" @click="toggleCasePreview(idx)">
            <div class="ai-case-header">
              <span class="ai-case-name">{{ tc.name }}</span>
              <div>
                <el-tag v-if="tc.priority === 'P0'" type="danger" size="small">P0</el-tag>
                <el-tag v-else-if="tc.priority === 'P1'" type="warning" size="small">P1</el-tag>
                <el-tag v-else-if="tc.priority === 'P2'" type="info" size="small">P2</el-tag>
                <el-tag v-if="tc.test_type" size="small" effect="plain" style="margin-left: 4px">{{ tc.test_type }}</el-tag>
              </div>
            </div>
            <transition name="el-zoom-in-top">
              <div v-if="expandedCaseIdx === idx" class="ai-case-preview markdown-body" v-html="renderCaseMarkdown(tc.markdown_content)" @click.stop></div>
            </transition>
          </div>
        </div>
        <el-divider content-position="left">调整用例</el-divider>
        <el-input v-model="aiFeedback" type="textarea" :rows="3" placeholder="输入修改意见，如「增加并发测试场景」" :disabled="aiAdjusting" />
        <div style="display: flex; justify-content: flex-end; margin-top: 8px">
          <el-button size="small" @click="handleAIFeedback" :loading="aiAdjusting" :disabled="!aiFeedback">
            <el-icon><ChatDotRound /></el-icon> 发送反馈
          </el-button>
        </div>
      </template>
      <template #footer>
        <el-button @click="showAIGenerate = false">取消</el-button>
        <template v-if="aiGeneratedCases.length && !aiGenerating">
          <el-button @click="handleAIGenerate" :loading="aiGenerating">重新生成</el-button>
          <el-button type="primary" @click="handleAISaveAll" :loading="aiSaving">确认保存</el-button>
        </template>
        <template v-else-if="!aiGenerating">
          <el-button type="primary" @click="handleAIGenerate" :loading="aiGenerating">
            <el-icon><MagicStick /></el-icon> 生成
          </el-button>
        </template>
      </template>
    </el-dialog>

    <!-- ═══ Agent 用例调整对话框 ═══ -->
    <AgentRefineDialog :visible="showAgentRefine" :testcase-id="agentRefineTestcaseId" @close="showAgentRefine = false" @updated="loadData" />

    <!-- ═══ 编辑项目弹窗 ═══ -->
    <el-dialog v-model="showEditProject" title="编辑项目" width="600px">
      <el-form :model="editProjectForm" label-width="100px">
        <el-form-item label="项目名称"><el-input v-model="editProjectForm.name" /></el-form-item>
        <el-form-item label="项目描述"><el-input v-model="editProjectForm.description" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="目标 URL"><el-input v-model="editProjectForm.base_url" placeholder="测试目标网址" /></el-form-item>
        <el-form-item label="Git 仓库"><el-input v-model="editProjectForm.repo_url" placeholder="Git 仓库地址" /></el-form-item>
        <el-form-item label="仓库账号"><el-input v-model="editProjectForm.repo_username" placeholder="可选" /></el-form-item>
        <el-form-item label="仓库密码"><el-input v-model="editProjectForm.repo_password" type="password" placeholder="留空则不修改" show-password /></el-form-item>
        <el-form-item label="GitHub 地址"><el-input v-model="editProjectForm.github_url" placeholder="可选" /></el-form-item>
        <el-form-item label="GitHub Token"><el-input v-model="editProjectForm.github_token" type="password" placeholder="留空则不修改" show-password /></el-form-item>
        <el-form-item label="本地仓库路径"><el-input v-model="editProjectForm.local_repo_path" placeholder="可选，本地克隆路径" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditProject = false">取消</el-button>
        <el-button type="primary" @click="handleSaveProject" :loading="savingProject">保存</el-button>
      </template>
    </el-dialog>

    <!-- 图片预览 -->
    <el-dialog v-model="showImagePreview" title="截图预览" width="70%">
      <div style="text-align: center"><el-image :src="previewImage" fit="contain" style="max-height: 70vh" /></div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import {
  getProject, updateProject, getProjectTestCases, createTestCase,
  updateTestCase, deleteTestCase,
  executeTestCaseAgent, executeProjectAgent,
  aiGenerateTestCase, aiAdjustTestCase,
  getExecutions,
  reorderTestcases, getFeatureGroups, getFeatureGroupsDetail, executeFeatureGroup,
  getGenerationDraft, saveGenerationDraft, clearGenerationDraft,
  getRepoAnalysis,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import AgentRefineDialog from './AgentRefineDialog.vue'
import ScreenshotGallery from '../components/ScreenshotGallery.vue'
import FeatureTree from '../components/FeatureTree.vue'
import RepoStatusCard from '../components/RepoStatusCard.vue'
import CodeAnalysisPanel from '../components/CodeAnalysisPanel.vue'
import PreconditionSelector from '../components/PreconditionSelector.vue'
import BatchTestCaseEditor from '../components/BatchTestCaseEditor.vue'

const route = useRoute()
const router = useRouter()
const projectId = route.params.id

// ─── Tabs & Loading ───
const activeTab = ref('overview')
const loading = ref(false)
const project = ref(null)
const testcases = ref([])
const recentExecutions = ref([])
const projectExecutions = ref([])
const loadingExecutions = ref(false)

// ─── Testcase list state ───
const featureGroups = ref([])
const featureTreeData = ref([])
const treeSelection = ref(null)
const executingFeature = ref('')

// ─── Dialog states ───
const showCreate = ref(false)
const showEditDialog = ref(false)
const editingTC = ref(null)
const savingTC = ref(false)
const showAgentRefine = ref(false)
const agentRefineTestcaseId = ref(null)
const showEditProject = ref(false)
const savingProject = ref(false)
const editProjectForm = ref({ name: '', description: '', base_url: '', repo_url: '', repo_username: '', repo_password: '', github_url: '', github_token: '', local_repo_path: '' })
const showImagePreview = ref(false)
const previewImage = ref('')

// ─── Drawer states ───
const showCaseDrawer = ref(false)
const drawerCase = ref(null)
const showExecDrawer = ref(false)
const execDrawerData = ref(null)
const execDrawerLoading = ref(false)

// ─── AI generation state ───
const showAIGenerate = ref(false)
const aiGenerating = ref(false)
const aiRequirement = ref('')
const aiTarget = ref('')
const aiGeneratedCases = ref([])
const aiTestcaseIds = ref([])
const aiConversationId = ref(null)
const aiFeedback = ref('')
const aiAdjusting = ref(false)
const aiSaving = ref(false)
const expandedCaseIdx = ref(-1)
const executingAllAgent = ref(false)

// ─── Wizard (code analysis) state ───
const wizardStep = ref(0)
const wizardSelectedItems = ref([])
const wizardItemDescriptions = ref({})
const wizardPreconditionId = ref(null)
const wizardSavedCount = ref(0)
const wizardDraftCases = ref(null)
const analysisKey = ref(0)
const batchKey = ref(0)

// ─── Form ───
const form = ref({ name: '', description: '', steps: '', expected_result: '', feature_group: '' })

// ─── Computed ───
marked.setOptions({ breaks: true, gfm: true })

const editPreview = computed(() => {
  if (!editingTC.value?.markdown_content) return '<span style="color:#999">预览区域</span>'
  return marked.parse(editingTC.value.markdown_content)
})

const featureGroupSuggestions = computed(() => {
  return featureGroups.value.filter(g => g.name !== '未分组').map(g => ({ value: g.name }))
})

// ─── Status helpers ───
const statusType = (s) => {
  const map = { draft: 'info', ready: '', running: 'warning', passed: 'success', failed: 'danger' }
  return map[s] || 'info'
}

const renderCaseMarkdown = (md) => md ? marked.parse(md) : ''

// ─── Data loading ───
const loadData = async () => {
  loading.value = true
  try {
    const [p, tc, fg, fgd] = await Promise.all([
      getProject(projectId),
      getProjectTestCases(projectId),
      getFeatureGroups(projectId),
      getFeatureGroupsDetail(projectId),
    ])
    project.value = p.data
    testcases.value = tc.data.results || tc.data
    featureGroups.value = fg.data.groups || []
    featureTreeData.value = fgd.data.groups || []
  } finally {
    loading.value = false
  }
}

const loadRecentExecutions = async () => {
  try {
    const { data } = await getExecutions({ project: projectId, page_size: 5 })
    recentExecutions.value = data.results || data
  } catch { /* ignore */ }
}

const loadProjectExecutions = async () => {
  loadingExecutions.value = true
  try {
    const { data } = await getExecutions({ project: projectId })
    projectExecutions.value = data.results || data
  } finally {
    loadingExecutions.value = false
  }
}

// ─── Tab change ───
function handleTabChange(tab) {
  if (tab === 'executions') loadProjectExecutions()
}

// ─── Testcase CRUD ───
const handleCreateTC = async () => {
  if (!form.value.name) return ElMessage.warning('请输入用例名称')
  await createTestCase({ ...form.value, project: parseInt(projectId) })
  ElMessage.success('创建成功')
  showCreate.value = false
  form.value = { name: '', description: '', steps: '', expected_result: '', feature_group: '' }
  await loadData()
}

const handleDeleteTC = async (row) => {
  await ElMessageBox.confirm(`确认删除用例「${row.name}」？`, '提示', { type: 'warning' })
  await deleteTestCase(row.id)
  ElMessage.success('已删除')
  await loadData()
}

const handleSaveTC = async () => {
  if (!editingTC.value) return
  savingTC.value = true
  try {
    await updateTestCase(editingTC.value.id, {
      name: editingTC.value.name,
      feature_group: editingTC.value.feature_group,
      sort_order: editingTC.value.sort_order,
      markdown_content: editingTC.value.markdown_content,
    })
    ElMessage.success('保存成功')
    showEditDialog.value = false
    loadData()
  } catch { ElMessage.error('保存失败') } finally { savingTC.value = false }
}

function openEditor(row) {
  editingTC.value = {
    id: row.id,
    name: row.name,
    feature_group: row.feature_group || '',
    sort_order: row.sort_order || 0,
    markdown_content: row.markdown_content || `## 测试步骤\n\n${row.steps || ''}\n\n## 预期结果\n\n${row.expected_result || ''}`,
  }
  showEditDialog.value = true
}

function openCaseDrawer(row) {
  drawerCase.value = row
  showCaseDrawer.value = true
}

// ─── Execution ───
const handleExecuteAgent = async (row) => {
  try {
    const { data } = await executeTestCaseAgent(row.id)
    ElMessage.success('Agent 执行已提交')
    row.status = 'running'
    const testRunId = data.test_run_id || data.id
    if (testRunId) router.push({ name: 'ExecutionObserver', params: { id: testRunId } })
  } catch (e) { ElMessage.error(e.response?.data?.error || 'Agent 执行失败') }
}

const handleExecuteAllAgent = async () => {
  executingAllAgent.value = true
  try {
    const { data } = await executeProjectAgent(projectId)
    ElMessage.success(`已提交 ${data.length} 个 Agent 执行`)
    await loadData()
    if (data.length > 0) {
      const firstId = data[0].test_run_id || data[0].id
      if (firstId) router.push({ name: 'ExecutionObserver', params: { id: firstId } })
    }
  } catch (e) { ElMessage.error(e.response?.data?.error || 'Agent 执行失败') } finally { executingAllAgent.value = false }
}

const handleAgentRefine = (row) => {
  agentRefineTestcaseId.value = row.id
  showAgentRefine.value = true
}

// ─── AI generation ───
const handleAIGenerate = async () => {
  if (!aiRequirement.value) return ElMessage.warning('请输入需求描述')
  aiGenerating.value = true
  aiGeneratedCases.value = []
  aiConversationId.value = null
  try {
    const { data } = await aiGenerateTestCase({
      project_id: parseInt(projectId),
      requirement: aiRequirement.value,
      target: aiTarget.value || '',
    })
    aiGeneratedCases.value = data.testcases || []
    aiTestcaseIds.value = (data.testcases || []).map(tc => tc.id)
    aiConversationId.value = data.conversation_id || null
    if (aiGeneratedCases.value.length) {
      ElMessage.success(`AI 生成了 ${aiGeneratedCases.value.length} 个测试用例`)
      try {
        await saveGenerationDraft(projectId, {
          status: 'generated', conversation_id: aiConversationId.value,
          testcase_ids: aiTestcaseIds.value, testcase_names: aiGeneratedCases.value.map(tc => tc.name),
          requirement: aiRequirement.value, target: aiTarget.value, generated_at: new Date().toISOString(),
        })
      } catch { /* ignore */ }
    }
  } catch (e) { ElMessage.error(e.response?.data?.error || 'AI 生成失败') } finally { aiGenerating.value = false }
}

const handleAIFeedback = async () => {
  if (!aiFeedback.value) return
  aiAdjusting.value = true
  try {
    const currentCases = aiGeneratedCases.value.map(tc => ({
      name: tc.name, description: tc.description || '', steps: tc.steps || '',
      expected_result: tc.expected_result || '', priority: tc.priority || '',
      test_type: tc.test_type || '', feature_group: tc.feature_group || '', markdown_content: tc.markdown_content || '',
    }))
    const { data } = await aiAdjustTestCase({
      project_id: parseInt(projectId), conversation_id: aiConversationId.value,
      user_feedback: aiFeedback.value, current_cases: currentCases, testcase_ids: aiTestcaseIds.value,
    })
    aiGeneratedCases.value = data.testcases || []
    aiConversationId.value = data.conversation_id || aiConversationId.value
    aiFeedback.value = ''
    expandedCaseIdx.value = -1
    ElMessage.success('用例已更新')
    try {
      await saveGenerationDraft(projectId, {
        status: 'adjusted', conversation_id: aiConversationId.value,
        testcase_ids: (data.testcases || []).map(tc => tc.id),
        testcase_names: (data.testcases || []).map(tc => tc.name),
        requirement: aiRequirement.value, target: aiTarget.value, generated_at: new Date().toISOString(),
      })
    } catch { /* ignore */ }
  } catch (e) { ElMessage.error(e.response?.data?.error || 'AI 调整失败') } finally { aiAdjusting.value = false }
}

const handleAISaveAll = async () => {
  if (!aiGeneratedCases.value.length) return
  aiSaving.value = true
  try {
    const count = aiGeneratedCases.value.length
    await loadData()
    showAIGenerate.value = false
    resetAIDialog()
    try { await clearGenerationDraft(projectId) } catch { /* ignore */ }
    ElMessage.success(`已保存 ${count} 个测试用例`)
  } finally { aiSaving.value = false }
}

const resetAIDialog = () => {
  aiGeneratedCases.value = []
  aiTestcaseIds.value = []
  aiConversationId.value = null
  aiFeedback.value = ''
  aiTarget.value = ''
  expandedCaseIdx.value = -1
}

const toggleCasePreview = (idx) => { expandedCaseIdx.value = expandedCaseIdx.value === idx ? -1 : idx }

// ─── Execution drawer ───
async function openExecDrawer(row) {
  execDrawerData.value = null
  execDrawerLoading.value = true
  showExecDrawer.value = true
  try {
    const { data } = await getExecutions({ testcase: row.testcase || row.id })
    const records = data.results || data
    if (records.length > 0) execDrawerData.value = records[0]
  } catch { /* ignore */ } finally { execDrawerLoading.value = false }
}

const handlePreviewImage = (src) => { previewImage.value = src; showImagePreview.value = true }

// ─── Project editing ───
function openProjectEditor() {
  editProjectForm.value = {
    name: project.value.name || '', description: project.value.description || '',
    base_url: project.value.base_url || '', repo_url: project.value.repo_url || '',
    repo_username: project.value.repo_username || '', repo_password: '',
    github_url: project.value.github_url || '', github_token: '',
    local_repo_path: project.value.local_repo_path || '',
  }
  showEditProject.value = true
}

async function handleSaveProject() {
  if (!editProjectForm.value.name) return ElMessage.warning('请输入项目名称')
  savingProject.value = true
  try {
    const data = { ...editProjectForm.value }
    if (!data.repo_password) delete data.repo_password
    if (!data.github_token) delete data.github_token
    await updateProject(projectId, data)
    ElMessage.success('项目信息已更新')
    showEditProject.value = false
    await loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '更新失败') } finally { savingProject.value = false }
}

// ─── Tree view handlers ───
function handleTreeSelectFeature(rawName) {
  const group = featureTreeData.value.find(g => (g.name === '未分组' ? '' : g.name) === rawName)
  if (group) treeSelection.value = { type: 'feature', label: group.name, rawName, count: group.count, testcases: group.testcases || [] }
}
function handleTreeSelectTestcase(tc) { treeSelection.value = { type: 'testcase', label: tc.name, raw: tc } }

async function handleTreeExecuteFeature(featureGroup) {
  if (!featureGroup && featureGroup !== '') return
  executingFeature.value = featureGroup
  try {
    const { data } = await executeFeatureGroup(projectId, featureGroup)
    ElMessage.success(`功能分组执行已提交，${data.submitted || 0} 个用例`)
    await loadData()
  } catch (e) { ElMessage.error(e.response?.data?.error || '功能分组执行失败') } finally { executingFeature.value = '' }
}

function queryFeatureGroup(queryString, cb) {
  const results = queryString ? featureGroupSuggestions.value.filter(s => s.value.toLowerCase().includes(queryString.toLowerCase())) : featureGroupSuggestions.value
  cb(results)
}

// ─── Wizard (code analysis) handlers ───
function onWizardItemsSelected(items, descriptions) {
  wizardSelectedItems.value = items
  wizardItemDescriptions.value = descriptions
  wizardStep.value = 3
}

function onWizardSaveComplete(count) {
  wizardSavedCount.value = count
  wizardStep.value = 4
}

async function loadWizardState() {
  wizardDraftCases.value = null
  wizardSelectedItems.value = []
  wizardItemDescriptions.value = {}
  wizardPreconditionId.value = null
  analysisKey.value++
  batchKey.value++

  if (!project.value?.local_repo_path) { wizardStep.value = 0; return }

  // Check for generation draft
  try {
    const { data } = await getGenerationDraft(projectId)
    const draft = data.draft || {}
    if (draft.generated_cases && draft.generated_cases.length) {
      wizardDraftCases.value = draft.generated_cases
      wizardSelectedItems.value = draft.selected_items || []
      wizardItemDescriptions.value = draft.descriptions || {}
      wizardPreconditionId.value = draft.precondition_id || null
      wizardStep.value = 3
      return
    }
  } catch { /* ignore */ }

  // Check repo analysis state
  try {
    const { data } = await getRepoAnalysis(projectId)
    const analysis = data.analysis
    if (!analysis) return
    if (analysis.status === 'analyzing') { wizardStep.value = 1; return }
    if (analysis.status === 'completed') { wizardStep.value = 2; return }
    if (analysis.status === 'failed') { wizardStep.value = 1; return }
  } catch { /* ignore */ }
}

// ─── Lifecycle ───
onMounted(async () => {
  await loadData()
  await loadRecentExecutions()
  await loadWizardState()

  // Check for persisted AI generation draft
  try {
    const { data } = await getGenerationDraft(projectId)
    const draft = data.draft || {}
    if (draft.status && draft.conversation_id) {
      aiConversationId.value = draft.conversation_id
      aiTestcaseIds.value = draft.testcase_ids || []
      aiRequirement.value = draft.requirement || ''
      aiTarget.value = draft.target || ''
      if (draft.testcase_ids && draft.testcase_ids.length) {
        const tcResults = []
        for (const tcId of draft.testcase_ids) {
          try {
            const tcRes = await import('../api').then(m => m.getTestCase(tcId))
            tcResults.push(tcRes.data)
          } catch { /* testcase may have been deleted */ }
        }
        if (tcResults.length) {
          aiGeneratedCases.value = tcResults
          showAIGenerate.value = true
          ElMessage.info(`已恢复上次未保存的 ${tcResults.length} 个 AI 生成用例`)
        } else {
          await clearGenerationDraft(projectId)
        }
      }
    }
  } catch { /* ignore */ }
})
</script>

<style scoped>
.quick-action-card {
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.quick-action-card:hover {
  border-color: #409eff;
  box-shadow: 0 2px 12px rgba(64, 158, 255, 0.15);
}
.markdown-body {
  max-height: 65vh;
  overflow-y: auto;
  padding: 16px;
  line-height: 1.6;
}
.markdown-body :deep(h1) { font-size: 1.5em; border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; margin-bottom: 16px; }
.markdown-body :deep(h2) { font-size: 1.3em; border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; margin: 24px 0 12px; }
.markdown-body :deep(h3) { font-size: 1.1em; margin: 18px 0 8px; }
.markdown-body :deep(table) { width: 100%; border-collapse: collapse; margin: 12px 0; }
.markdown-body :deep(th), .markdown-body :deep(td) { border: 1px solid #dfe2e5; padding: 8px 12px; text-align: left; }
.markdown-body :deep(th) { background-color: #f6f8fa; font-weight: 600; }
.markdown-body :deep(code) { background-color: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }
.markdown-body :deep(pre) { background-color: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }
.markdown-body :deep(pre code) { background: none; padding: 0; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 24px; margin: 8px 0; }
.markdown-body :deep(blockquote) { border-left: 4px solid #dfe2e5; padding: 0 16px; color: #6a737d; margin: 12px 0; }
.ai-case-item { border: 1px solid #e4e7ed; border-radius: 6px; margin-bottom: 8px; cursor: pointer; transition: border-color 0.2s; }
.ai-case-item:hover { border-color: #409eff; }
.ai-case-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; }
.ai-case-name { font-weight: 500; font-size: 14px; }
.ai-case-preview { border-top: 1px solid #ebeef5; padding: 12px; max-height: 40vh; overflow-y: auto; background-color: #fafafa; cursor: default; }
.agent-response-box { background-color: #f6f8fa; border: 1px solid #e4e7ed; border-radius: 6px; padding: 12px; max-height: 200px; overflow-y: auto; }
.md-editor-layout { display: flex; gap: 12px; margin-top: 12px; }
.md-editor-left { flex: 1; display: flex; flex-direction: column; }
.md-editor-right { flex: 1; display: flex; flex-direction: column; }
.md-editor-label { font-size: 12px; color: #909399; margin-bottom: 6px; font-weight: 600; }
.md-textarea {
  flex: 1; min-height: 400px; padding: 12px; border: 1px solid #dcdfe6; border-radius: 4px;
  font-family: 'Consolas', 'Monaco', monospace; font-size: 13px; line-height: 1.6; resize: vertical; outline: none;
}
.md-textarea:focus { border-color: #409eff; }
.md-preview { flex: 1; min-height: 400px; padding: 12px; border: 1px solid #e4e7ed; border-radius: 4px; overflow-y: auto; background: #fafafa; }
.card-header { display: flex; justify-content: space-between; align-items: center; }

@media (max-width: 768px) {
  .md-editor-layout {
    flex-direction: column;
  }
}
</style>
