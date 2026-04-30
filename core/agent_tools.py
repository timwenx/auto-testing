"""
Agent 工具定义 — 为 Anthropic tool_use 定义仓库探索、浏览器操作和结果报告工具。

每个工具包含:
- schema: Anthropic tool_use 格式的工具定义 (name, description, input_schema)
- execute(input_dict, context) -> str: 执行工具并返回结果字符串

context 是一个 dict，包含:
- project: Project 对象
- page: Playwright Page 对象 (浏览器工具可用，未初始化时为 None)
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# 仓库探索工具 (4 个)
# ══════════════════════════════════════════════════════════════════

def _execute_list_files(input_dict, context):
    """列出仓库目录树结构"""
    from . import repo_service
    project = context['project']
    max_depth = input_dict.get('max_depth', 3)
    try:
        tree = repo_service.get_repo_file_tree(project, max_depth=max_depth)
        return tree if tree else "(空目录)"
    except Exception as e:
        return f"Error: {e}"


def _execute_read_file(input_dict, context):
    """读取仓库中指定文件的内容"""
    from . import repo_service
    project = context['project']
    path = input_dict['path']
    try:
        if not project.local_repo_path:
            return "Error: 仓库未克隆，请先克隆仓库"

        # 路径安全检查（与 list_directory 一致）
        from pathlib import Path
        target = Path(project.local_repo_path) / path
        try:
            target.resolve().relative_to(Path(project.local_repo_path).resolve())
        except ValueError:
            return "Error: 非法的文件路径"

        content = repo_service.read_file_content(project, path)
        return content
    except Exception as e:
        return f"Error: {e}"


def _execute_search_code(input_dict, context):
    """在仓库中搜索关键词"""
    from . import repo_service
    project = context['project']
    keyword = input_dict['keyword']
    try:
        results = repo_service.search_code(project, keyword)
        if not results:
            return f"未找到匹配 '{keyword}' 的代码"
        lines = []
        for r in results:
            lines.append(f"{r['file']}:{r['line_num']}: {r['line']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _execute_list_directory(input_dict, context):
    """列出指定目录下的文件和子目录（单层）"""
    project = context['project']
    rel_path = input_dict.get('path', '')
    try:
        if not project.local_repo_path:
            return "Error: 仓库未克隆"
        target = Path(project.local_repo_path) / rel_path
        if not target.exists():
            return f"Error: 目录不存在: {rel_path}"
        if not target.is_dir():
            return f"Error: 不是目录: {rel_path}"

        # 路径安全检查
        try:
            target.resolve().relative_to(Path(project.local_repo_path).resolve())
        except ValueError:
            return "Error: 非法的目录路径"

        IGNORED = {'.git', 'node_modules', '__pycache__', '.venv', 'venv'}
        entries = []
        for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if entry.name in IGNORED or entry.name.startswith('.'):
                continue
            suffix = '/' if entry.is_dir() else ''
            entries.append(f"  {entry.name}{suffix}")
        if not entries:
            return "(空目录)"
        return "\n".join(entries)
    except Exception as e:
        return f"Error: {e}"


REPO_TOOLS = [
    {
        'schema': {
            'name': 'list_files',
            'description': '列出项目的文件目录树结构。用于了解项目整体组织和文件布局。返回格式化的目录树文本。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'max_depth': {
                        'type': 'integer',
                        'description': '目录遍历深度，默认 3',
                        'default': 3,
                    },
                },
                'required': [],
            },
        },
        'execute': _execute_list_files,
    },
    {
        'schema': {
            'name': 'read_file',
            'description': '读取项目仓库中指定文件的完整内容。路径相对于仓库根目录。用于查看具体文件的代码实现。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': '文件的相对路径，如 "src/App.vue" 或 "package.json"',
                    },
                },
                'required': ['path'],
            },
        },
        'execute': _execute_read_file,
    },
    {
        'schema': {
            'name': 'search_code',
            'description': '在项目代码库中搜索关键词，返回匹配的文件名、行号和代码行。用于定位特定的函数、组件、路由或 API。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'keyword': {
                        'type': 'string',
                        'description': '要搜索的关键词，如函数名、路由路径、组件名等',
                    },
                },
                'required': ['keyword'],
            },
        },
        'execute': _execute_search_code,
    },
    {
        'schema': {
            'name': 'list_directory',
            'description': '列出指定目录下的文件和子目录（单层）。用于浏览特定目录的内容。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': '相对于仓库根目录的目录路径，留空表示根目录',
                        'default': '',
                    },
                },
                'required': [],
            },
        },
        'execute': _execute_list_directory,
    },
]


# ══════════════════════════════════════════════════════════════════
# Playwright 浏览器工具
# ══════════════════════════════════════════════════════════════════

# ---------- 共用 JS 片段 ----------

_JS_COLLECT_ATTRS = """
    const ATTRS = ['id','class','name','type','placeholder','value',
                   'href','src','alt','title','role','aria-label',
                   'data-testid','disabled','readonly','required',
                   'action','method','for','label','selected','checked'];
    function getAttrs(el) {
        const parts = [];
        for (const a of ATTRS) {
            const v = el.getAttribute(a);
            if (v !== null && v !== '') {
                if (a === 'class') {
                    parts.push('class="' + v.trim().split(/\\s+/).slice(0,3).join(' ') + '"');
                } else if (['disabled','readonly','required','selected','checked'].includes(a)) {
                    parts.push(a);
                } else {
                    parts.push(a + '="' + (v.length > 80 ? v.substring(0,80)+'...' : v) + '"');
                }
            }
        }
        return parts.join(' ');
    }
"""

_JS_SNAPSHOT = """
() => {
    const SKIP = new Set(['script','style','noscript','svg','path','br','hr','wbr','iframe']);
    const INTERACTIVE = new Set(['input','button','select','textarea','a','option']);
    const HEADING = new Set(['h1','h2','h3','h4','h5','h6']);
    const STRUCT = new Set(['form','table','thead','tbody','tr','td','th','ul','ol','li',
                            'details','summary','dialog','nav','header','footer','main',
                            'section','article','aside','div','span','label','fieldset',
                            'legend','img','video']);

    function describe(el, depth) {
        if (depth > 8) return null;
        const tag = el.tagName.toLowerCase();
        if (SKIP.has(tag) || !el.checkVisibility()) return null;

        const node = { tag };

        // 收集属性
        const attrParts = [];
        for (const a of ['id','class','name','type','placeholder','value','href','src',
                         'alt','title','role','aria-label','data-testid','disabled',
                         'readonly','required','action','method','for','selected','checked']) {
            const v = el.getAttribute(a);
            if (v !== null && v !== '') {
                if (a === 'class') attrParts.push('class="' + v.trim().split(/\\s+/).slice(0,3).join(' ') + '"');
                else if (['disabled','readonly','required','selected','checked'].includes(a)) attrParts.push(a);
                else attrParts.push(a + '="' + (v.length > 80 ? v.substring(0,80)+'...' : v) + '"');
            }
        }
        node.attrs = attrParts.join(' ');

        // 直接文本 (不包含子元素的文本)
        let directText = '';
        for (const child of el.childNodes) {
            if (child.nodeType === 3) directText += child.textContent;
        }
        node.text = directText.trim().substring(0, 150);

        // 递归子元素
        const children = [];
        for (const child of el.children) {
            const c = describe(child, depth + 1);
            if (c) children.push(c);
        }
        node.children = children;
        return node;
    }

    // 判断节点是否"有意义" (有属性、有文本、或是结构容器)
    function isMeaningful(node) {
        if (!node) return false;
        if (node.attrs && node.attrs.length > 0) return true;
        if (node.text && node.text.length >= 1) return true;
        if (INTERACTIVE.has(node.tag)) return true;
        if (HEADING.has(node.tag)) return true;
        if (node.children && node.children.length > 0) return true;
        return false;
    }

    // 裁剪: 去掉无意义的中间节点，只保留叶子结构
    function prune(node) {
        if (!node) return null;
        if (node.children) {
            node.children = node.children.map(prune).filter(isMeaningful);
        }
        // 如果是纯 div/span 且无属性无文本只有一个子节点，则提升子节点
        if (['div','span'].includes(node.tag) && !node.attrs && !node.text
            && node.children && node.children.length === 1) {
            return node.children[0];
        }
        return node;
    }

    // 估算输出大小，如果太大就截断
    function countNodes(node) {
        if (!node) return 0;
        let c = 1;
        if (node.children) for (const ch of node.children) c += countNodes(ch);
        return c;
    }

    const body = document.body;
    if (!body) return { url: location.href, title: document.title || '', tree: null };

    let tree = describe(body, 0);
    tree = prune(tree);

    // 如果节点数 > 150，尝试只保留交互元素附近的上下文
    if (countNodes(tree) > 150) {
        function keepImportant(node, depth) {
            if (!node) return null;
            const important = INTERACTIVE.has(node.tag) || HEADING.has(node.tag) || node.attrs;
            const newObj = { tag: node.tag, attrs: node.attrs, text: node.text };
            if (node.children) {
                newObj.children = node.children
                    .map(c => keepImportant(c, depth + 1))
                    .filter(c => c !== null);
            }
            // 保留: 交互元素、标题、有文本的元素、有 id/name 的元素
            if (important || (node.text && node.text.length > 0) ||
                (newObj.children && newObj.children.length > 0)) {
                return newObj;
            }
            return null;
        }
        tree = keepImportant(tree, 0) || tree;
    }

    return { url: location.href, title: document.title || '', tree };
}
"""

_JS_SNAPSHOT_INTERACTIVE = """
(rootSel) => {
    const SKIP = new Set(['script','style','noscript','svg','path','br','hr','wbr','iframe']);
    const INTERACTIVE = new Set(['input','button','select','textarea','a']);
    const LANDMARK = new Set(['form','fieldset','section','nav','header','footer','main','article','aside','dialog']);
    const ATTRS = ['id','class','name','type','placeholder','value','href','src',
                   'alt','title','role','aria-label','data-testid','disabled',
                   'readonly','required','action','method','for','selected','checked'];

    const root = rootSel ? document.querySelector(rootSel) : document.body;
    if (!root) return { url: location.href, title: document.title || '', items: [] };

    function getAttrs(el) {
        const parts = [];
        for (const a of ATTRS) {
            const v = el.getAttribute(a);
            if (v !== null && v !== '') {
                if (a === 'class') parts.push('class="' + v.trim().split(/\\s+/).slice(0,3).join(' ') + '"');
                else if (['disabled','readonly','required','selected','checked'].includes(a)) parts.push(a);
                else parts.push(a + '="' + (v.length > 80 ? v.substring(0,80)+'...' : v) + '"');
            }
        }
        return parts.join(' ');
    }

    function findLandmark(el) {
        let cur = el.parentElement;
        while (cur && cur !== document.body) {
            const tag = cur.tagName.toLowerCase();
            if (LANDMARK.has(tag) || /^h[1-6]$/.test(tag)) {
                const id = cur.id ? '#' + cur.id : '';
                const name = cur.getAttribute('name') ? '[name=' + cur.getAttribute('name') + ']' : '';
                let text = '';
                if (/^h[1-6]$/.test(tag)) {
                    text = cur.textContent.trim().substring(0, 60);
                }
                return { tag, id, name, text };
            }
            cur = cur.parentElement;
        }
        return null;
    }

    const items = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    while (walker.nextNode()) {
        const el = walker.currentNode;
        const tag = el.tagName.toLowerCase();
        if (SKIP.has(tag)) continue;
        if (!el.checkVisibility()) continue;
        if (!INTERACTIVE.has(tag)) continue;

        // Skip nested options inside select (select itself is enough)
        if (tag === 'option') continue;

        const attrs = getAttrs(el);
        const landmark = findLandmark(el);
        let text = '';
        if (tag === 'a') {
            text = (el.textContent || '').trim().substring(0, 100);
        }

        items.push({ tag, attrs, text, parent: landmark });
    }
    return { url: location.href, title: document.title || '', items };
}
"""

_JS_SNAPSHOT_FORMS = """
(rootSel) => {
    const ATTRS = ['id','class','name','type','placeholder','value',
                   'disabled','readonly','required','action','method'];

    function getAttrs(el) {
        const parts = [];
        for (const a of ATTRS) {
            const v = el.getAttribute(a);
            if (v !== null && v !== '') {
                if (a === 'class') parts.push('class="' + v.trim().split(/\\s+/).slice(0,3).join(' ') + '"');
                else if (['disabled','readonly','required'].includes(a)) parts.push(a);
                else parts.push(a + '="' + (v.length > 80 ? v.substring(0,80)+'...' : v) + '"');
            }
        }
        return parts.join(' ');
    }

    function buildSelector(el) {
        if (el.id) return '#' + el.id;
        if (el.name) return el.tagName.toLowerCase() + '[name=' + el.name + ']';
        return getAttrs(el) || el.tagName.toLowerCase();
    }

    function extractField(el) {
        const tag = el.tagName.toLowerCase();
        const info = {
            tag,
            selector: buildSelector(el),
            id: el.id || '',
            name: el.name || '',
            type: el.getAttribute('type') || (tag === 'textarea' ? 'textarea' : tag === 'select' ? 'select' : 'text'),
            placeholder: el.placeholder || '',
            value: el.value || '',
            required: el.required,
            disabled: el.disabled,
            readonly: el.readOnly,
        };
        if (tag === 'select') {
            info.options = Array.from(el.options).map(o => ({
                value: o.value,
                label: o.textContent.trim(),
                selected: o.selected,
            }));
        }
        return info;
    }

    function extractForm(formEl) {
        const formInfo = {
            form_id: formEl.id || '',
            form_name: formEl.name || '',
            action: formEl.action || '',
            method: formEl.method || 'get',
            selector: formEl.id ? '#' + formEl.id : (formEl.name ? 'form[name=' + formEl.name + ']' : 'form'),
            fields: [],
            submit_buttons: [],
        };
        const inputs = formEl.querySelectorAll('input, select, textarea');
        for (const el of inputs) {
            const type = (el.getAttribute('type') || '').toLowerCase();
            if (['hidden','submit','button','reset','image'].includes(type)) {
                if (type === 'submit' || type === 'image') {
                    formInfo.submit_buttons.push({
                        selector: buildSelector(el),
                        text: el.value || el.alt || 'Submit',
                    });
                }
                continue;
            }
            formInfo.fields.push(extractField(el));
        }
        const btns = formEl.querySelectorAll('button');
        for (const btn of btns) {
            const type = (btn.getAttribute('type') || 'submit').toLowerCase();
            if (type === 'submit') {
                formInfo.submit_buttons.push({
                    selector: buildSelector(btn),
                    text: btn.textContent.trim().substring(0, 50),
                });
            }
        }
        return formInfo;
    }

    const root = rootSel ? document.querySelector(rootSel) : document.body;
    if (!root) return [];
    const forms = root.querySelectorAll('form');
    if (forms.length > 0) return Array.from(forms).map(extractForm);
    return [extractForm(root)];
}
"""

_JS_SNAPSHOT_TEXT = """
(rootSel) => {
    const SKIP = new Set(['script','style','noscript','svg','path','br','hr','wbr','iframe']);
    const HEADING = new Set(['h1','h2','h3','h4','h5','h6']);

    const root = rootSel ? document.querySelector(rootSel) : document.body;
    if (!root) return { url: location.href, title: document.title || '', sections: [] };

    const sections = [];
    let current = { heading: '(页面顶部)', texts: [] };

    function walk(el) {
        const tag = el.tagName.toLowerCase();
        if (SKIP.has(tag)) return;
        if (!el.checkVisibility()) return;

        if (HEADING.has(tag)) {
            if (current.texts.length > 0 || current.heading !== '(页面顶部)') {
                sections.push(current);
            }
            current = { heading: tag + ': ' + el.textContent.trim().substring(0, 100), texts: [] };
            return;
        }

        // Direct text only
        let directText = '';
        for (const child of el.childNodes) {
            if (child.nodeType === 3) directText += child.textContent;
        }
        const trimmed = directText.trim();
        if (trimmed.length > 0) {
            current.texts.push(trimmed.substring(0, 200));
        }

        for (const child of el.children) {
            walk(child);
        }
    }

    walk(root);
    if (current.texts.length > 0) sections.push(current);
    return { url: location.href, title: document.title || '', sections };
}
"""

_JS_GET_FORM = """
function extractForm(formEl) {
    function buildSelector(el) {
        if (el.id) return '#' + el.id;
        if (el.name) return el.tagName.toLowerCase() + '[name=' + el.name + ']';
        return el.tagName.toLowerCase();
    }

    const formInfo = {
        form_id: formEl.id || '',
        form_name: formEl.name || '',
        action: formEl.action || '',
        method: formEl.method || 'get',
        selector: formEl.id ? '#' + formEl.id : (formEl.name ? 'form[name=' + formEl.name + ']' : 'form'),
        fields: [],
        submit_buttons: [],
    };
    const inputs = formEl.querySelectorAll('input, select, textarea');
    for (const el of inputs) {
        const type = (el.getAttribute('type') || '').toLowerCase();
        if (['hidden','submit','button','reset','image'].includes(type)) {
            if (type === 'submit' || type === 'image') {
                formInfo.submit_buttons.push({
                    selector: buildSelector(el),
                    text: el.value || el.alt || 'Submit',
                });
            }
            continue;
        }
        const info = {
            tag: el.tagName.toLowerCase(),
            selector: buildSelector(el),
            id: el.id || '',
            name: el.name || '',
            type: el.getAttribute('type') || (el.tagName.toLowerCase() === 'textarea' ? 'textarea' : el.tagName.toLowerCase() === 'select' ? 'select' : 'text'),
            placeholder: el.placeholder || '',
            value: el.value || '',
            required: el.required,
            disabled: el.disabled,
            readonly: el.readOnly,
        };
        if (el.tagName.toLowerCase() === 'select') {
            info.options = Array.from(el.options).map(o => ({
                value: o.value,
                label: o.textContent.trim(),
                selected: o.selected,
            }));
        }
        formInfo.fields.push(info);
    }
    const btns = formEl.querySelectorAll('button');
    for (const btn of btns) {
        const type = (btn.getAttribute('type') || 'submit').toLowerCase();
        if (type === 'submit') {
            formInfo.submit_buttons.push({
                selector: buildSelector(btn),
                text: btn.textContent.trim().substring(0, 50),
            });
        }
    }
    return formInfo;
}
"""


def _format_tree(node, indent=0, max_lines=120):
    """将 DOM 树格式化为缩进文本，限制总行数"""
    lines = []
    _format_tree_recursive(node, indent, lines, [0], max_lines)
    return "\n".join(lines)


def _format_tree_recursive(node, indent, lines, counter, max_lines):
    if not node or counter[0] >= max_lines:
        return
    pad = "  " * indent
    tag = node.get('tag', '?')
    attrs = node.get('attrs', '')
    text = node.get('text', '')
    children = node.get('children', [])

    # 选择图标
    icon = ''
    if tag in ('input', 'select', 'textarea'):
        icon = '🔤 '
    elif tag == 'button' or tag == 'a':
        icon = '👆 '
    elif tag in ('h1','h2','h3','h4','h5','h6'):
        icon = '📌 '
    elif tag == 'img':
        icon = '🖼️ '
    elif tag == 'form':
        icon = '📋 '
    elif tag == 'table':
        icon = '📊 '

    attr_str = f" {attrs}" if attrs else ""
    text_str = f" \"{text}\"" if text else ""
    lines.append(f"{pad}{icon}<{tag}{attr_str}>{text_str}")
    counter[0] += 1

    if children:
        for child in children:
            if counter[0] >= max_lines:
                lines.append(f"{pad}  ... (截断，用 browser_query_all 获取更多)")
                return
            _format_tree_recursive(child, indent + 1, lines, counter, max_lines)


def _snapshot_page(page):
    """获取页面快照: URL + 标题 + 结构化 DOM 树。供多个工具复用。"""
    return page.evaluate(_JS_SNAPSHOT)


def _format_snapshot(snap):
    """格式化 snapshot 结果为结构化 DOM 树文本"""
    lines = [f"📄 URL: {snap['url']}", f"📌 标题: {snap.get('title', '')}"]
    tree = snap.get('tree')
    if tree:
        lines.append("\n[页面结构]")
        lines.append(_format_tree(tree))
    else:
        lines.append("\n(页面无可见内容)")
    return "\n".join(lines)


def _format_interactive(snap):
    """格式化 interactive 模式结果为扁平列表"""
    lines = [f"📄 URL: {snap['url']}", f"📌 标题: {snap.get('title', '')}"]
    items = snap.get('items', [])
    if not items:
        lines.append("\n(无可交互元素)")
        return "\n".join(lines)

    lines.append(f"\n[可交互元素] ({len(items)} 个)")

    # 按 parent 分组显示
    current_parent = None
    for item in items:
        parent = item.get('parent')
        parent_key = ''
        if parent:
            ptag = parent.get('tag', '')
            pid = parent.get('id', '')
            pname = parent.get('name', '')
            ptext = parent.get('text', '')
            parent_key = f"{ptag}{'#' + pid if pid else ''}{'[name=' + pname + ']' if pname else ''}"
            if ptext:
                parent_key += f' "{ptext}"'
        else:
            parent_key = '(页面根部)'

        if parent_key != current_parent:
            current_parent = parent_key
            lines.append(f"\n  [{parent_key}]")

        tag = item['tag']
        icon = '🔤 ' if tag in ('input', 'select', 'textarea') else '👆 '
        attrs = item.get('attrs', '')
        text = item.get('text', '')
        line = f"    {icon}<{tag}"
        if attrs:
            line += f" {attrs}"
        line += ">"
        if text:
            line += f' "{text}"'
        lines.append(line)

    return "\n".join(lines)


def _format_forms(forms_data):
    """格式化 forms 模式结果为结构化 JSON"""
    if not forms_data:
        return "(未找到表单)"
    return json.dumps(forms_data, ensure_ascii=False, indent=2)


def _format_text(snap):
    """格式化 text 模式结果为纯文本"""
    lines = [f"📄 URL: {snap['url']}", f"📌 标题: {snap.get('title', '')}"]
    sections = snap.get('sections', [])
    if not sections:
        lines.append("\n(页面无可见文本)")
        return "\n".join(lines)

    for sec in sections:
        lines.append(f"\n## {sec['heading']}")
        for t in sec.get('texts', []):
            lines.append(f"  {t}")

    return "\n".join(lines)


def _get_snapshot(page, mode='interactive', selector=''):
    """统一的快照获取入口，根据 mode 路由到不同的 JS 和格式化函数"""
    if mode == 'full':
        snap = page.evaluate(_JS_SNAPSHOT) if not selector else page.locator(selector).evaluate(_JS_SNAPSHOT)
        return _format_snapshot(snap)
    elif mode == 'interactive':
        snap = page.evaluate(_JS_SNAPSHOT_INTERACTIVE, selector)
        return _format_interactive(snap)
    elif mode == 'forms':
        result = page.evaluate(_JS_SNAPSHOT_FORMS, selector)
        return _format_forms(result)
    elif mode == 'text':
        snap = page.evaluate(_JS_SNAPSHOT_TEXT, selector)
        return _format_text(snap)
    else:
        return f"Error: 未知 mode '{mode}'，支持: interactive, forms, full, text"


# ---------- 工具实现 ----------

def _execute_browser_navigate(input_dict, context):
    """导航到指定 URL，等待加载完成后自动返回页面快照"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    url = input_dict['url']
    wait_until = input_dict.get('wait_until', 'domcontentloaded')
    try:
        page.goto(url, wait_until=wait_until, timeout=30000)
        # 自动等待网络空闲
        try:
            page.wait_for_load_state('networkidle', timeout=5000)
        except Exception:
            pass
        # 返回页面快照，省去额外调用
        snap = _snapshot_page(page)
        return f"✅ 已导航到: {page.url}\n\n{_format_snapshot(snap)}"
    except Exception as e:
        return f"Error navigating to {url}: {e}"


def _execute_browser_click(input_dict, context):
    """点击元素，自动处理 confirm/alert 弹窗，支持等待页面响应。失败时自动诊断。"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    selector = input_dict['selector']
    wait_for = input_dict.get('wait_for', '')
    wait_nav = input_dict.get('wait_for_navigation', False)
    wait_warning = ''
    dialog_info = ''

    # 注册 dialog 处理器：自动接受 confirm/alert/prompt
    dialogs_seen = []
    def _on_dialog(dialog):
        dialogs_seen.append(dialog.message)
        dialog.accept()
    page.on('dialog', _on_dialog)

    try:
        old_url = page.url
        page.click(selector, timeout=10000)

        if dialogs_seen:
            dialog_info = f"\n💬 检测到弹窗已自动确认: {'; '.join(dialogs_seen[:3])}"

        # 等待策略：优先用 wait_for，其次 wait_for_navigation，最后自动检测
        if wait_for:
            try:
                page.wait_for_selector(wait_for, timeout=10000)
            except Exception:
                wait_warning = f"\n⚠️ 等待 '{wait_for}' 超时，但点击已成功"
        elif wait_nav:
            try:
                page.wait_for_load_state('domcontentloaded', timeout=15000)
            except Exception:
                wait_warning = "\n⚠️ 等待页面导航超时"
        else:
            # 自动检测：如果 URL 变了，等待新页面加载
            import time as _time
            _time.sleep(0.3)
            if page.url != old_url:
                try:
                    page.wait_for_load_state('domcontentloaded', timeout=10000)
                except Exception:
                    pass
            else:
                _time.sleep(0.2)

        snap = _snapshot_page(page)
        return f"✅ 已点击: {selector}{dialog_info}{wait_warning}\n\n{_format_snapshot(snap)}"
    except Exception as click_err:
        diagnosis = _diagnose_click_failure(page, selector)
        try:
            snap = _snapshot_page(page)
            snap_text = f"\n\n{_format_snapshot(snap)}"
        except Exception:
            snap_text = ""
        return f"❌ 点击失败: {selector}\n原因: {click_err}\n{diagnosis}{snap_text}"
    finally:
        # 移除 dialog 监听，避免影响后续操作
        try:
            page.remove_listener('dialog', _on_dialog)
        except Exception:
            pass


def _diagnose_click_failure(page, selector):
    """诊断点击失败的原因，返回可读的诊断信息"""
    try:
        diag = page.evaluate(f"""(selector) => {{
            const el = document.querySelector(selector);
            if (!el) {{
                // 尝试模糊匹配
                const all = document.querySelectorAll('button, input[type="submit"], input[type="button"], a');
                const similar = [];
                for (const e of all) {{
                    const id = e.id || '';
                    const text = (e.textContent || '').trim().substring(0, 30);
                    const cls = e.className || '';
                    if (id.includes('btn') || id.includes('submit') || text.includes('提交') || text.includes('保存') || text.includes('Submit')) {{
                        similar.push({{ tag: e.tagName, id, text, type: e.type || '' }});
                    }}
                }}
                return {{ exists: false, similar }};
            }}

            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            const visible = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';

            // 检查是否被遮挡
            let covered = false;
            if (visible) {{
                const cx = rect.left + rect.width / 2;
                const cy = rect.top + rect.height / 2;
                const topEl = document.elementFromPoint(cx, cy);
                covered = topEl !== el && !el.contains(topEl);
            }}

            return {{
                exists: true,
                visible,
                disabled,
                covered,
                rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
                display: style.display,
                opacity: style.opacity,
                tag: el.tagName,
                type: el.type || '',
            }};
        }}""", selector)

        if not diag.get('exists'):
            lines = ["诊断: 元素不存在"]
            similar = diag.get('similar', [])
            if similar:
                lines.append("页面上发现类似的按钮:")
                for s in similar[:5]:
                    lines.append(f"  - <{s['tag']}> id=\"{s['id']}\" type=\"{s['type']}\" text=\"{s['text']}\"")
            else:
                lines.append("页面上没有找到类似的按钮元素")
            return "\n".join(lines)

        lines = []
        if not diag.get('visible'):
            lines.append(f"诊断: 元素不可见 (display={diag.get('display')}, opacity={diag.get('opacity')}, size={diag.get('rect', {}).get('width')}x{diag.get('rect', {}).get('height')})")
        if diag.get('disabled'):
            lines.append("诊断: 元素被禁用 (disabled)")
        if diag.get('covered'):
            lines.append("诊断: 元素被其他元素遮挡，无法点击")
        if not lines:
            lines.append(f"诊断: 元素存在且可见，但点击仍然失败 (tag={diag.get('tag')}, type={diag.get('type')})")
        return "\n".join(lines)
    except Exception:
        return ""


def _execute_browser_fill(input_dict, context):
    """填写单个输入框，失败时自动诊断原因"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    selector = input_dict['selector']
    value = input_dict['value']
    try:
        page.fill(selector, value, timeout=10000)
        snap = _snapshot_page(page)
        display_val = value[:50] + ('...' if len(value) > 50 else '')
        return f"✅ 已填写 '{selector}': {display_val}\n\n{_format_snapshot(snap)}"
    except Exception as fill_err:
        diagnosis = _diagnose_element_failure(page, selector, 'fill')
        try:
            snap = _snapshot_page(page)
            snap_text = f"\n\n{_format_snapshot(snap)}"
        except Exception:
            snap_text = ""
        return f"❌ 填写失败: {selector}\n原因: {fill_err}\n{diagnosis}{snap_text}"


def _diagnose_element_failure(page, selector, action='click'):
    """通用元素诊断：检查元素是否存在、可见、可用"""
    try:
        diag = page.evaluate(f"""(selector) => {{
            const el = document.querySelector(selector);
            if (!el) return {{ exists: false }};
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            const visible = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            const disabled = el.disabled || el.readOnly || el.getAttribute('aria-disabled') === 'true';
            return {{
                exists: true,
                visible,
                disabled,
                tag: el.tagName,
                type: el.type || '',
                display: style.display,
                readOnly: el.readOnly || false,
            }};
        }}""", selector)

        if not diag.get('exists'):
            return f"诊断: 选择器 '{selector}' 未匹配到任何元素，请检查选择器是否正确"
        if not diag.get('visible'):
            return f"诊断: 元素不可见 (display={diag.get('display')}), 可能被隐藏或在屏幕外"
        if diag.get('disabled'):
            if action == 'fill' and diag.get('readOnly'):
                return "诊断: 元素是只读的 (readonly), 无法填写"
            return "诊断: 元素被禁用 (disabled)"
        return ""
    except Exception:
        return ""


def _execute_browser_fill_form(input_dict, context):
    """一次填写多个表单字段，可选择是否自动点击提交按钮"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    fields = input_dict['fields']  # [{"selector": "...", "value": "..."}, ...]
    submit_selector = input_dict.get('submit_selector', '')
    results = []
    try:
        for f in fields:
            sel, val = f['selector'], f['value']
            try:
                page.fill(sel, val, timeout=10000)
                results.append(f"✅ {sel} = {val[:50]}")
            except Exception as e:
                results.append(f"❌ {sel}: {e}")
        # 可选: 自动点击提交
        if submit_selector:
            try:
                page.click(submit_selector, timeout=10000)
                import time as _time
                _time.sleep(0.5)
                results.append(f"✅ 已点击提交: {submit_selector}")
            except Exception as e:
                results.append(f"❌ 提交 {submit_selector}: {e}")
        snap = _snapshot_page(page)
        return "\n".join(results) + f"\n\n{_format_snapshot(snap)}"
    except Exception as e:
        return f"Error: {e}"


def _execute_browser_select(input_dict, context):
    """选择下拉框选项"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    selector = input_dict['selector']
    value = input_dict.get('value', '')
    label = input_dict.get('label', '')
    try:
        if label:
            page.select_option(selector, label=label, timeout=10000)
        elif value:
            page.select_option(selector, value=value, timeout=10000)
        else:
            return "Error: 必须指定 value 或 label"
        snap = _snapshot_page(page)
        chosen = label or value
        return f"✅ 已选择 '{selector}': {chosen}\n\n{_format_snapshot(snap)}"
    except Exception as e:
        return f"Error selecting {selector}: {e}"


def _execute_browser_press_key(input_dict, context):
    """按下键盘按键"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    key = input_dict['key']
    try:
        page.keyboard.press(key)
        import time as _time
        _time.sleep(0.3)
        snap = _snapshot_page(page)
        return f"✅ 已按下: {key}\n\n{_format_snapshot(snap)}"
    except Exception as e:
        return f"Error pressing key {key}: {e}"


def _execute_browser_snapshot(input_dict, context):
    """获取当前页面快照，支持多种探索模式。"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    mode = input_dict.get('mode', 'interactive')
    selector = input_dict.get('selector', '')
    try:
        return _get_snapshot(page, mode=mode, selector=selector)
    except Exception as e:
        return f"Error: {e}"


def _execute_browser_query_all(input_dict, context):
    """根据 CSS 选择器批量获取匹配元素的详细属性和文本，支持多个选择器一次查询"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"

    # 支持 selector (string) 和 selectors (array)，向后兼容
    selector = input_dict.get('selector', '')
    selectors = input_dict.get('selectors', [])
    if not selectors and selector:
        selectors = [selector]
    if not selectors:
        return "Error: 必须指定 selector 或 selectors"

    query_js = f"""(selector) => {{
        {_JS_COLLECT_ATTRS}
        const els = document.querySelectorAll(selector);
        const items = [];
        for (const el of els) {{
            const tag = el.tagName.toLowerCase();
            const attrs = getAttrs(el);
            let text = (el.innerText || '').trim();
            if (text.length > 200) text = text.substring(0, 200) + '...';
            items.push({{ tag, attrs, text }});
        }}
        return items;
    }}"""

    try:
        if len(selectors) == 1:
            # 单选择器：保持原有输出格式
            sel = selectors[0]
            results = page.evaluate(query_js, sel)
            if not results:
                return f"未找到匹配 '{sel}' 的元素"
            lines = []
            for i, item in enumerate(results):
                line = f"[{i}] <{item['tag']}"
                if item['attrs']:
                    line += f" {item['attrs']}"
                line += ">"
                if item['text']:
                    line += f" {item['text']}"
                lines.append(line)
                if len(lines) >= 50:
                    lines.append(f"... 共 {len(results)} 个元素，截断显示前 50 个")
                    break
            return f"共找到 {len(results)} 个匹配 '{sel}' 的元素:\n" + "\n".join(lines)
        else:
            # 多选择器：按分组返回
            all_lines = []
            total = 0
            for sel in selectors:
                results = page.evaluate(query_js, sel)
                count = len(results)
                total += count
                all_lines.append(f"\n=== {sel} ({count} 个匹配) ===")
                if not results:
                    all_lines.append("  (无匹配)")
                    continue
                for i, item in enumerate(results):
                    line = f"  [{i}] <{item['tag']}"
                    if item['attrs']:
                        line += f" {item['attrs']}"
                    line += ">"
                    if item['text']:
                        line += f" {item['text']}"
                    all_lines.append(line)
                    if i >= 49:
                        all_lines.append(f"  ... 共 {count} 个元素，截断显示前 50 个")
                        break
            return f"共查询 {len(selectors)} 个选择器，找到 {total} 个元素:" + "\n".join(all_lines)
    except Exception as e:
        return f"Error querying selectors: {e}"


def _execute_browser_get_text(input_dict, context):
    """获取单个元素的文本内容，用于精确验证特定元素"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    selector = input_dict['selector']
    try:
        text = page.text_content(selector, timeout=10000)
        if text:
            text = text.strip()
            if len(text) > 2000:
                text = text[:2000] + "\n... (已截断)"
            return text
        return "(元素文本为空)"
    except Exception as e:
        return f"Error getting text from {selector}: {e}"


def _execute_browser_screenshot(input_dict, context):
    """对当前页面截图，保存到 media/{execution_id}/"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    save_path = input_dict.get('save_path', '')
    try:
        if not save_path:
            from django.conf import settings as django_settings
            execution_id = context.get('execution_id', 'unknown')
            counter = context.get('screenshot_counter', 0) + 1
            context['screenshot_counter'] = counter
            screenshot_dir = os.path.join(
                str(django_settings.MEDIA_ROOT),
                str(execution_id),
            )
            os.makedirs(screenshot_dir, exist_ok=True)
            save_path = os.path.join(screenshot_dir, f'step_{counter}.png')
        page.screenshot(path=save_path, full_page=True)
        context['last_screenshot'] = save_path
        return f"截图已保存: {save_path}"
    except Exception as e:
        return f"Error taking screenshot: {e}"


def _execute_browser_batch_action(input_dict, context):
    """依次执行多个浏览器操作，所有操作完成后只返回一次页面快照。自动处理 confirm/alert 弹窗。"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"

    actions = input_dict['actions']
    delay = input_dict.get('delay_between', 20) / 1000.0  # ms -> seconds
    results = []
    dialogs_seen = []

    # 注册全局 dialog 处理器：自动接受 confirm/alert/prompt
    def _on_dialog(dialog):
        dialogs_seen.append(dialog.message)
        dialog.accept()
    page.on('dialog', _on_dialog)

    try:
        for i, action in enumerate(actions):
            action_type = action.get('type', '')
            try:
                if action_type == 'click':
                    old_url = page.url
                    page.click(action['selector'], timeout=10000)
                    import time as _t
                    _t.sleep(0.3)
                    if page.url != old_url:
                        try:
                            page.wait_for_load_state('domcontentloaded', timeout=10000)
                        except Exception:
                            pass
                elif action_type == 'fill':
                    page.fill(action['selector'], action['value'], timeout=10000)
                elif action_type == 'select':
                    label = action.get('label', '')
                    value = action.get('value', '')
                    if label:
                        page.select_option(action['selector'], label=label, timeout=10000)
                    elif value:
                        page.select_option(action['selector'], value=value, timeout=10000)
                    else:
                        results.append(f"❌ [{i+1}] select: 必须指定 value 或 label")
                        continue
                elif action_type == 'press_key':
                    page.keyboard.press(action['key'])
                elif action_type == 'wait':
                    sel = action.get('selector', '')
                    timeout = action.get('timeout', 5000)
                    if sel:
                        page.wait_for_selector(sel, timeout=timeout)
                    else:
                        import time as _time
                        _time.sleep(timeout / 1000.0)
                else:
                    results.append(f"❌ [{i+1}] 未知操作类型: {action_type}")
                    continue
                results.append(f"✅ [{i+1}] {action_type}")
            except Exception as e:
                results.append(f"❌ [{i+1}] {action_type}: {e}")

            # 操作间延迟
            if delay > 0 and i < len(actions) - 1:
                import time as _time
                _time.sleep(delay)

        # 所有操作完成后返回一次快照
        try:
            snap = _snapshot_page(page)
            snapshot_text = _format_snapshot(snap)
        except Exception as e:
            snapshot_text = f"(快照获取失败: {e})"

        dialog_info = ''
        if dialogs_seen:
            dialog_info = f"\n💬 检测到弹窗已自动确认: {'; '.join(dialogs_seen[:3])}\n"

        return "\n".join(results) + dialog_info + f"\n\n{snapshot_text}"
    finally:
        try:
            page.remove_listener('dialog', _on_dialog)
        except Exception:
            pass


def _execute_browser_get_form(input_dict, context):
    """提取页面表单数据为结构化 JSON"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    selector = input_dict.get('selector', '')

    try:
        result = page.evaluate(f"""(selector) => {{
            {_JS_GET_FORM}
            if (selector) {{
                const form = document.querySelector(selector);
                return form ? extractForm(form) : null;
            }}
            const forms = document.querySelectorAll('form');
            if (forms.length > 0) {{
                return Array.from(forms).map(extractForm);
            }}
            return extractForm(document.body);
        }}""", selector)

        if not result:
            return "未找到表单元素"
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error getting form: {e}"


BROWSER_TOOLS = [
    {
        'schema': {
            'name': 'browser_navigate',
            'description': '导航到指定 URL，自动等待页面加载完成，并返回页面快照（URL、标题、所有交互元素、文本内容）。无需额外调用 browser_snapshot。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'url': {
                        'type': 'string',
                        'description': '要导航到的完整 URL',
                    },
                    'wait_until': {
                        'type': 'string',
                        'description': '等待策略: "domcontentloaded"(默认) 或 "load" 或 "networkidle"',
                        'default': 'domcontentloaded',
                        'enum': ['domcontentloaded', 'load', 'networkidle'],
                    },
                },
                'required': ['url'],
            },
        },
        'execute': _execute_browser_navigate,
    },
    {
        'schema': {
            'name': 'browser_click',
            'description': '点击页面元素。自动处理 confirm/alert 弹窗（自动点确认）。'
                '点击后自动检测页面变化：如果 URL 变了会等待新页面加载，'
                '也可以用 wait_for 等待特定元素出现。失败时自动诊断原因（元素不存在/不可见/被遮挡/被禁用）并返回页面快照。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': 'CSS 选择器，如 "#login-btn"、"button[type=submit]"',
                    },
                    'wait_for': {
                        'type': 'string',
                        'description': '点击后等待此 CSS 选择器对应的元素出现，如 "#success-msg"、".result"。'
                            '适用于点击后页面异步加载内容的场景。',
                        'default': '',
                    },
                    'wait_for_navigation': {
                        'type': 'boolean',
                        'description': '点击后等待页面导航完成（URL 变化并加载）。'
                            '适用于点击后跳转到新页面的场景。',
                        'default': False,
                    },
                },
                'required': ['selector'],
            },
        },
        'execute': _execute_browser_click,
    },
    {
        'schema': {
            'name': 'browser_fill',
            'description': '填写单个输入框。填写后自动返回页面快照。如果需要一次填写多个字段，请使用 browser_fill_form。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': 'CSS 选择器，如 "input[name=\\"username\\"]"',
                    },
                    'value': {
                        'type': 'string',
                        'description': '要输入的文本',
                    },
                },
                'required': ['selector', 'value'],
            },
        },
        'execute': _execute_browser_fill,
    },
    {
        'schema': {
            'name': 'browser_fill_form',
            'description': '一次填写多个表单字段，可选自动点击提交按钮。比逐个 browser_fill 高效得多。例如填写登录表单: fields=[{"selector":"input[name=username]","value":"admin"}, {"selector":"input[name=password]","value":"123456"}], submit_selector="button[type=submit]"',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'fields': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'selector': {'type': 'string', 'description': '输入框 CSS 选择器'},
                                'value': {'type': 'string', 'description': '要填写的文本'},
                            },
                            'required': ['selector', 'value'],
                        },
                        'description': '要填写的字段列表，每个包含 selector 和 value',
                    },
                    'submit_selector': {
                        'type': 'string',
                        'description': '提交按钮的 CSS 选择器（可选）。填写完成后自动点击此按钮。',
                        'default': '',
                    },
                },
                'required': ['fields'],
            },
        },
        'execute': _execute_browser_fill_form,
    },
    {
        'schema': {
            'name': 'browser_select',
            'description': '选择下拉框(select)的选项。可通过 value 或 label(显示文本) 选择。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': '下拉框的 CSS 选择器',
                    },
                    'value': {
                        'type': 'string',
                        'description': '选项的 value 属性值',
                        'default': '',
                    },
                    'label': {
                        'type': 'string',
                        'description': '选项的显示文本',
                        'default': '',
                    },
                },
                'required': ['selector'],
            },
        },
        'execute': _execute_browser_select,
    },
    {
        'schema': {
            'name': 'browser_press_key',
            'description': '按下键盘按键（如 Enter、Escape、Tab）。按键后自动返回页面快照。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'key': {
                        'type': 'string',
                        'description': '按键名称，如 "Enter"、"Escape"、"Tab"、"ArrowDown"',
                    },
                },
                'required': ['key'],
            },
        },
        'execute': _execute_browser_press_key,
    },
    {
        'schema': {
            'name': 'browser_snapshot',
            'description': '获取当前页面快照。支持多种探索模式:\n'
                '- mode="interactive" (默认): 只返回可交互元素(input/button/select/textarea/a)及其父级上下文(form/section等)。最省 token，推荐日常使用。\n'
                '- mode="forms": 返回所有表单及其字段的结构化 JSON (含 name/type/placeholder/options)。\n'
                '- mode="full": 完整 DOM 树，仅在需要完整页面结构时使用。\n'
                '- mode="text": 只返回页面可见文本，按标题组织。\n'
                '- selector 参数: 只快照页面的某个区域，如 "#login-form"。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'mode': {
                        'type': 'string',
                        'enum': ['interactive', 'forms', 'full', 'text'],
                        'default': 'interactive',
                        'description': '探索模式: interactive=只返回可交互元素(默认), forms=表单结构化JSON, full=完整DOM树, text=纯文本',
                    },
                    'selector': {
                        'type': 'string',
                        'description': 'CSS 选择器，限定快照范围，如 "#login-form"。留空则快照整个页面。',
                        'default': '',
                    },
                },
                'required': [],
            },
        },
        'execute': _execute_browser_snapshot,
    },
    {
        'schema': {
            'name': 'browser_query_all',
            'description': '根据 CSS 选择器批量获取匹配元素的详细属性和文本。'
                '支持单个 selector 或多个 selectors 一次查询，结果按选择器分组返回。\n'
                '示例: selector="input" 或 selectors=["input","button","select"]',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': '单个 CSS 选择器（向后兼容），如 "input"、".product"',
                    },
                    'selectors': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': '多个 CSS 选择器，一次查询多个类型，如 ["input","button","select"]',
                    },
                },
                'required': [],
            },
        },
        'execute': _execute_browser_query_all,
    },
    {
        'schema': {
            'name': 'browser_get_text',
            'description': '获取单个元素的纯文本内容。仅在需要精确验证某个已知选择器的元素时使用。了解页面全貌请用 browser_snapshot，批量获取请用 browser_query_all。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': 'CSS 选择器',
                    },
                },
                'required': ['selector'],
            },
        },
        'execute': _execute_browser_get_text,
    },
    {
        'schema': {
            'name': 'browser_screenshot',
            'description': '对当前页面截图，保存为 PNG 文件。用于记录测试过程或截图留证。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'save_path': {
                        'type': 'string',
                        'description': '截图保存路径，留空自动生成',
                        'default': '',
                    },
                },
                'required': [],
            },
        },
        'execute': _execute_browser_screenshot,
    },
    {
        'schema': {
            'name': 'browser_batch_action',
            'description': '依次执行多个浏览器操作（click/fill/select/press_key/wait），所有操作完成后只返回一次页面快照。'
                '比逐个调用高效得多，适合填写表单后提交、连续点击等场景。\n'
                '示例: actions=[{"type":"fill","selector":"#user","value":"admin"},'
                '{"type":"fill","selector":"#pass","value":"123"},'
                '{"type":"click","selector":"#submit"}]',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'actions': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'type': {
                                    'type': 'string',
                                    'enum': ['click', 'fill', 'select', 'press_key', 'wait'],
                                    'description': '操作类型',
                                },
                                'selector': {
                                    'type': 'string',
                                    'description': '元素的 CSS 选择器 (click/fill/select 需要)',
                                },
                                'value': {
                                    'type': 'string',
                                    'description': '要填写的值 (fill) 或 select 的 value 属性',
                                },
                                'label': {
                                    'type': 'string',
                                    'description': 'select 的显示文本 (与 value 二选一)',
                                },
                                'key': {
                                    'type': 'string',
                                    'description': '键盘按键名称 (press_key 需要)，如 "Enter"、"Escape"',
                                },
                                'timeout': {
                                    'type': 'integer',
                                    'description': '等待超时毫秒数 (wait 可用)，默认 5000',
                                },
                            },
                            'required': ['type'],
                        },
                        'description': '操作列表，按顺序依次执行',
                    },
                    'delay_between': {
                        'type': 'integer',
                        'description': '操作之间的延迟（毫秒），默认 20。设为 0 则无延迟。',
                        'default': 20,
                    },
                },
                'required': ['actions'],
            },
        },
        'execute': _execute_browser_batch_action,
    },
    {
        'schema': {
            'name': 'browser_get_form',
            'description': '提取页面表单数据为结构化 JSON，包含所有字段的 name/type/placeholder/value/options 和提交按钮。'
                '比从快照中解析更可靠，适合精确了解表单结构。\n'
                '不传 selector 则提取页面所有表单；传 selector 提取指定表单。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': '表单的 CSS 选择器，如 "#login-form" 或 "form"。留空则提取所有表单。',
                        'default': '',
                    },
                },
                'required': [],
            },
        },
        'execute': _execute_browser_get_form,
    },
]


# ══════════════════════════════════════════════════════════════════
# report_result 工具
# ══════════════════════════════════════════════════════════════════

def _execute_report_result(input_dict, context):
    """接收 Agent 的测试结果报告"""
    context['report_result'] = {
        'status': input_dict['status'],
        'summary': input_dict['summary'],
        'details': input_dict.get('details', ''),
    }
    return f"结果已记录: {input_dict['status']} — {input_dict['summary']}"


REPORT_RESULT_TOOL = {
    'schema': {
        'name': 'report_result',
        'description': '报告测试执行结果。当测试完成时（无论通过或失败），必须调用此工具报告最终结果。',
        'input_schema': {
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string',
                    'enum': ['passed', 'failed', 'error'],
                    'description': '测试结果状态: passed（通过）、failed（失败）、error（异常）',
                },
                'summary': {
                    'type': 'string',
                    'description': '结果的一句话总结',
                },
                'details': {
                    'type': 'string',
                    'description': '详细的结果说明，包括测试了什么、发现的问题等',
                    'default': '',
                },
            },
            'required': ['status', 'summary'],
        },
    },
    'execute': _execute_report_result,
}


# ══════════════════════════════════════════════════════════════════
# 工具注册表
# ══════════════════════════════════════════════════════════════════

def get_all_tools():
    """返回所有工具定义列表 (repo + browser + report_result)"""
    return REPO_TOOLS + BROWSER_TOOLS + [REPORT_RESULT_TOOL]


def get_tool_schemas():
    """返回 Anthropic tool_use 格式的 schema 列表（仅 schema 部分）"""
    return [tool['schema'] for tool in get_all_tools()]


def get_tool_executor(tool_name):
    """根据工具名查找 execute 函数，未找到返回 None"""
    for tool in get_all_tools():
        if tool['schema']['name'] == tool_name:
            return tool['execute']
    return None


def get_browser_tool_names():
    """返回所有浏览器工具的名称集合"""
    return {tool['schema']['name'] for tool in BROWSER_TOOLS}


# ══════════════════════════════════════════════════════════════════
# System Prompt 构建
# ══════════════════════════════════════════════════════════════════

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'templates', 'agent_execute_prompt.md')


def build_test_execution_system_prompt(testcase, base_url: str, project) -> str:
    """
    构建 Agent 执行测试用例的 system prompt。

    Args:
        testcase: TestCase 对象
        base_url: 测试目标 URL
        project: Project 对象

    Returns:
        格式化后的 system prompt 字符串
    """
    # 加载模板
    try:
        with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            template = f.read()
    except FileNotFoundError:
        logger.warning("Agent prompt template not found at %s", _TEMPLATE_PATH)
        template = _get_fallback_template()

    # 准备 markdown_section
    if testcase.markdown_content:
        markdown_section = f"### 完整用例文档\n{testcase.markdown_content}"
    else:
        markdown_section = ''

    # 准备 repo_info
    repo_info = ''
    if project.repo_url:
        repo_info = f"- Git 仓库: {project.repo_url}\n- 本地路径: {project.local_repo_path or '未克隆'}"

    return template.format(
        project_name=project.name,
        base_url=base_url,
        repo_info=repo_info,
        testcase_name=testcase.name,
        testcase_description=testcase.description or '无描述',
        testcase_steps=testcase.steps or '无步骤',
        testcase_expected=testcase.expected_result or '无预期结果',
        markdown_section=markdown_section,
    )


def _get_fallback_template() -> str:
    """当模板文件不存在时的备用模板"""
    return (
        "你是一个自动化测试工程师。请使用提供的工具完成以下测试。\n\n"
        "项目: {project_name} | URL: {base_url}\n"
        "{repo_info}\n\n"
        "用例: {testcase_name}\n描述: {testcase_description}\n\n"
        "步骤:\n{testcase_steps}\n\n预期结果:\n{testcase_expected}\n\n"
        "{markdown_section}\n\n"
        "工作流程: 探索代码 → 规划测试 → 执行操作 → report_result 报告结果。"
    )
