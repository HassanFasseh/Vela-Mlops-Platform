"""add is_active to deployments

Revision ID: e0a6b2e48388
Revises: 1d9f62c24c0f
Create Date: 2026-08-24 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0a6b2e48388'
down_revision: Union[str, Sequence[str], None] = '1d9f62c24c0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('deployments', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('deployments', 'is_active')
