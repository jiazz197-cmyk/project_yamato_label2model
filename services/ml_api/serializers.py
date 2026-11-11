"""训练域 JSON 序列化：字段与 DRF 原有输出保持一致（含时间格式）。"""

import datetime as dt
from typing import Any

from services.ml_api.models import BaseModel, TrainingJob


def isoformat(value: dt.datetime | None) -> str | None:
    """按 DRF DateTimeField 的格式输出 UTC 时间（``...Z``）。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    else:
        value = value.astimezone(dt.timezone.utc)
    return value.isoformat().replace('+00:00', 'Z')


def base_model_to_dict(model: BaseModel) -> dict[str, Any]:
    """序列化 BaseModel。"""
    return {
        'id': model.id,
        'name': model.name,
        'task_type': model.task_type,
        'framework': model.framework,
        'local_path': model.local_path,
        'description': model.description,
        'default_config': model.default_config or {},
        'is_active': model.is_active,
        'organization': model.organization_id,
        'created_at': isoformat(model.created_at),
        'updated_at': isoformat(model.updated_at),
    }


def training_job_to_dict(job: TrainingJob) -> dict[str, Any]:
    """序列化 TrainingJob。"""
    return {
        'id': job.id,
        'base_model': job.base_model_id,
        'project': job.project_id,
        'train_subset': job.train_subset,
        'hyperparams': job.hyperparams or {},
        'status': job.status,
        'metrics': job.metrics or {},
        'artifact_path': job.artifact_path,
        'model_version': job.model_version,
        'error_message': job.error_message,
        'created_at': isoformat(job.created_at),
        'started_at': isoformat(job.started_at),
        'completed_at': isoformat(job.completed_at),
    }
