"""training domain: training_base_model / training_job

沿用 Django training app 的表名与列名，存量库通过 ``db_bootstrap`` stamp 到本版本。

Revision ID: 0001_training_domain
Revises:
Create Date: 2026-11-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0001_training_domain'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'training_base_model',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('task_type', sa.String(length=255), nullable=False),
        sa.Column('framework', sa.String(length=16), nullable=False),
        sa.Column('local_path', sa.String(length=1024), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('default_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='training_base_model_name_key'),
    )
    op.create_index('ix_training_base_model_organization_id', 'training_base_model', ['organization_id'])
    op.create_index('ix_training_base_model_created_by_id', 'training_base_model', ['created_by_id'])

    op.create_table(
        'training_job',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('base_model_id', sa.BigInteger(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('train_subset', sa.String(length=16), nullable=False),
        sa.Column('hyperparams', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('artifact_path', sa.String(length=1024), nullable=True),
        sa.Column('model_version', sa.String(length=255), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['base_model_id'], ['training_base_model.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_training_job_base_model_id', 'training_job', ['base_model_id'])
    op.create_index('ix_training_job_organization_id', 'training_job', ['organization_id'])
    op.create_index('ix_training_job_created_by_id', 'training_job', ['created_by_id'])
    op.create_index('ix_training_job_project_id', 'training_job', ['project_id'])
    op.create_index('ix_training_job_created_at', 'training_job', ['created_at'])


def downgrade() -> None:
    op.drop_table('training_job')
    op.drop_table('training_base_model')
