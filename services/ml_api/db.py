"""训练域的数据库连接（SQLAlchemy 同步引擎）。

FastAPI 侧车与 RQ worker 共用同一套 PostgreSQL：连接参数优先读 ``DATABASE_URL``，
否则复用 compose 注入的 ``POSTGRE_*`` 变量，保证与 Django 使用同一个库。
"""

import os
from collections.abc import Iterator
from urllib.parse import quote_plus

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def database_url() -> str:
    """返回 SQLAlchemy 连接串；显式 ``DATABASE_URL`` 优先。"""
    explicit = os.environ.get('DATABASE_URL')
    if explicit:
        return explicit

    user = quote_plus(os.environ.get('POSTGRE_USER', 'postgres'))
    password = quote_plus(os.environ.get('POSTGRE_PASSWORD', ''))
    host = os.environ.get('POSTGRE_HOST', 'postgres')
    port = os.environ.get('POSTGRE_PORT', '5432')
    name = quote_plus(os.environ.get('POSTGRE_NAME', 'postgres'))
    return f'postgresql+psycopg://{user}:{password}@{host}:{port}/{name}'


def create_db_engine(url: str | None = None) -> Engine:
    """创建引擎；``pool_pre_ping`` 避免数据库重启后拿到失效连接。"""
    return create_engine(url or database_url(), pool_pre_ping=True, future=True)


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个 Session，请求结束关闭。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
