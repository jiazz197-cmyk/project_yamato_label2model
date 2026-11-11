"""BaseModel.save() 校验行为与收敛后的模型结构（@pytest.mark.django_db）。"""

import pytest
from django.core.exceptions import ValidationError

from training.models import BaseModel, TrainingJob


def _make_yolo_dir(tmp_path):
    directory = tmp_path / 'm'
    directory.mkdir()
    (directory / 'yolov8n.pt').write_bytes(b'dummy')
    return directory


def test_framework_choices_only_yolo():
    """framework 收敛后只剩 YOLO 一个 choice。"""
    assert [choice[0] for choice in BaseModel.Framework.choices] == ['YOLO']


def test_task_type_choices_yolo_only():
    """task_type 仅保留目标检测 / 实例分割。"""
    assert [choice[0] for choice in BaseModel.TaskType.choices] == [
        'ObjectDetection',
        'InstanceSegmentation',
    ]


def test_test_run_model_removed():
    """TestRun 模型已从 training app 删除。"""
    import training.models

    assert not hasattr(training.models, 'TestRun')


def test_celery_task_id_field_removed():
    """TrainingJob 不再保留 Celery 调度字段。"""
    field_names = {field.name for field in TrainingJob._meta.get_fields()}
    assert 'celery_task_id' not in field_names


@pytest.mark.django_db
def test_save_valid_active(tmp_path):
    directory = _make_yolo_dir(tmp_path)
    base_model = BaseModel(
        name='valid-active',
        task_type=BaseModel.TaskType.OBJECT_DETECTION,
        framework=BaseModel.Framework.YOLO,
        local_path=str(directory),
        is_active=True,
    )
    base_model.save()
    assert BaseModel.objects.filter(pk=base_model.pk).exists()


@pytest.mark.django_db
def test_save_invalid_active_no_pt(tmp_path):
    directory = tmp_path / 'empty'
    directory.mkdir()
    base_model = BaseModel(
        name='invalid-active-no-pt',
        task_type=BaseModel.TaskType.OBJECT_DETECTION,
        framework=BaseModel.Framework.YOLO,
        local_path=str(directory),
        is_active=True,
    )
    with pytest.raises(ValidationError):
        base_model.save()


@pytest.mark.django_db
def test_save_invalid_active_missing_dir(tmp_path):
    base_model = BaseModel(
        name='invalid-active-missing',
        task_type=BaseModel.TaskType.INSTANCE_SEGMENTATION,
        framework=BaseModel.Framework.YOLO,
        local_path=str(tmp_path / 'does-not-exist'),
        is_active=True,
    )
    with pytest.raises(ValidationError):
        base_model.save()


@pytest.mark.django_db
def test_save_invalid_inactive(tmp_path):
    base_model = BaseModel(
        name='invalid-inactive',
        task_type=BaseModel.TaskType.OBJECT_DETECTION,
        framework=BaseModel.Framework.YOLO,
        local_path=str(tmp_path / 'does-not-exist'),
        is_active=False,
    )
    base_model.save()
    assert BaseModel.objects.filter(pk=base_model.pk).exists()
