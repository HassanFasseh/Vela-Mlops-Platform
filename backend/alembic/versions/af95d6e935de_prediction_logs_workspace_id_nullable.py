"""prediction_logs.workspace_id nullable

Revision ID: af95d6e935de
Revises: ff1858325ddf
Create Date: 2026-09-15 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'af95d6e935de'
down_revision: Union[str, Sequence[str], None] = 'ff1858325ddf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('prediction_logs', 'workspace_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('prediction_logs', 'workspace_id', existing_type=sa.Integer(), nullable=False)
