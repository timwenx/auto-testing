http://localhost:3000/executions/3/observe
执行自动化测试时
ws://localhost:3000/ws/execution/3/
消息：execution_id
: 
3
execution_status
: 
"running"
type
: 
"connection_established"
，
action
: 
"list_files"
step_num
: 
1
target
: 
""
timestamp
: 
"2026-04-30T14:02:21"
type
: 
"step_start"

，
action
: 
"list_files"
duration_ms
: 
1
result
: 
"Error: 仓库未克隆，请先克隆仓库"
screenshot_path
: 
""
step_num
: 
1
target
: 
""
timestamp
: 
"2026-04-30T14:02:21"
type
: 
"step_complete"
，
text
: 
"这是一个外部网站（百度）的测试，无需本地代码探索。我将直接进入浏览器执行测试阶段。\n\n**测试步骤：**\n1. 打开百度\n2. 搜索\"京东\"\n3. 打开第一个页面\n\n让我们开始执行测试：\n\n**第1步：打开百度首页**"
timestamp
: 
"2026-04-30T14:02:26"
type
: 
"agent_thinking"，
action
: 
"browser_navigate"
step_num
: 
2
target
: 
"https://www.baidu.com/"
timestamp
: 
"2026-04-30T14:02:26"
type
: 
"step_start"

然后就不回消息了，一直卡住直到自动化测试执行完成，如果执行完成也需要有回放
页面显示：
用例	打开百度	模式	
agent
项目	百度	状态	
completed
已完成
0s
20 步骤
输入 4.0k / 输出 1.6k
2026-04-30T14:02:21
📂
list_files
✓
1ms
2026-04-30T14:02:26
🤖Agent 思考中
这是一个外部网站（百度）的测试，无需本地代码探索。我将直接进入浏览器执行测试阶段。

**测试步骤：**
1. 打开百度
2. 搜索"京东"
3. 打开第一个页面

让我们开始执行测试：

**第1步：打开百度首页**

2026-04-30T14:02:26
🌐
导航到 https://www.baidu.com/
执行中
https://www.baidu.com/