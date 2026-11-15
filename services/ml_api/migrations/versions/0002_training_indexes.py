"""training domain: ensure indexes for legacy databases

Revision ID: 0002_training_indexes
Revises: 0001_training_domain
Create Date: 2026-11-15

0001 已为全新库建索引；历史库由 Django 迁移创建，可能缺少
``ix_training_job_created_at`` 等非外键索引。这里用 ``IF NOT EXISTS``
幂等补齐，避免旧库 stamp 后永远缺索引。
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0002_training_indexes'
down_revision: Union[str, None] = '0001_training_domain'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = (
    ('ix_training_base_model_organization_id', 'training_base_model', 'organization_id'),
    ('ix_training_base_model_created_by_id', 'training_base_model', 'created_by_id'),
    ('ix_training_job_base_model_id', 'training_job', 'base_model_id'),
    ('ix_training_job_organization_id', 'training_job', 'organization_id'),
    ('ix_training_job_created_by_id', 'training_job', 'created_by_id'),
    ('ix_training_job_project_id', 'training_job', 'project_id'),
    ('ix_training_job_created_at', 'training_job', 'created_at'),
)


def upgrade() -> None:
    for name, table, column in _INDEXES:
        op.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})')


def downgrade() -> None:
    for name, _table, _column in reversed(_INDEXES):
        op.execute(f'DROP INDEX IF EXISTS {name}')
