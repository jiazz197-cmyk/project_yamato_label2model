from django.conf import settings
from django.db import models

from ml_models.models import SkillNames
from training.utils import validate_local_model_path


class BaseModel(models.Model):
    """本地预置基模（事先下载好，不联网）"""

    class Framework(models.TextChoices):
        HUGGINGFACE = 'HF', 'HuggingFace Transformers'
        SKLEARN = 'SKLEARN', 'scikit-learn'

    name = models.CharField(max_length=255, unique=True)
    task_type = models.CharField(
        max_length=255,
        choices=SkillNames.choices,
    )
    framework = models.CharField(max_length=16, choices=Framework.choices)
    local_path = models.CharField(
        max_length=1024,
        help_text='本地模型目录绝对路径（事先下载，不联网）',
    )
    description = models.TextField(blank=True, null=True)
    default_config = models.JSONField(default=dict, help_text='默认超参')
    is_active = models.BooleanField(default=True)

    # 审计
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
    )
    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.CASCADE, null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def validate_local_path(self):
        """校验 local_path 存在且含框架期望文件（委托 utils.validate_local_model_path）。"""
        validate_local_model_path(self.local_path, self.framework)

    def save(self, *args, **kwargs):
        """保存前校验：仅 is_active=True 时校验本地路径（is_active=False 可先存占位再补文件）。"""
        if self.is_active:
            self.validate_local_path()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} ({self.framework})'

    class Meta:
        db_table = 'training_base_model'


class TrainingJob(models.Model):
    """一次训练任务"""

    class TrainSubset(models.TextChoices):
        ALL = 'All', 'All tasks'
        HAS_GT = 'HasGT', 'Tasks with ground truth annotations'
        SAMPLE = 'Sample', 'Random sample of annotated tasks'

    class Status(models.TextChoices):
        PENDING = 'Pending'
        RUNNING = 'Running'
        COMPLETED = 'Completed'
        FAILED = 'Failed'
        CANCELED = 'Canceled'

    base_model = models.ForeignKey(BaseModel, on_delete=models.CASCADE, related_name='training_jobs')
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='training_jobs')
    train_subset = models.CharField(max_length=16, choices=TrainSubset.choices, default=TrainSubset.HAS_GT)
    hyperparams = models.JSONField(default=dict, help_text='用户覆盖的超参，merge 到 base_model.default_config')

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    metrics = models.JSONField(default=dict, help_text='训练指标：{epoch, loss, acc, ...}')
    artifact_path = models.CharField(max_length=1024, blank=True, null=True, help_text='训练产物本地目录绝对路径')
    model_version = models.CharField(max_length=255, blank=True, help_text='写入 Prediction.model_version，格式 f"{base_model.name}__{job.id}"')
    celery_task_id = models.CharField(max_length=255, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)

    # 审计
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
    )
    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.CASCADE, null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'TrainingJob #{self.id} ({self.base_model.name} -> {self.project})'

    class Meta:
        db_table = 'training_job'
        ordering = ['-created_at']


class TestRun(models.Model):
    """一次测试任务（零样本 or 训练产物）"""

    class TestSubset(models.TextChoices):
        ALL = 'All', 'All tasks'
        HAS_GT = 'HasGT', 'Tasks with ground truth annotations'
        SAMPLE = 'Sample', 'Random sample of annotated tasks'

    class Status(models.TextChoices):
        PENDING = 'Pending'
        RUNNING = 'Running'
        COMPLETED = 'Completed'
        FAILED = 'Failed'
        CANCELED = 'Canceled'

    # 二选一：training_job（训练产物测试）或 base_model（零样本测试）
    training_job = models.ForeignKey(
        TrainingJob, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='test_runs',
        help_text='训练产物测试（与 base_model 二选一）',
    )
    base_model = models.ForeignKey(
        BaseModel, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='test_runs',
        help_text='零样本测试（与 training_job 二选一）',
    )
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='test_runs')
    test_subset = models.CharField(max_length=16, choices=TestSubset.choices, default=TestSubset.HAS_GT)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    metrics = models.JSONField(default=dict, help_text='测试指标：{accuracy, f1, precision, recall, confusion_matrix, total, correct, skipped}')
    celery_task_id = models.CharField(max_length=255, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)

    # 审计
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
    )
    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.CASCADE, null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        """校验 training_job 与 base_model 二选一"""
        from django.core.exceptions import ValidationError
        if self.training_job and self.base_model:
            raise ValidationError('training_job 和 base_model 不能同时设置（二选一）')
        if not self.training_job and not self.base_model:
            raise ValidationError('training_job 和 base_model 必须设置其一（二选一）')

    def __str__(self):
        target = self.training_job or self.base_model
        return f'TestRun #{self.id} ({target} -> {self.project})'

    class Meta:
        db_table = 'training_test_run'
        ordering = ['-created_at']