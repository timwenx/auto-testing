# 执行观察系统改进方案

## 一、当前问题

### 1.1 WebSocket 事件循环空转
观察页面连接 `/ws/execution/<id>/` 后，在没有实际执行步骤时，会持续收到三类无意义消息：
- `connection_established` → 带上 `execution_status: "running"` 后就没了
- `heartbeat` → 服务端每 15s 发一次，纯保活
- `ping` / `pong` → 前端每 20s 发一次，纯保活

**问题**：客户端一直"等待步骤事件"和"等待浏览器启动"，UI 没有任何实质内容，用户不知道在等什么。

### 1.2 两种进入场景未区分
访问 `/executions/:id/observe` 有两种来源：
1. **从历史执行记录进入**（执行已完成）→ 应该直接展示历史步骤 + 截图，可回放
2. **从 Agent 执行时实时跳转进入**（执行刚开始/进行中）→ 应该从 0 开始逐步接收

目前两种场景走同一个初始化逻辑（先 REST 拉步骤，再判断是否 WS 连接），没有做差异处理。

### 1.3 截图流和执行事件混在同一个 WS
- `browser_frame` 通知、`frame_heartbeat` 和步骤事件走同一个 channel group
- 截图通知频率高（500ms 一次），会干扰步骤事件的接收
- 截图最终通过 HTTP `/latest_frame/` 拉取，但通知占用 WS 带宽

### 1.4 执行记录在结束后才批量写入 DB
- `execute_testcase_with_agent()` 在 Agent 整个循环结束后才返回结果
- `_save_agent_result()` 一次性把 `step_logs`、`screenshots`、`agent_response` 写入 `ExecutionRecord`
- **问题**：执行过程中页面刷新或 WS 断线重连，REST 查不到任何中间步骤，回填失败

---

## 二、改进方案

### 2.1 步骤实时写入 DB（核心改动）

**现状**：Agent 执行完所有步骤后，一次性把 `step_logs` 写入 `ExecutionRecord.step_logs`（JSONField）。

**改为**：每完成一个工具调用，立即写入 DB。

**实现思路**：
- 在 `AgentRunner.run()` 循环中，每次工具执行完成后，调用一个 `_persist_step()` 方法
- 将已完成步骤追加到 `ExecutionRecord.step_logs`（读-追加-写）
- 同时更新 `ExecutionRecord.tool_calls_count`
- 如果工具产生了截图，立即创建 `Screenshot` 记录并保存文件
- 执行结束时 `_save_agent_result()` 只更新最终状态、duration、agent_response

**涉及文件**：
- `core/agent_service.py` → `AgentRunner.run()` 循环中加 `_persist_step()`
- `core/execution_engine.py` → 移除 `_build_step_logs()` / `_extract_screenshots()` 的后置逻辑
- `core/views.py` → `_save_agent_result()` 简化，只负责最终状态
- `core/models.py` → 无需改动，现有字段已够

### 2.2 两种进入场景差异化处理

**场景 A：从历史记录进入（执行已完成）**
```
页面加载 → REST GET /api/executions/:id/steps/ → 拿到全部 step_logs
         → REST GET /api/executions/:id/ → 拿到 status=passed/failed
         → 展示历史步骤 + 截图画廊
         → 不建立 WS 连接
         → 自动展示"回放"按钮
```

**场景 B：从 Agent 执行时跳转进入（执行刚开始/进行中）**
```
页面加载 → REST GET /api/executions/:id/ → status=running/pending
         → REST GET /api/executions/:id/steps/ → 拿到已完成的步骤（可能为空）
         → 建立 WS 连接 → 开始接收实时步骤
         → 截图流连接（见 2.3）
```

**前端改动**：
- `ExecutionObserver.vue` 的 `onMounted` 逻辑根据 `executionInfo.status` 分支
- 已结束的执行：不调用 `connect()`，直接填充步骤数据，显示回放面板
- 运行中的执行：先 REST 回填已有步骤，再 WS 连接接收后续

### 2.3 截图流独立 WS 连接

**现状**：截图通知（`browser_frame` / `frame_heartbeat`）和步骤事件混在同一个 WS。

**改为**：截图流使用独立 WS 连接 `/ws/screenshots/<execution_id>/`。

**理由**：
- 步骤事件是低频、高价值的（每个工具调用一次），不能丢
- 截图通知是高频、可丢弃的（500ms 一次，丢几帧无所谓）
- 分开后可以独立控制 QoS：步骤 WS 保序保送达，截图 WS 允许丢帧

**实现思路**：
- 新增 `ScreenshotConsumer`，专用通道 `screenshots_{id}`
- `ScreenshotStream.maybe_capture()` 和 `_FrameWatchdog` 改用新通道推送
- 前端 `useExecutionObserver.js` 拆分为两个 WS 管理
- 或者更简单：保持现有 WS，但前端根据 `type` 分流到不同 handler，降低截图通知的优先级

**更轻量的替代方案**（推荐）：
不新建 WS，而是在前端对 `browser_frame` / `frame_heartbeat` 做 debounce，降低处理频率。后端保持不变。

### 2.4 固定时长截图 + 截图持久化

**现状**：
- 截图只在 Agent 调用 `browser_screenshot` 工具时产生持久化文件
- 实时截图流（`ScreenshotStream`）只存内存，不落盘，执行结束即丢失

**改为**：
- 执行过程中，每 N 秒（如 3-5 秒）自动截一张图并持久化到 `media/screenshots/`
- 截图和步骤关联（通过 timestamp 或 step_num 近似匹配）
- 执行结束后，截图画廊可以展示完整时间线

**实现思路**：
- `ScreenshotStream.maybe_capture()` 中增加持久化逻辑
- 每次截图除了存内存，同时写文件到 `media/screenshots/{project_id}/{execution_id}/`
- 创建 `Screenshot` 记录（step_num 可留空，标记为 `auto_captured=True`）
- 配置项：`screenshot_interval`（截图间隔，默认 3s）、`screenshot_quality`（JPEG 质量）

**涉及文件**：
- `core/screenshot_stream.py` → `maybe_capture()` 增加文件保存
- `core/models.py` → `Screenshot` 模型加 `auto_captured` 字段
- `core/views.py` → 截图列表 API 返回所有截图（含自动截图）
- 前端 `ScreenshotGallery.vue` → 展示完整截图时间线

### 2.5 WS 连接状态优化

**现状**：连接后只有 `connection_established` + 心跳，用户看不到有意义的进度。

**改为**：增加执行阶段状态推送，让用户知道当前在干什么。

**新增事件类型**：
```json
{ "type": "phase_change", "phase": "initializing_browser" }
{ "type": "phase_change", "phase": "browser_ready" }
{ "type": "phase_change", "phase": "executing_step", "step_num": 1 }
{ "type": "phase_change", "phase": "waiting_for_claude" }
```

**前端**：根据 `phase` 展示不同的状态提示，比如"正在启动浏览器..."、"正在等待 Claude 响应..."。

**涉及文件**：
- `core/agent_service.py` → `_emit_step_event` 新增 `phase_change` 事件
- `core/consumers.py` → 无需改动（透传）
- 前端 `useExecutionObserver.js` → `_handleEvent` 处理 `phase_change`
- 前端 `BrowserView.vue` → 展示阶段状态

### 2.6 断线重连改进

**现状**：
- 前端有重连逻辑（最多 5 次，指数退避）
- 有 Stale 检测（断线 10s 后开始 REST 轮询）
- 重连后会 REST 回填步骤

**问题**：
- 如果步骤没有实时写入 DB（当前状态），REST 回填拿不到中间步骤
- 重连后截图流会断掉（`_latest_frames` 在内存中，不依赖连接状态，但前端不知道要重新拉取）

**改进**：
- 配合 2.1（步骤实时写入），重连后 REST 回填就能拿到完整步骤
- 重连成功后立即拉取一次 `latest_frame`，恢复截图流
- 后端在 `connection_established` 中返回已完成的步骤数，前端据此判断是否需要回填

---

## 三、实现优先级

| 优先级 | 改进项 | 依赖 | 预估工作量 |
|--------|--------|------|-----------|
| **P0** | 2.1 步骤实时写入 DB | 无 | 2h |
| **P0** | 2.2 两种场景差异化 | 2.1 | 1h |
| **P1** | 2.5 WS 连接状态优化 | 无 | 1h |
| **P1** | 2.6 断线重连改进 | 2.1 | 0.5h |
| **P2** | 2.4 固定时长截图持久化 | 无 | 2h |
| **P2** | 2.3 截图流独立（或 debounce） | 无 | 1h |

建议先做 P0 的两项，核心链路通了再优化体验。

---

## 四、数据流对比

### 改前
```
Agent 开始执行
  → 工具调用 1,2,3...N（步骤只在内存 _tool_calls_log 中）
  → WS 推送 step_start / step_complete（前端实时看到）
  → Agent 循环结束
  → _save_agent_result() 一次性写入 DB
  → 前端 WS 断线重连 → REST 回填 → 拿不到中间步骤 → 丢失
```

### 改后
```
Agent 开始执行
  → ExecutionRecord.status = running, step_logs = []
  → 工具调用 1 完成 → _persist_step() → DB 追加 step[0] + WS 推送
  → 工具调用 2 完成 → _persist_step() → DB 追加 step[1] + WS 推送
  → ...
  → Agent 循环结束 → _save_agent_result() 只更新最终状态
  → 前端 WS 断线重连 → REST 回填 → 拿到全部已完成步骤 → 完整
```

---

## 五、其他可考虑的改进

1. **执行取消**：前端提供"停止执行"按钮，通过 WS 发送 `cancel` 消息，后端设置标志位让 Agent 循环退出
2. **执行超时优雅降级**：Agent 达到 `max_turns` 后，即使没调用 `report_result`，也生成一个合理的总结
3. **步骤搜索/过滤**：历史步骤多了以后，支持按工具名称、关键词搜索
4. **性能指标面板**：展示每步耗时分布、token 消耗趋势图
5. **导出报告**：将执行结果导出为 PDF/HTML 报告
