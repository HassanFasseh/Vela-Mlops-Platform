"""add dataset_source to model_cards

Revision ID: c153b1c5ca2f
Revises: e0a6b2e48388
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c153b1c5ca2f'
down_revision: Union[str, Sequence[str], None] = 'e0a6b2e48388'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('model_cards', sa.Column('dataset_source', sa.Text(), nullable=False, server_default=''))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('model_cards', 'dataset_source')
