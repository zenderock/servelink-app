"""Add knowledge base

Revision ID: 20250125_knowledge_base
Revises: 20250125_resources_support
Create Date: 2025-01-25 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20250125_knowledge_base'
down_revision: Union[str, Sequence[str], None] = '20250125_resources_support'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create kb_category enum (if it doesn't exist)
    try:
        op.execute("CREATE TYPE kb_category AS ENUM ('getting_started', 'deployment', 'billing', 'troubleshooting', 'api', 'other')")
    except Exception:
        pass  # Type already exists
    
    # Create knowledge_base_article table
    op.create_table('knowledge_base_article',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=255), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('excerpt', sa.String(length=500), nullable=True),
        sa.Column('category', postgresql.ENUM('getting_started', 'deployment', 'billing', 'troubleshooting', 'api', 'other', name='kb_category', create_type=False), nullable=False, server_default='other'),
        sa.Column('tags', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('view_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('helpful_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('not_helpful_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_published', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('author_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['author_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug')
    )
    
    op.create_index('ix_knowledge_base_article_title', 'knowledge_base_article', ['title'])
    op.create_index('ix_knowledge_base_article_slug', 'knowledge_base_article', ['slug'])
    op.create_index('ix_knowledge_base_article_created_at', 'knowledge_base_article', ['created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_knowledge_base_article_created_at', table_name='knowledge_base_article')
    op.drop_index('ix_knowledge_base_article_slug', table_name='knowledge_base_article')
    op.drop_index('ix_knowledge_base_article_title', table_name='knowledge_base_article')
    op.drop_table('knowledge_base_article')
    op.execute("DROP TYPE IF EXISTS kb_category")
