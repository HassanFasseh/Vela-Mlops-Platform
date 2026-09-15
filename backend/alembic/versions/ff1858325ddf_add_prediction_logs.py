"""add prediction logs

Revision ID: ff1858325ddf
Revises: a6334f94e8c9
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff1858325ddf'
down_revision: Union[str, Sequence[str], None] = 'a6334f94e8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('prediction_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('deployment_id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('api_key_id', sa.Integer(), nullable=True),
    sa.Column('input', sa.Text(), nullable=False),
    sa.Column('output', sa.Text(), nullable=False),
    sa.Column('latency_ms', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['deployment_id'], ['deployments.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['api_key_id'], ['workspace_api_keys.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('prediction_logs')
