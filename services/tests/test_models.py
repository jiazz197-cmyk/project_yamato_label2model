"""训练域 ORM 结构与权限单测（不连接数据库）。"""

from services.ml_api import models as training_models
from services.ml_api.models import TRAIN_SUBSETS, BaseModel, TrainingJob


def test_table_names_preserved():
    """表名沿用 Django 迁移创建的表，存量数据无需搬迁。"""
    assert BaseModel.__tablename__ == 'training_base_model'
    assert TrainingJob.__tablename__ == 'training_job'


def test_training_job_columns_match_legacy_schema():
    """列名与 Django 版本一致，且不再保留 Celery 调度字段。"""
    columns = {column.name for column in TrainingJob.__table__.columns}
    assert columns == {
        'id',
        'base_model_id',
        'project_id',
        'train_subset',
        'hyperparams',
        'status',
        'metrics',
        'artifact_path',
        'model_version',
        'error_message',
        'created_by_id',
        'organization_id',
        'created_at',
        'started_at',
        'completed_at',
    }
    assert 'celery_task_id' not in columns


def test_indexes_match_migration():
    """0001 已建索引必须在 ORM metadata 中声明，避免 autogenerate 生成 drop_index。"""
    expected = {
        'ix_training_base_model_organization_id',
        'ix_training_base_model_created_by_id',
        'ix_training_job_base_model_id',
        'ix_training_job_organization_id',
        'ix_training_job_created_by_id',
        'ix_training_job_project_id',
        'ix_training_job_created_at',
    }
    actual = {
        index.name
        for table in (BaseModel.__table__, TrainingJob.__table__)
        for index in table.indexes
    }
    assert expected == actual


def test_test_run_model_removed():
    """TestRun 模型已删除（YOLO-only 收敛）。"""
    assert not hasattr(training_models, 'TestRun')


def test_train_subset_choices():
    """train_subset 仅保留三种取值。"""
    assert TRAIN_SUBSETS == ('All', 'HasGT', 'Sample')


def test_base_model_permission():
    """服务器预置基模全员可见；组织基模仅同组织可见。"""
    global_model = BaseModel(organization_id=None)
    assert global_model.has_permission(None)
    assert global_model.has_permission(7)

    org_model = BaseModel(organization_id=2)
    assert org_model.has_permission(2)
    assert not org_model.has_permission(3)
    assert not org_model.has_permission(None)


def test_training_job_permission():
    """训练任务仅同组织成员可访问。"""
    job = TrainingJob(organization_id=2)
    assert job.has_permission(2)
    assert not job.has_permission(3)
    assert not job.has_permission(None)
