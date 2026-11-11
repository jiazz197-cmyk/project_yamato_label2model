from django.conf import settings
from django.db import models

from training.utils import validate_local_model_path


class BaseModel(models.Model):
    """本地预置 YOLO 基模（事先下载好，不联网）。"""

    class Framework(models.TextChoices):
        YOLO = 'YOLO', 'Ultralytics YOLO'

    class TaskType(models.TextChoices):
        """YOLO 训练支持的任务类型（仅目标检测与实例分割）。"""

        OBJECT_DETECTION = 'ObjectDetection', 'ObjectDetection'
        INSTANCE_SEGMENTATION = 'InstanceSegmentation', 'InstanceSegmentation'

    name = models.CharField(max_length=255, unique=True)
    task_type = models.CharField(
        max_length=255,
        choices=TaskType.choices,
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
        """校验 local_path 存在且含 YOLO 权重（委托 utils.validate_local_model_path）。"""
        validate_local_model_path(self.local_path)

    def save(self, *args, **kwargs):
        """保存前校验：仅 is_active=True 时校验本地路径（is_active=False 可先存占位再补文件）。"""
        if self.is_active:
            self.validate_local_path()
        super().save(*args, **kwargs)

    def has_permission(self, user):
        """服务器预置（organization 为空）基模全员可见；其余仅同组织成员。"""
        return self.organization_id is None or user.active_organization_id == self.organization_id

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

    def has_permission(self, user):
        """仅同组织成员可访问。"""
        return user.active_organization_id == self.organization_id

    def __str__(self):
        return f'TrainingJob #{self.id} ({self.base_model.name} -> {self.project})'

    class Meta:
        db_table = 'training_job'
        ordering = ['-created_at']
