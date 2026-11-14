"""训练域 ORM 模型（SQLAlchemy）。

表名与列名沿用 Django training app 的 ``training_base_model`` / ``training_job``，
因此存量库无需数据搬迁；表结构由 ``services/ml_api/migrations``（Alembic）维护。

Django 侧只保留项目、组织与用户；``project_id`` / ``organization_id`` /
``created_by_id`` 是跨域引用，这里按整数保存，不做数据库外键（由 API 层校验）。
"""

import datetime as dt
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# SQLite 只有 INTEGER PRIMARY KEY 才能自增；生产库仍是 BIGSERIAL/BIGINT。
_BIGINT = sa.BigInteger().with_variant(sa.Integer, 'sqlite')
# Django JSONField 在 PostgreSQL 上是 jsonb，测试用 SQLite 时退化为 JSON。
_JSON = sa.JSON().with_variant(postgresql.JSONB, 'postgresql')
_TIMESTAMP = sa.DateTime(timezone=True)


class Base(DeclarativeBase):
    """训练域 ORM 基类。"""


def utcnow() -> dt.datetime:
    """带时区的当前时间（Django USE_TZ=True 的等价行为）。"""
    return dt.datetime.now(dt.timezone.utc)


class BaseModel(Base):
    """本地预置 YOLO 基模（事先下载好，不联网）。"""

    __tablename__ = 'training_base_model'
    __table_args__ = (
        sa.UniqueConstraint('name', name='training_base_model_name_key'),
    )

    id: Mapped[int] = mapped_column(_BIGINT, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    task_type: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    framework: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    local_path: Mapped[str] = mapped_column(sa.String(1024), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    default_config: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)

    # Django 的 User / Organization 主键是 integer，跨域引用保持相同类型。
    created_by_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    organization_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(_TIMESTAMP, default=utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(_TIMESTAMP, default=utcnow, onupdate=utcnow, nullable=False)

    training_jobs: Mapped[list['TrainingJob']] = relationship(back_populates='base_model')

    def has_permission(self, organization_id: int | None) -> bool:
        """服务器预置（organization_id 为空）基模全员可见；其余仅同组织成员。"""
        return self.organization_id is None or organization_id == self.organization_id


class TrainingJob(Base):
    """一次训练任务。"""

    __tablename__ = 'training_job'

    id: Mapped[int] = mapped_column(_BIGINT, primary_key=True, autoincrement=True)
    base_model_id: Mapped[int] = mapped_column(
        _BIGINT,
        sa.ForeignKey('training_base_model.id', ondelete='CASCADE'),
        nullable=False,
    )
    project_id: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    train_subset: Mapped[str] = mapped_column(sa.String(16), default='HasGT', nullable=False)
    hyperparams: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict, nullable=False)

    status: Mapped[str] = mapped_column(sa.String(16), default='Pending', nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict, nullable=False)
    artifact_path: Mapped[str | None] = mapped_column(sa.String(1024), nullable=True)
    model_version: Mapped[str] = mapped_column(sa.String(255), default='', nullable=False)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    organization_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(_TIMESTAMP, default=utcnow, nullable=False)
    started_at: Mapped[dt.datetime | None] = mapped_column(_TIMESTAMP, nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(_TIMESTAMP, nullable=True)

    base_model: Mapped[BaseModel] = relationship(back_populates='training_jobs', lazy='joined')

    def has_permission(self, organization_id: int | None) -> bool:
        """仅同组织成员可访问；null-org 历史任务保持旧行为的 None == None。"""
        return organization_id == self.organization_id


class ProjectRef(Base):
    """只读映射 Django ``project`` 表，用于校验项目所属组织。

    只声明本域需要的两列；不写数据、不参与 Alembic 迁移。
    """

    __tablename__ = 'project'
    __table_args__ = {'extend_existing': True}

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    # Django Project 是软删除：默认 manager 会过滤 deleted_at IS NOT NULL。
    # 训练域只读映射该表，因此校验项目可见性时必须自己过滤。
    deleted_at: Mapped[dt.datetime | None] = mapped_column(_TIMESTAMP, nullable=True)


# 枚举值集中定义，序列化/校验共用。
TRAIN_SUBSETS = ('All', 'HasGT', 'Sample')
JOB_STATUSES = ('Pending', 'Running', 'Completed', 'Failed', 'Canceled')
