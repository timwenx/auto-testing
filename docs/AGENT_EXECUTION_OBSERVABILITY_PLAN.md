# Agent 执行可观测性 UI 改进方案

> 状态：规划中 | 作者：timwen | 日期：2026-04-30

---

## 1. 背景

当前 My_Test 的 Agent 执行流程：

1. 用户在 `ProjectDetail.vue` 点击「Agent 执行」
2. 后端创建 `ExecutionRecord`（status=running），通过线程池异步运行 `AgentRunner`
3. `AgentRunner` 在循环中调用 Claude API + 执行 Playwright 工具，直到 `end_turn` 或达到 `max_turns`
4. 执行完成后，结果写入 `ExecutionRecord.step_logs` / `screenshots` / `agent_response`
5. 前端在 `Executions.vue` 通过 5 秒轮询刷新，**执行完成后**才能看到步骤时间线和截图

### 核心问题

| 问题 | 影响 |
|------|------|
| **执行过程不可见** | 用户点击 Agent 执行后只能看一个「running」状态，无法知道 Agent 正在做什么 |
| **无浏览器画面** | Agent 操作 Playwright 浏览器时完全黑盒，用户无法直观看到操作过程 |
| **排障困难** | Agent 卡住或出错时，无法实时判断是哪一步出了问题 |
| **信任度低** | 看不到过程，用户难以信任 Agent 的测试结果 |

---

## 2. 目标体验

### 2.1 核心场景

用户点击「Agent 执行」后，跳转（或弹出）一个**执行观察面板**：

```
┌─────────────────────────────────────────────────────────┐
│  执行观察 — [用例名称]                        ● 运行中   │
├───────────────────────┬─────────────────────────────────┤
│                       │  ┌─ 执行步骤 ─────────────────┐ │
│                       │  │ ✓ Step 1: browser_navigate  │ │
│                       │  │   → http://localhost:5173    │ │
│   📺 浏览器实时画面    │  │ ✓ Step 2: browser_click     │ │
│   (嵌入浏览器屏幕)     │  │   → button.submit           │ │
│                       │  │ ● Step 3: browser_fill      │ │
│                       │  │   → input[name="email"]     │ │
│                       │  │   ...正在输入...              │ │
│                       │  │ ○ Step 4: (等待中)           │ │
│                       │  └────────────────────────────┘ │
│                       │                                 │
│                       │  ┌─ 工具详情 ─────────────────┐ │
│                       │  │ 最近的工具调用详细信息        │ │
│                       │  │ 输入参数 / 返回结果          │ │
│                       │  └────────────────────────────┘ │
├───────────────────────┴─────────────────────────────────┤
│  📊 Token: 输入 1,234 / 输出 567  │  耗时: 12.3s  │ ... │
└─────────────────────────────────────────────────────────┘
```

### 2.2 功能清单

| # | 功能 | 优先级 | 说明 |
|---|------|--------|------|
| F1 | 实时步骤推送 | P0 | Agent 每执行一个工具调用，前端立即显示 |
| F2 | 浏览器实时画面 | P0 | 嵌入 Playwright 浏览器的屏幕画面（VNC/noVNC 或截图流） |
| F3 | 步骤时间线 | P0 | 带状态标记的步骤列表（完成✓ / 进行中● / 等待○） |
| F4 | 工具详情面板 | P1 | 点击步骤可查看工具调用的输入/输出参数 |
| F5 | 实时截图预览 | P1 | Agent 调用 `browser_screenshot` 时自动显示截图 |
| F6 | 执行统计 | P1 | Token 消耗、耗时、工具调用次数的实时计数 |
| F7 | Agent 思维过程 | P2 | 显示 Claude 的文本回复（非工具调用的思考内容） |
| F8 | 执行控制 | P3 | 暂停/继续/终止（后续迭代） |
| F9 | 历史回放 | P3 | 对已完成的执行记录进行回放，模拟实时效果 |

---

## 3. 技术方案

### 3.1 架构总览

```
┌──────────────┐    WebSocket     ┌──────────────┐    工具回调     ┌──────────────┐
│              │ ◄──────────────► │              │ ◄───────────── │              │
│   Vue 前端    │   实时步骤推送    │  Django 后端  │   step_events  │  AgentRunner │
│  (观察面板)   │   浏览器画面流    │  WebSocket   │                │  (线程池)     │
│              │                  │  + REST API  │                │  Playwright  │
└──────────────┘                  └──────────────┘                └──────────────┘
                                         │                              │
                                         │ 文件/HTTP                     │ 截图
                                         ▼                              ▼
                                  ┌──────────────┐              ┌──────────────┐
                                  │  noVNC 服务   │              │  浏览器实例   │
                                  │  (浏览器画面)  │              │  Chromium     │
                                  └──────────────┘              └──────────────┘
```

### 3.2 实时步骤推送（F1）

**方案：Django Channels + WebSocket**

当前 `AgentRunner.run()` 中每个工具调用都记录到 `self._tool_calls_log`，但只在执行完成后一次性返回。

**改造点**：

1. **新增 `StepEvent` 模型**（或用 Redis pub/sub，避免 DB 写入瓶颈）

   ```python
   # 方案 A：直接用 channel layer（推荐，轻量）
   from channels.layers import get_channel_layer
   from asgiref.sync import async_to_sync

   def _emit_step_event(execution_id, step_data):
       """Agent 工具执行后推送步骤事件"""
       channel_layer = get_channel_layer()
       async_to_sync(channel_layer.group_send)(
           f"execution_{execution_id}",
           {
               "type": "step_event",
               "data": step_data,
           }
       )
   ```

2. **在 `AgentRunner.run()` 工具执行后调用**：

   ```python
   # agent_service.py — 在 tool 执行后添加事件推送
   self._tool_calls_log.append(log_entry)

   # 新增：推送实时事件
   if self.testcase_id:
       _emit_step_event(execution_id, {
           "step_num": len(self._tool_calls_log),
           "action": tool_name,
           "target": _extract_target(tool_name, tool_input),
           "result": result_text[:300],
           "screenshot_path": ...,
           "timestamp": time.strftime('%Y-%m-%dT%H:%M:%S'),
           "status": "completed",
       })
   ```

3. **新增 Django Channels Consumer**

   ```python
   # consumers.py
   class ExecutionConsumer(WebsocketConsumer):
       def connect(self):
           self.execution_id = self.scope['url_route']['kwargs']['execution_id']
           self.group_name = f'execution_{self.execution_id}'
           async_to_sync(self.channel_layer.group_add)(
               self.group_name, self.channel_name
           )
           self.accept()

       def disconnect(self, close_code):
           async_to_sync(self.channel_layer.group_discard)(
               self.group_name, self.channel_name
           )

       def step_event(self, event):
           self.send(text_data=json.dumps(event['data']))
   ```

4. **前端 WebSocket 监听**

   ```javascript
   // ExecutionObserver.vue
   const ws = new WebSocket(`ws://${host}/ws/execution/${executionId}/`)
   ws.onmessage = (event) => {
       const step = JSON.parse(event.data)
       steps.value.push(step)
       // 自动滚动到最新步骤
       // 如果有 screenshot_path，自动加载截图
   }
   ```

**WebSocket 事件协议**：

```jsonc
// 步骤开始事件
{
  "event": "step_start",
  "step_num": 3,
  "action": "browser_click",
  "target": "button.submit",
  "timestamp": "2026-04-30T10:15:23"
}

// 步骤完成事件
{
  "event": "step_complete",
  "step_num": 3,
  "action": "browser_click",
  "target": "button.submit",
  "result": "已点击: button.submit",
  "screenshot_path": "/media/screenshots/1/5/step_3.png",
  "duration_ms": 234,
  "timestamp": "2026-04-30T10:15:23"
}

// 执行结束事件
{
  "event": "execution_end",
  "status": "passed",
  "duration": 12.3,
  "total_input_tokens": 1234,
  "total_output_tokens": 567
}

// Agent 思维事件（F7）
{
  "event": "agent_thinking",
  "text": "我需要先检查登录表单的结构..."
}
```

### 3.3 浏览器实时画面（F2）

这是最关键的体验提升。有三种方案：

#### 方案对比

| 方案 | 原理 | 延迟 | 改动量 | 推荐度 |
|------|------|------|--------|--------|
| **A. Playwright 截图流** | 每步自动截图，通过 WebSocket 推送到前端 | 1-3s（按步骤） | 小 | ⭐⭐⭐ |
| **B. noVNC + Xvfb** | Playwright 在虚拟显示器运行，noVNC 转发画面 | <100ms | 中 | ⭐⭐⭐⭐ |
| **C. Playwright CDP 镜像** | 通过 Chrome DevTools Protocol 录屏并转发 | <200ms | 中 | ⭐⭐⭐ |

#### 推荐：方案 B（noVNC + Xvfb）

**原理**：
- 用 Xvfb 创建虚拟显示器
- Playwright 在该显示器上运行 Chromium（`headless: false`）
- noVNC 提供浏览器端的 VNC 客户端
- 前端通过 iframe 嵌入 noVNC 页面

**后端改造**：

```python
# agent_service.py — _ensure_browser 改造
def _ensure_browser(self, context):
    """在虚拟显示器上启动 Playwright 浏览器"""
    import os
    from playwright.sync_api import sync_playwright

    # 启动 Xvfb（如果没有运行）
    display = self._start_xvfb()
    os.environ['DISPLAY'] = f':{display}'

    self._playwright = sync_playwright().start()
    self._browser = self._playwright.chromium.launch(
        headless=False,  # 关键：非无头模式
        args=['--no-sandbox', '--disable-gpu']
    )
    self._page = self._browser.new_page()
    context['page'] = self._page
```

```python
# 新增：vnc_service.py
import subprocess
import os

class VNCService:
    """管理 Xvfb + x11vnc，为每次 Agent 执行提供独立的浏览器画面"""

    def __init__(self, execution_id):
        self.execution_id = execution_id
        self.display = None
        self._xvfb_proc = None
        self._vnc_proc = None
        self.vnc_port = 6080 + execution_id % 100  # 简单端口分配

    def start(self):
        """启动虚拟显示器和 VNC 服务"""
        # 1. Xvfb
        self.display = self._find_free_display()
        self._xvfb_proc = subprocess.Popen([
            'Xvfb', f':{self.display}', '-screen', '0',
            '1280x720x24', '-ac'
        ])
        os.environ['DISPLAY'] = f':{self.display}'

        # 2. x11vnc
        self._vnc_proc = subprocess.Popen([
            'x11vnc', '-display', f':{self.display}',
            '-nopw', '-listen', 'localhost',
            '-rfbport', str(self.vnc_port),
            '-forever', '-shared'
        ])

        # 3. noVNC (websockify)
        # websockify 将 WebSocket 流量转发到 VNC 端口
        # 前端通过 /vnc/<execution_id>/ 访问
        return self.vnc_port

    def stop(self):
        """清理资源"""
        for proc in [self._vnc_proc, self._xvfb_proc]:
            if proc:
                proc.terminate()
                proc.wait(timeout=5)
```

**前端嵌入**：

```vue
<!-- ExecutionObserver.vue -->
<template>
  <div class="browser-view">
    <!-- noVNC iframe -->
    <iframe
      :src="`/vnc/vnc.html?host=${host}&port=${vncPort}&path=vnc/${executionId}`"
      class="vnc-frame"
    />
  </div>
</template>
```

**简化方案（Windows 环境）**：

当前项目运行在 Windows 上，Xvfb 不可用。替代方案：

```python
# Windows 方案：使用 Playwright 的非无头模式 + 定时截图流
def _ensure_browser(self, context):
    self._playwright = sync_playwright().start()
    self._browser = self._playwright.chromium.launch(
        headless=False,  # Windows 上直接弹出浏览器窗口
        args=['--no-sandbox']
    )
    self._page = self._browser.new_page(viewport={'width': 1280, 'height': 720})
    context['page'] = self._page

    # 启动定时截图线程（每 500ms 截图一次推送到前端）
    self._start_screenshot_stream()
```

**截图流方案（方案 A，Windows 友好）**：

```python
# screenshot_stream.py
import threading
import time
import base64

class ScreenshotStream:
    """定时截图并通过 WebSocket 推送到前端"""

    def __init__(self, page, execution_id, interval=0.5):
        self.page = page
        self.execution_id = execution_id
        self.interval = interval
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _stream_loop(self):
        while self._running:
            try:
                screenshot_bytes = self.page.screenshot(type='jpeg', quality=60)
                b64 = base64.b64encode(screenshot_bytes).decode()
                _emit_step_event(self.execution_id, {
                    "event": "browser_frame",
                    "image": f"data:image/jpeg;base64,{b64}",
                    "timestamp": time.strftime('%Y-%m-%dT%H:%M:%S.%f'),
                })
            except Exception:
                pass
            time.sleep(self.interval)
```

> **建议**：先实现截图流方案（方案 A），验证体验后再升级到 noVNC。

### 3.4 步骤时间线组件（F3）

**新增 Vue 组件 `ExecutionTimeline.vue`**：

```vue
<template>
  <div class="execution-timeline">
    <div
      v-for="step in steps"
      :key="step.step_num"
      :class="['step-item', step.status]"
      @click="$emit('select', step)"
    >
      <span class="step-icon">
        <span v-if="step.status === 'completed'">✓</span>
        <span v-else-if="step.status === 'running'" class="pulse">●</span>
        <span v-else>○</span>
      </span>
      <span class="step-action">{{ formatAction(step) }}</span>
      <span v-if="step.target" class="step-target">{{ step.target }}</span>
      <span class="step-time">{{ step.timestamp }}</span>
    </div>
  </div>
</template>
```

**步骤状态映射**：

| Agent 工具 | 步骤显示 |
|------------|---------|
| `browser_navigate` | 🌐 导航到 `{url}` |
| `browser_click` | 👆 点击 `{selector}` |
| `browser_fill` | ⌨️ 在 `{selector}` 输入 `{value}` |
| `browser_press_key` | ⌨️ 按下 `{key}` |
| `browser_wait_for` | ⏳ 等待 `{selector}` |
| `browser_get_text` | 📋 获取 `{selector}` 文本 |
| `browser_screenshot` | 📸 截图 |
| `list_files` / `read_file` / ... | 📂 仓库探索: `{tool}` |
| `report_result` | 🏁 报告结果: `{status}` |

### 3.5 数据模型变更

```python
# 新增模型（可选，也可用 Channel Layer 内存推送）

class ExecutionStep(models.Model):
    """实时执行步骤 — 每个工具调用产生一条记录"""
    execution = models.ForeignKey(
        ExecutionRecord, on_delete=models.CASCADE,
        related_name='live_steps'
    )
    step_num = models.IntegerField('步骤序号')
    action = models.CharField('操作', max_length=100)
    target = models.CharField('目标', max_length=500, blank=True)
    input_data = models.JSONField('输入参数', default=dict)
    result = models.TextField('执行结果', blank=True)
    status = models.CharField('状态', max_length=20, default='running')
    screenshot_path = models.CharField('截图', max_length=500, blank=True)
    started_at = models.DateTimeField('开始时间', auto_now_add=True)
    completed_at = models.DateTimeField('完成时间', null=True)
    duration_ms = models.IntegerField('耗时(ms)', null=True)

    class Meta:
        ordering = ['step_num']
```

> **注意**：如果用 Channel Layer 推送，这个模型不是必须的。但持久化步骤记录有助于：
> - 执行中断后恢复
> - 历史回放（F9）
> - 数据分析

### 3.6 API 变更

| 接口 | 方法 | 说明 |
|------|------|------|
| `/ws/execution/<id>/` | WebSocket | 实时步骤推送 + 截图流 |
| `/api/executions/<id>/steps/` | GET | 获取已完成的步骤列表（用于页面加载时补齐） |
| `/api/executions/<id>/vnc-info/` | GET | 获取 VNC 连接信息（如果使用 noVNC 方案） |
| `/api/executions/<id>/live-stats/` | GET | 实时统计（Token、耗时、工具调用数） |

### 3.7 前端组件架构

```
新增文件:
├── frontend/src/
│   ├── views/
│   │   └── ExecutionObserver.vue      # 执行观察主页面（新）
│   ├── components/
│   │   ├── ExecutionTimeline.vue      # 实时步骤时间线（新）
│   │   ├── BrowserView.vue            # 浏览器画面组件（新）
│   │   ├── ToolDetailPanel.vue        # 工具详情面板（新）
│   │   └── ExecutionStats.vue         # 执行统计组件（新）
│   └── composables/
│       └── useExecutionObserver.js    # WebSocket 连接管理（新）
```

**`useExecutionObserver.js` — WebSocket 组合式函数**：

```javascript
export function useExecutionObserver(executionId) {
  const steps = ref([])
  const currentFrame = ref(null)    // 浏览器截图帧
  const stats = ref({ inputTokens: 0, outputTokens: 0, duration: 0 })
  const status = ref('connecting')  // connecting | running | completed | error
  const ws = ref(null)

  function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    ws.value = new WebSocket(`${protocol}//${location.host}/ws/execution/${executionId}/`)

    ws.value.onopen = () => { status.value = 'running' }

    ws.value.onmessage = (event) => {
      const data = JSON.parse(event.data)

      switch (data.event) {
        case 'step_start':
          steps.value.push({ ...data, status: 'running' })
          break
        case 'step_complete':
          const idx = steps.value.findIndex(s => s.step_num === data.step_num)
          if (idx >= 0) steps.value[idx] = { ...data, status: 'completed' }
          break
        case 'browser_frame':
          currentFrame.value = data.image
          break
        case 'execution_end':
          status.value = data.status
          stats.value = data
          break
      }
    }

    ws.value.onclose = () => { status.value = 'completed' }
  }

  function disconnect() {
    ws.value?.close()
  }

  return { steps, currentFrame, stats, status, connect, disconnect }
}
```

---

## 4. 后端依赖

| 依赖 | 用途 | 安装 |
|------|------|------|
| `channels` | Django WebSocket 支持 | `pip install channels` |
| `channels_redis` | Channel Layer（Redis 后端） | `pip install channels_redis` |
| Redis | WebSocket 消息代理 | 需要运行 Redis 服务 |

**settings.py 变更**：

```python
INSTALLED_APPS += ['channels']

ASGI_APPLICATION = 'backend.asgi.application'

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [('127.0.0.1', 6379)],
        },
    },
}
```

---

## 5. 实施计划

### Phase 1：MVP — 实时步骤推送（~2 天）

> 目标：用户能看到 Agent 每一步在做什么

- [ ] 安装 `channels` + `channels_redis`，配置 ASGI
- [ ] 新增 `ExecutionConsumer` WebSocket 消费者
- [ ] 改造 `AgentRunner.run()` — 工具执行后推送 `step_start` / `step_complete` 事件
- [ ] 新增 `ExecutionObserver.vue` — WebSocket 连接 + 步骤列表
- [ ] 新增 `ExecutionTimeline.vue` — 带状态标记的步骤组件
- [ ] 修改 `ProjectDetail.vue` — Agent 执行后跳转到观察面板

**交付物**：点击 Agent 执行后，新页面实时显示步骤列表（文字形式）

### Phase 2：浏览器画面（~3 天）

> 目标：用户能看到 Agent 的浏览器操作画面

- [ ] 实现 `ScreenshotStream` — 定时截图推流（500ms 间隔）
- [ ] 新增 `BrowserView.vue` — 显示实时截图帧
- [ ] WebSocket 推送 `browser_frame` 事件
- [ ] 优化截图压缩（JPEG quality=60，约 30-50KB/帧）
- [ ] 首屏加载时发送最近一帧截图

**交付物**：观察面板左侧显示浏览器实时画面

### Phase 3：增强体验（~2 天）

> 目标：更丰富的信息展示

- [ ] 新增 `ToolDetailPanel.vue` — 点击步骤查看输入/输出详情
- [ ] 新增 `ExecutionStats.vue` — 实时 Token / 耗时统计
- [ ] Agent 思维过程展示（`agent_thinking` 事件）
- [ ] 截图自动预览（Agent 调用 `browser_screenshot` 时弹出大图）
- [ ] 页面加载时通过 REST API 补齐已完成的步骤

**交付物**：完整的观察面板，包含工具详情和统计

### Phase 4：进阶功能（后续迭代）

- [ ] noVNC 方案（需 Linux 部署环境）
- [ ] 执行控制（暂停/继续/终止）
- [ ] 历史回放（对已完成记录模拟实时播放）
- [ ] 多执行并行观察
- [ ] 步骤搜索/过滤

---

## 6. 风险与注意事项

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 截图流带宽消耗 | 每帧 ~50KB × 2帧/s = ~100KB/s | JPEG 压缩 + 按需降帧率 + 用户可关闭画面 |
| Windows 无 Xvfb | noVNC 方案不可用 | 先用截图流，部署到 Linux 再升级 |
| WebSocket 断连 | 用户丢失实时更新 | 断线重连 + REST API 补齐已执行步骤 |
| Agent 线程与 WebSocket 通信 | Django 同步视图 vs ASGI 异步 | 用 Channel Layer 解耦，Agent 线程写入 channel |
| 并发执行 | 多个 Agent 同时运行 | 每个 execution_id 独立的 channel group |
| Redis 依赖 | 需要额外服务 | 开发环境可用 `InMemoryChannelLayer` |

---

## 7. 与现有代码的集成点

| 现有文件 | 改造内容 |
|----------|---------|
| `agent_service.py` → `AgentRunner.run()` | 工具执行后调用 `_emit_step_event()` |
| `agent_service.py` → `_ensure_browser()` | 接入 `ScreenshotStream` 或 `VNCService` |
| `execution_engine.py` → `execute_testcase_with_agent()` | 传入 `execution_id`，启动/停止流服务 |
| `views.py` → `execute_testcase_agent()` | 返回 WebSocket 连接信息 |
| `models.py` | 可选：新增 `ExecutionStep` 模型 |
| `backend/asgi.py` | 注册 WebSocket application |
| `backend/urls.py` | 添加 WebSocket 路由 |
| `frontend/src/views/ProjectDetail.vue` | Agent 执行后导航到观察面板 |
| `frontend/src/views/Executions.vue` | 详情弹窗增加「观察回放」入口 |

---

## 8. 参考资料

- [Django Channels 官方文档](https://channels.readthedocs.io/)
- [Playwright Screenshot API](https://playwright.dev/python/docs/api/class-page#page-screenshot)
- [noVNC 项目](https://github.com/novnc/noVNC)
- [websockify](https://github.com/novnc/websockify)
