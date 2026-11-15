"""训练域表结构启动引导。

- 全新库：执行 Alembic ``upgrade head`` 建表；
- 存量库（Django training app 已建表、但还没有 ``alembic_version``）：
  先校验表/列完整，``stamp 0001`` 后再 ``upgrade head``，让 0002 补索引；
- 已有版本表：正常 ``upgrade head``。

由 ml-api 启动脚本调用；ml-worker 依赖 ml-api healthy，不会并发迁移。
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from services.ml_api.db import database_url

_BASE_MODEL_COLUMNS = {
    'id',
    'name',
    'task_type',
    'framework',
    'local_path',
    'description',
    'default_config',
    'is_active',
    'created_by_id',
    'organization_id',
    'created_at',
    'updated_at',
}

_TRAINING_JOB_COLUMNS = {
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


def alembic_config() -> Config:
    """定位与包同目录的 alembic.ini。"""
    return Config(str(Path(__file__).resolve().parent / 'alembic.ini'))


def _validate_legacy_schema(inspector) -> None:
    """校验 Django 迁移创建的 training 表是否与当前 ORM 对齐。

    只做启动前的最小校验，避免在缺表/缺列时直接 stamp head，导致后续接口
    运行期才 500 且无法通过 Alembic 修复。
    """
    tables = set(inspector.get_table_names())
    has_base_model = 'training_base_model' in tables
    has_training_job = 'training_job' in tables

    if has_base_model != has_training_job:
        missing = 'training_job' if has_base_model else 'training_base_model'
        raise RuntimeError(
            f'训练域 legacy 表不完整：缺少 {missing}；请先执行原 Django training 迁移，'
            '或手工建表后再启动 ml-api。'
        )

    expected = {
        'training_base_model': _BASE_MODEL_COLUMNS,
        'training_job': _TRAINING_JOB_COLUMNS,
    }
    for table, columns in expected.items():
        actual = {column['name'] for column in inspector.get_columns(table)}
        missing_columns = sorted(columns - actual)
        if missing_columns:
            raise RuntimeError(
                f'训练域 legacy 表 {table} 缺少列 {missing_columns}；'
                '请先补齐原 Django training 迁移，不能直接 stamp。'
            )


def bootstrap() -> str:
    """确保训练域表结构与 Alembic 版本一致，返回本次动作。"""
    config = alembic_config()
    engine = create_engine(database_url())
    try:
        inspector = inspect(engine)
        has_version_table = inspector.has_table('alembic_version')
        has_legacy_tables = inspector.has_table('training_base_model') or inspector.has_table(
            'training_job'
        )

        if not has_version_table and has_legacy_tables:
            _validate_legacy_schema(inspector)
            command.stamp(config, '0001_training_domain')
            command.upgrade(config, 'head')
            return 'stamped legacy tables and upgraded indexes'

        command.upgrade(config, 'head')
        return 'upgraded'
    finally:
        engine.dispose()


def main() -> None:
    """命令行入口。"""
    print(f'[ml-api] training schema: {bootstrap()}')


if __name__ == '__main__':
    main()
