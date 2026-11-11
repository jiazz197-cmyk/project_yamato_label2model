"""Alembic 迁移环境：复用 ``services.ml_api.db`` 的连接参数。"""

from sqlalchemy import create_engine, pool

from alembic import context
from services.ml_api.db import database_url
from services.ml_api.models import Base

config = context.config
target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to):
    """autogenerate 时忽略只读的 Django ``project`` 映射表。"""
    if type_ == 'table' and name == 'project':
        return False
    return True


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连接数据库。"""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库并执行迁移。"""
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
