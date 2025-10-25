"""Merge heads

Revision ID: 20250125_merge_heads
Revises: ffcb97e6f7c3, 20250125_knowledge_base
Create Date: 2025-01-25 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250125_merge_heads'
down_revision: Union[str, Sequence[str], None] = ('ffcb97e6f7c3', '20250125_knowledge_base')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge heads - no schema changes."""
    pass


def downgrade() -> None:
    """Downgrade - no schema changes."""
    pass
