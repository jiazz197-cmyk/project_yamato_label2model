"""Training REST API 序列化器（BaseModel / TrainingJob / TestRun）。

- BaseModelSerializer：只读（列表/详情均不提供写入端点）。
- TrainingJobSerializer：写字段仅 base_model/project/train_subset/hyperparams。
- TestRunSerializer：project 必填；base_model_id 与 training_job_id 二选一（write_only）。
"""

from projects.models import Project
from rest_framework import serializers

from training.models import BaseModel, TestRun, TrainingJob


class BaseModelSerializer(serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = BaseModel
        fields = [
            'id',
            'name',
            'task_type',
            'framework',
            'local_path',
            'description',
            'default_config',
            'is_active',
            'organization',
            'created_at',
            'updated_at',
        ]
        # organization 显式 read_only；其余字段均为只读端点，此处兜底声明。
        read_only_fields = [
            'id',
            'name',
            'task_type',
            'framework',
            'local_path',
            'description',
            'default_config',
            'is_active',
            'created_at',
            'updated_at',
        ]


class TrainingJobSerializer(serializers.ModelSerializer):
    base_model = serializers.PrimaryKeyRelatedField(queryset=BaseModel.objects.all())
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())

    class Meta:
        model = TrainingJob
        fields = [
            'id',
            'base_model',
            'project',
            'train_subset',
            'hyperparams',
            'status',
            'metrics',
            'artifact_path',
            'model_version',
            'celery_task_id',
            'error_message',
            'created_at',
            'started_at',
            'completed_at',
        ]
        read_only_fields = [
            'id',
            'status',
            'metrics',
            'artifact_path',
            'model_version',
            'celery_task_id',
            'error_message',
            'created_at',
            'started_at',
            'completed_at',
        ]


class TestRunSerializer(serializers.ModelSerializer):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    base_model_id = serializers.PrimaryKeyRelatedField(
        source='base_model', queryset=BaseModel.objects.all(), required=False, write_only=True
    )
    training_job_id = serializers.PrimaryKeyRelatedField(
        source='training_job', queryset=TrainingJob.objects.all(), required=False, write_only=True
    )

    class Meta:
        model = TestRun
        fields = [
            'id',
            'project',
            'base_model_id',
            'training_job_id',
            'test_subset',
            'status',
            'metrics',
            'celery_task_id',
            'error_message',
            'created_at',
            'started_at',
            'completed_at',
        ]
        read_only_fields = [
            'id',
            'status',
            'metrics',
            'celery_task_id',
            'error_message',
            'created_at',
            'started_at',
            'completed_at',
        ]

    def validate(self, attrs):
        """base_model_id 与 training_job_id 必须二选一。"""
        base_model = attrs.get('base_model')
        training_job = attrs.get('training_job')
        if (base_model is None) == (training_job is None):
            raise serializers.ValidationError('base_model_id 和 training_job_id 必须二选一')
        return attrs
