"""Training REST API 序列化器（BaseModel / TrainingJob）。

- BaseModelSerializer：只读（列表/详情均不提供写入端点）。
- TrainingJobSerializer：写字段仅 base_model/project/train_subset/hyperparams。
"""

from projects.models import Project
from rest_framework import serializers

from training.models import BaseModel, TrainingJob


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
            'error_message',
            'created_at',
            'started_at',
            'completed_at',
        ]
