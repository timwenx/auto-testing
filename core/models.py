from django.db import models
from django.conf import settings


class Project(models.Model):
    """测试项目"""
    name = models.CharField('项目名称', max_length=200)
    description = models.TextField('项目描述', blank=True, default='')
    base_url = models.CharField('测试目标 URL', max_length=500, blank=True, default='')
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
