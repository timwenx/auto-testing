from django.db import models
from django.conf import settings


class Project(models.Model):
    """测试项目"""
    name = models.CharField('项目名称', max_length=200)
    description = models.TextField('项目描述', blank=True, default='')
    base_url = models.CharField('测试目标 URL', max_length=500, blank=True, default='')
    # Git 仓库配置
    repo_url = models.CharField('Git 仓库地址', max_length=500, blank=True, default='')
    repo_username = models.CharField('仓库账号', max_length=200, blank=True, default='')
    repo_password = models.CharField('仓库凭证/密码', max_length=500, blank=True, default='')
    github_url = models.CharField('GitHub 地址', max_length=500, blank=True, default='')
    github_token = models.CharField('GitHub Token', max_length=500, blank=True, default='')
    local_repo_path = models.CharField('本地仓库路径', max_length=500, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = '项目'
        verbose_name_plural = '项目'

    def __str__(self):
        return self.name

    @property
    def testcase_count(self):
        return self.testcases.count()

    @property
    def last_execution(self):
        return self.executions.order_by('-created_at').first()


class TestCase(models.Model):
    """测试用例"""
    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('ready', '就绪'),
        ('running', '运行中'),
        ('passed', '通过'),
        ('failed', '失败'),
    ]

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name='testcases', verbose_name='所属项目'
    )
    name = models.CharField('用例名称', max_length=300)
    description = models.TextField('用例描述', blank=True, default='')
    steps = models.TextField('测试步骤', help_text='自然语言描述的测试步骤')
    expected_result = models.TextField('预期结果')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='draft')
    is_ai_generated = models.BooleanField('AI 生成', default=False)
    markdown_content = models.TextField('Markdown 内容', blank=True, default='')
    priority = models.CharField(
        '优先级', max_length=10,
        choices=[('P0', 'P0'), ('P1', 'P1'), ('P2', 'P2')],
        blank=True, default=''
    )
    test_type = models.CharField('测试类型', max_length=50, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = '测试用例'
        verbose_name_plural = '测试用例'

    def __str__(self):
        return f"[{self.project.name}] {self.name}"


class ExecutionRecord(models.Model):
    """执行记录"""
    STATUS_CHOICES = [
        ('pending', '等待中'),
        ('running', '运行中'),
        ('passed', '通过'),
        ('failed', '失败'),
        ('error', '异常'),
    ]

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name='executions', verbose_name='所属项目'
    )
    testcase = models.ForeignKey(
        TestCase, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='executions', verbose_name='关联用例'
    )
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    log = models.TextField('执行日志', blank=True, default='')
    screenshot_path = models.CharField('截图路径', max_length=500, blank=True, default='')
    duration = models.FloatField('耗时(秒)', null=True, blank=True)
    error_message = models.TextField('错误信息', blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '执行记录'
        verbose_name_plural = '执行记录'

    def __str__(self):
        tc_name = self.testcase.name if self.testcase else '批量执行'
        return f"[{self.status}] {tc_name} @ {self.created_at:%Y-%m-%d %H:%M}"


class SystemSetting(models.Model):
    """系统设置 — 以 key-value 形式存储"""
    key = models.CharField('设置键', max_length=100, unique=True)
    value = models.TextField('设置值', blank=True, default='')
    description = models.CharField('描述', max_length=200, blank=True, default='')
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['key']
        verbose_name = '系统设置'
        verbose_name_plural = '系统设置'

    def __str__(self):
        return f"{self.key} = {self.value[:40]}"

    # ── 默认设置 ──
    DEFAULTS = {
        'anthropic_api_key': {'value': '', 'description': 'Anthropic API Key（用于 AI 生成和分析）'},
        'anthropic_model': {'value': 'claude-sonnet-4-20250514', 'description': 'Anthropic AI 模型名称'},
        'max_workers': {'value': '3', 'description': '同时执行的最大测试用例数量'},
        'execution_timeout': {'value': '120', 'description': '单个用例最大执行时间（秒）'},
        'api_base_url': {'value': '/api', 'description': '后端 API 基础地址'},
        'repo_base_path': {'value': 'repos', 'description': 'Git 仓库克隆目标根目录'},
    }

    @classmethod
    def get(cls, key: str, default: str = '') -> str:
        """获取设置值，不存在则返回默认"""
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            info = cls.DEFAULTS.get(key)
            return info['value'] if info else default

    @classmethod
    def get_all_dict(cls) -> dict:
        """返回所有设置为 {key: value} 字典，缺失的用默认值补齐"""
        stored = {s.key: s.value for s in cls.objects.all()}
        result = {}
        for key, info in cls.DEFAULTS.items():
            result[key] = stored.get(key, info['value'])
        # 也返回不在 DEFAULTS 里的自定义设置
        for key, val in stored.items():
            if key not in result:
                result[key] = val
        return result


class AIConversation(models.Model):
    """AI 对话记录"""
    CONVERSATION_TYPES = [
        ('generate', '生成用例'),
        ('analyze', '分析结果'),
        ('chat', '自由对话'),
    ]

    conversation_type = models.CharField('对话类型', max_length=20, choices=CONVERSATION_TYPES)
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name='ai_conversations',
        verbose_name='关联项目', null=True, blank=True
    )
    user_message = models.TextField('用户消息')
    ai_response = models.TextField('AI 回复')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'AI 对话'
        verbose_name_plural = 'AI 对话'

    def __str__(self):
        return f"[{self.conversation_type}] {self.user_message[:50]}"
