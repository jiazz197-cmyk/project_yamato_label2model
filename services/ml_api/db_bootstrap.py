"""训练域表结构启动引导。

- 全新库：执行 Alembic ``upgrade head`` 建表；
- 存量库（Django training app 已建表、但还没有 ``alembic_version``）：
  ``stamp head``，不重建表、不动数据；
- 已有版本表：正常 ``upgrade head``。

由 ml-api 启动脚本调用；ml-worker 依赖 ml-api healthy，不会并发迁移。
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from services.ml_api.db import database_url


def alembic_config() -> Config:
    """定位与包同目录的 alembic.ini。"""
    return Config(str(Path(__file__).resolve().parent / 'alembic.ini'))


def bootstrap() -> str:
    """确保训练域表结构与 Alembic 版本一致，返回本次动作。"""
    config = alembic_config()
    engine = create_engine(database_url())
    try:
        inspector = inspect(engine)
        has_version_table = inspector.has_table('alembic_version')
        has_legacy_tables = inspector.has_table('training_base_model')

        if not has_version_table and has_legacy_tables:
            command.stamp(config, 'head')
            return 'stamped existing training tables'

        command.upgrade(config, 'head')
        return 'upgraded'
    finally:
        engine.dispose()


def main() -> None:
    """命令行入口。"""
    print(f'[ml-api] training schema: {bootstrap()}')


if __name__ == '__main__':
    main()
