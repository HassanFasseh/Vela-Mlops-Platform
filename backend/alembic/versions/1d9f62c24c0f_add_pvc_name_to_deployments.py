"""add pvc_name to deployments

Revision ID: 1d9f62c24c0f
Revises: d093d7212ede
Create Date: 2026-08-24 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1d9f62c24c0f'
down_revision: Union[str, Sequence[str], None] = 'd093d7212ede'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('deployments', sa.Column('pvc_name', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('deployments', 'pvc_name')
