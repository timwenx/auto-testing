"""
script_converter.py — 将 Agent 执行记录转换为结构化可回放脚本。

从 ExecutionRecord 的 step_logs / tool_calls_log 中提取浏览器操作步骤，
自动将用户输入值（填写内容、选择项、URL）提取为动态参数。
"""
import re
import json
import hashlib
import logging

logger = logging.getLogger(__name__)

# 可回放的浏览器工具（产生可重现的页面操作）
REPLAYABLE_TOOLS = {
    'browser_navigate', 'browser_click', 'browser_fill',
    'browser_fill_form', 'browser_select', 'browser_press_key',
    'browser_batch_action', 'browser_assert',
}

# 探索/观察类工具（跳过）
SKIP_TOOLS = {
    'browser_snapshot', 'browser_query_all', 'browser_get_text',
    'browser_screenshot', 'browser_get_form',
    'list_files', 'read_file', 'search_code', 'list_directory',
    'report_result',
}


def _short_selector(selector, max_len=30):
    """从 CSS selector 生成简短的参数后缀"""
    # 取最后一个简单选择器部分
    parts = selector.rstrip(']').split(',')
    simple = parts[0].strip().split()[-1] if parts else selector
    simple = simple.lstrip('#.')[:max_len]
    return re.sub(r'[^a-zA-Z0-9_]', '_', simple).lower()


def _make_param_name(prefix, selector='', index=0):
    """生成唯一的参数名"""
    suffix = _short_selector(selector) if selector else str(index)
    return f'{prefix}_{suffix}'


def _make_label(tool_name, selector, value):
    """生成参数的可读标签"""
    short_sel = selector.replace('"', "'")[:40] if selector else ''
    short_val = (value or '')[:30]
    labels = {
        'browser_navigate': f'URL',
        'browser_fill': f'填写 {short_sel}',
        'browser_fill_form': f'填写 {short_sel}',
        'browser_select': f'选择 {short_sel}',
        'browser_press_key': f'按键',
    }
    return labels.get(tool_name, short_val)


def _link_assert_selectors(steps, parameters):
    """
    后处理：将 browser_assert 步骤 selector 中的硬编码值替换为已有参数引用。
    例如 tr:has-text('AT001') 中 AT001 如果是某个填写参数的 default，
    则替换为 tr:has-text('{{param_code_5}}')。
    """
    # 收集 default → param_name 映射（排除空值和过短的值）
    value_to_param = {}
    for pname, pinfo in parameters.items():
        default = str(pinfo.get('default', '')).strip()
        if len(default) >= 2:  # 至少2字符才值得替换
            value_to_param[default] = pname

    if not value_to_param:
        return

    # 按 default 值长度降序排列，避免短值误替换长值的一部分
    sorted_values = sorted(value_to_param.items(), key=lambda x: len(x[0]), reverse=True)

    for step in steps:
        if step.get('tool_name') != 'browser_assert':
            continue
        selector = step.get('inputs', {}).get('selector', '')
        if not selector:
            continue

        new_selector = selector
        referenced_params = []
        for value, pname in sorted_values:
            if value in new_selector:
                ref = '{{' + pname + '}}'
                new_selector = new_selector.replace(value, ref)
                if pname not in referenced_params:
                    referenced_params.append(pname)

        if new_selector != selector:
            step['inputs']['selector'] = new_selector
            step['parameters'] = referenced_params


def convert_execution_to_script(record):
    """
    将 ExecutionRecord 的 agent 执行数据转换为结构化回放脚本。

    Args:
        record: ExecutionRecord 对象

    Returns:
        dict: 结构化脚本 JSON，包含 parameters 和 steps

    Raises:
        ValueError: 如果没有可回放的步骤
    """
    # 优先使用 step_logs（新数据含 tool_input 字段）
    # 回退到从 tool_calls_log 中提取
    tool_calls = _extract_tool_calls(record)
    step_logs = record.step_logs or []

    if not tool_calls and not step_logs:
        raise ValueError('执行记录中没有工具调用数据')

    parameters = {}
    steps = []
    param_counter = 0

    if tool_calls:
        # 有完整的 tool_calls_log（含 input 参数）
        for call in tool_calls:
            tool_name = call.get('tool', '')
            tool_input = call.get('input', {})
            if tool_name not in REPLAYABLE_TOOLS:
                continue
            param_counter += 1
            step, new_params = _convert_step(tool_name, tool_input, param_counter, record.pk)
            if step:
                parameters.update(new_params)
                steps.append(step)
    else:
        # 从 step_logs 转换（兼容旧数据）
        for slog in step_logs:
            tool_name = slog.get('tool_name', '')
            if tool_name not in REPLAYABLE_TOOLS:
                continue
            param_counter += 1
            # 新数据有 tool_input 字段
            tool_input = slog.get('tool_input')
            if not tool_input:
                # 旧数据：从 target/action 反推基本参数
                tool_input = _reconstruct_input(tool_name, slog)
            step, new_params = _convert_step(tool_name, tool_input, param_counter, record.pk)
            if step:
                parameters.update(new_params)
                steps.append(step)

    if not steps:
        raise ValueError('没有可回放的浏览器操作步骤（仅发现探索/观察类工具调用）')

    # 后处理：断言 selector 中的硬编码值替换为已有参数引用
    _link_assert_selectors(steps, parameters)

    base_url = _extract_base_url(steps, record)

    return {
        'version': 1,
        'name': f'脚本回放 - {record.testcase.name if record.testcase else "批量执行"}',
        'base_url': base_url,
        'source_execution_id': record.pk,
        'parameters': parameters,
        'steps': steps,
    }


def _extract_tool_calls(record):
    """从 ExecutionRecord 提取 tool_calls_log"""
    log = record.log or ''

    # 优先：从 TOOL_CALLS_JSON 标记后解析（新数据）
    marker = '=== TOOL_CALLS_JSON ==='
    idx = log.find(marker)
    if idx != -1:
        json_str = log[idx + len(marker):].strip()
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict) and parsed.get('tool_calls'):
                return parsed['tool_calls']
        except (json.JSONDecodeError, TypeError):
            pass

    # 回退：整个 log 是纯 JSON
    if log:
        try:
            parsed = json.loads(log)
            if isinstance(parsed, dict) and parsed.get('tool_calls'):
                return parsed['tool_calls']
        except (json.JSONDecodeError, TypeError):
            pass

    return []


def _reconstruct_input(tool_name, slog):
    """
    从旧版 step_logs（缺少 tool_input 字段）反推基本参数。
    利用 target / action / result 等已有字段重建。
    """
    target = slog.get('target', '')
    result = slog.get('result', '')
    action = slog.get('action', '')

    if tool_name == 'browser_navigate':
        # target 就是 URL
        url = target
        if not url and result:
            m = re.search(r'(https?://\S+)', result)
            if m:
                url = m.group(1)
        return {'url': url}

    elif tool_name in ('browser_click',):
        return {'selector': target, 'wait_for': '', 'wait_for_navigation': False}

    elif tool_name == 'browser_fill':
        # action 格式如 "填写 TEST100" 或 "填写 #username = admin"
        value = ''
        if '=' in action:
            value = action.split('=', 1)[-1].strip()
        elif action.startswith('填写 '):
            value = action[3:].strip()
        return {'selector': target, 'value': value}

    elif tool_name == 'browser_fill_form':
        return {'fields': [], 'submit_selector': ''}

    elif tool_name == 'browser_select':
        # action 格式如 "选择 txInfo - 交易资料"（来自 label 优先）
        # action 文本来自 format_step_action: label 优先，回退 value
        label = ''
        if action.startswith('选择 '):
            label = action[3:].strip()
        return {'selector': target, 'value': '', 'label': label}

    elif tool_name == 'browser_press_key':
        key = ''
        if action.startswith('按键 '):
            key = action[3:].strip()
        elif ' ' in action:
            key = action.split()[-1]
        return {'key': key}

    elif tool_name == 'browser_batch_action':
        # 从 action 文本解析子操作类型，创建占位 actions
        # action 格式如 "批量操作 (4 步: fill, fill, fill, click)"
        m = re.search(r'\((\d+)\s*步[:：]\s*(.*?)\)', action)
        if m:
            type_str = m.group(2)
            types = [t.strip() for t in type_str.split(',')]
            actions = []
            for t in types:
                if t in ('fill', 'click', 'select', 'press_key', 'wait'):
                    actions.append({'type': t})
            return {'actions': actions, 'delay_between': 20}
        return {'actions': [], 'delay_between': 20}

    elif tool_name == 'browser_assert':
        # action 格式如 "验证 count(sel) gte 1" 或 "验证 text(sel) contains xxx"
        assert_type = 'element_count'
        selector = target.split(': ', 1)[-1] if ': ' in target else target
        operator = ''
        expected = ''
        # 尝试从 action 解析: "验证 count(selector) op expected"
        m = re.match(r'验证\s+(\w+)\((.+?)\)\s+(\w+)\s+(.+)', action)
        if m:
            assert_type = 'element_count' if m.group(1) == 'count' else 'text_content'
            selector = m.group(2)
            operator = m.group(3)
            expected = m.group(4).strip('"').strip("'")
        return {'assert_type': assert_type, 'selector': selector, 'operator': operator, 'expected': expected, 'message': ''}

    return {}


def _extract_base_url(steps, record):
    """提取 base_url：从第一个 navigate 步骤的 URL 中提取域名"""
    for step in steps:
        inputs = step.get('inputs', {})
        url = inputs.get('url', '')
        if url:
            m = re.match(r'(https?://[^/]+)', url)
            if m:
                return m.group(1)
    return record.project.base_url if record.project else ''


def _convert_step(tool_name, tool_input, step_num, execution_id):
    """
    转换单个工具调用为脚本步骤，同时提取参数。

    Returns:
        (step_dict, params_dict) 或 (None, {})
    """
    params = {}

    if tool_name == 'browser_navigate':
        url = tool_input.get('url', '')
        pname = _make_param_name('param_url')
        params[pname] = {
            'label': '目标 URL',
            'type': 'url',
            'default': url,
        }
        step = {
            'step_num': step_num,
            'enabled': True,
            'tool_name': tool_name,
            'description': f'导航到 {url[:60]}',
            'inputs': {
                'url': '{{' + pname + '}}',
                'wait_until': tool_input.get('wait_until', 'domcontentloaded'),
            },
            'parameters': [pname],
        }

    elif tool_name == 'browser_click':
        selector = tool_input.get('selector', '')
        step = {
            'step_num': step_num,
            'enabled': True,
            'tool_name': tool_name,
            'description': f'点击 {selector[:50]}',
            'inputs': {
                'selector': selector,
                'wait_for': tool_input.get('wait_for', ''),
                'wait_for_navigation': tool_input.get('wait_for_navigation', False),
            },
            'parameters': [],
        }

    elif tool_name == 'browser_fill':
        selector = tool_input.get('selector', '')
        value = tool_input.get('value', '')
        pname = _make_param_name('param', selector)
        params[pname] = {
            'label': f'填写 {selector[:40]}',
            'type': 'string',
            'default': value,
        }
        step = {
            'step_num': step_num,
            'enabled': True,
            'tool_name': tool_name,
            'description': f'填写 {selector[:50]} = {(value or "")[:30]}',
            'inputs': {
                'selector': selector,
                'value': '{{' + pname + '}}',
            },
            'parameters': [pname],
        }

    elif tool_name == 'browser_fill_form':
        fields = tool_input.get('fields', [])
        submit = tool_input.get('submit_selector', '')
        templated_fields = []
        for i, f in enumerate(fields):
            sel = f.get('selector', '')
            val = f.get('value', '')
            pname = _make_param_name('param', sel, i)
            params[pname] = {
                'label': f'填写 {sel[:40]}',
                'type': 'string',
                'default': val,
            }
            templated_fields.append({
                'selector': sel,
                'value': '{{' + pname + '}}',
            })
        step = {
            'step_num': step_num,
            'enabled': True,
            'tool_name': tool_name,
            'description': f'填写表单 ({len(fields)} 个字段)',
            'inputs': {
                'fields': templated_fields,
                'submit_selector': submit,
            },
            'parameters': list(params.keys()),
        }

    elif tool_name == 'browser_select':
        selector = tool_input.get('selector', '')
        value = tool_input.get('value', '')
        label = tool_input.get('label', '')
        # 优先提取 label（更可读），回退到 value
        if label:
            pname = _make_param_name('param', selector)
            params[pname] = {
                'label': f'选择 {selector[:40]}',
                'type': 'string',
                'default': label,
            }
            step = {
                'step_num': step_num,
                'enabled': True,
                'tool_name': tool_name,
                'description': f'选择 {selector[:50]} = {label[:30]}',
                'inputs': {
                    'selector': selector,
                    'value': '',
                    'label': '{{' + pname + '}}',
                },
                'parameters': [pname],
            }
        elif value:
            pname = _make_param_name('param', selector)
            params[pname] = {
                'label': f'选择 {selector[:40]}',
                'type': 'string',
                'default': value,
            }
            step = {
                'step_num': step_num,
                'enabled': True,
                'tool_name': tool_name,
                'description': f'选择 {selector[:50]} = {value[:30]}',
                'inputs': {
                    'selector': selector,
                    'value': '{{' + pname + '}}',
                    'label': '',
                },
                'parameters': [pname],
            }
        else:
            step = {
                'step_num': step_num,
                'enabled': True,
                'tool_name': tool_name,
                'description': f'选择 {selector[:50]}',
                'inputs': {'selector': selector, 'value': '', 'label': ''},
                'parameters': [],
            }

    elif tool_name == 'browser_press_key':
        key = tool_input.get('key', '')
        step = {
            'step_num': step_num,
            'enabled': True,
            'tool_name': tool_name,
            'description': f'按键 {key}',
            'inputs': {'key': key},
            'parameters': [],
        }

    elif tool_name == 'browser_batch_action':
        actions = tool_input.get('actions', [])
        delay = tool_input.get('delay_between', 20)
        templated_actions = []
        for i, act in enumerate(actions):
            act_type = act.get('type', '')
            new_act = dict(act)
            if act_type == 'fill' and act.get('value'):
                sel = act.get('selector', '')
                pname = _make_param_name('param', sel, i)
                params[pname] = {
                    'label': f'填写 {sel[:40]}',
                    'type': 'string',
                    'default': act['value'],
                }
                new_act['value'] = '{{' + pname + '}}'
            elif act_type == 'select':
                sel = act.get('selector', '')
                val = act.get('value', '') or act.get('label', '')
                if val:
                    pname = _make_param_name('param', sel, i)
                    params[pname] = {
                        'label': f'选择 {sel[:40]}',
                        'type': 'string',
                        'default': val,
                    }
                    if act.get('value'):
                        new_act['value'] = '{{' + pname + '}}'
                    if act.get('label'):
                        new_act['label'] = '{{' + pname + '}}'
            templated_actions.append(new_act)
        step = {
            'step_num': step_num,
            'enabled': True,
            'tool_name': tool_name,
            'description': f'批量操作 ({len(actions)} 步)',
            'inputs': {
                'actions': templated_actions,
                'delay_between': delay,
            },
            'parameters': list(params.keys()),
        }

    elif tool_name == 'browser_assert':
        assert_type = tool_input.get('assert_type', '')
        selector = tool_input.get('selector', '')
        operator = tool_input.get('operator', '')
        expected = tool_input.get('expected', '')
        message = tool_input.get('message', '')

        pname = f'param_expected_{step_num}'
        params[pname] = {
            'label': f'预期值 ({selector[:25]})',
            'type': 'string',
            'default': str(expected),
            'group': 'assertion',
        }

        desc = message or f'验证 {assert_type}: {selector} {operator} {expected}'
        step = {
            'step_num': step_num,
            'enabled': True,
            'tool_name': 'browser_assert',
            'description': desc,
            'inputs': {
                'assert_type': assert_type,
                'selector': selector,
                'operator': operator,
                'expected': '{{' + pname + '}}',
                'message': message,
            },
            'parameters': [pname],
        }

    else:
        return None, {}

    # 添加原始截图路径（按 step_num 精确匹配）
    if execution_id:
        from core.models import ExecutionRecord
        try:
            rec = ExecutionRecord.objects.get(pk=execution_id)
            db_steps = rec.step_logs or []
            for s in db_steps:
                if s.get('step_num') == step_num and s.get('screenshot_path'):
                    step['original_screenshot'] = s['screenshot_path']
                    break
        except Exception:
            pass

    return step, params


def resolve_parameters(script, overrides=None):
    """
    解析脚本中的 {{param}} 模板引用，返回解析后的步骤列表。

    Args:
        script: 结构化脚本 JSON
        overrides: 用户覆盖的参数值 dict

    Returns:
        list: 解析后的步骤列表（inputs 中的模板已替换为实际值）
    """
    overrides = overrides or {}
    defaults = {k: v['default'] for k, v in script.get('parameters', {}).items()}
    merged = {**defaults, **overrides}

    resolved_steps = []
    for step in script.get('steps', []):
        if not step.get('enabled', True):
            continue
        resolved_inputs = _resolve_dict(step.get('inputs', {}), merged)
        resolved_steps.append({**step, 'inputs': resolved_inputs})

    return resolved_steps


def _resolve_dict(d, params):
    """递归解析 dict 中的 {{param}} 模板"""
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = _resolve_template(v, params)
        elif isinstance(v, list):
            result[k] = [_resolve_item(item, params) for item in v]
        elif isinstance(v, dict):
            result[k] = _resolve_dict(v, params)
        else:
            result[k] = v
    return result


def _resolve_item(item, params):
    """解析列表中的元素"""
    if isinstance(item, str):
        return _resolve_template(item, params)
    elif isinstance(item, dict):
        return _resolve_dict(item, params)
    return item


def _resolve_template(s, params):
    """将 {{param_name}} 替换为实际值"""
    def replacer(m):
        name = m.group(1)
        return str(params.get(name, m.group(0)))
    return re.sub(r'\{\{(\w+)\}\}', replacer, s)
