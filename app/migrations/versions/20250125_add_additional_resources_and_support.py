"""Add additional resources and support system

Revision ID: 20250125_resources_support
Revises: 20250125_usage_tracking_payments
Create Date: 2025-01-25 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20250125_resources_support'
down_revision: Union[str, Sequence[str], None] = '20250125_usage_tracking_payments'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create enums (if they don't exist)
    try:
        op.execute("CREATE TYPE resource_type AS ENUM ('ram', 'cpu', 'traffic', 'storage')")
    except Exception:
        pass
    
    try:
        op.execute("CREATE TYPE resource_status AS ENUM ('active', 'expired', 'cancelled')")
    except Exception:
        pass
    
    try:
        op.execute("CREATE TYPE ticket_priority AS ENUM ('low', 'normal', 'high', 'urgent')")
    except Exception:
        pass
    
    try:
        op.execute("CREATE TYPE ticket_status AS ENUM ('open', 'in_progress', 'waiting', 'resolved', 'closed')")
    except Exception:
        pass
    
    try:
        op.execute("CREATE TYPE ticket_category AS ENUM ('technical', 'billing', 'feature_request', 'bug_report', 'other')")
    except Exception:
        pass
    
    try:
        op.execute("CREATE TYPE message_author_type AS ENUM ('user', 'support', 'system')")
    except Exception:
        pass
    
    # Create additional_resource table
    op.create_table('additional_resource',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('team_id', sa.String(length=32), nullable=False),
        sa.Column('resource_type', postgresql.ENUM('ram', 'cpu', 'traffic', 'storage', name='resource_type', create_type=False), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='EUR'),
        sa.Column('payment_id', sa.String(length=32), nullable=True),
        sa.Column('status', postgresql.ENUM('active', 'expired', 'cancelled', name='resource_status', create_type=False), nullable=False, server_default='active'),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['payment_id'], ['payment.id'], ),
        sa.ForeignKeyConstraint(['team_id'], ['team.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('ix_additional_resource_team_id', 'additional_resource', ['team_id'])
    
    # Create support_ticket table
    op.create_table('support_ticket',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('team_id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('priority', postgresql.ENUM('low', 'normal', 'high', 'urgent', name='ticket_priority', create_type=False), nullable=False, server_default='normal'),
        sa.Column('status', postgresql.ENUM('open', 'in_progress', 'waiting', 'resolved', 'closed', name='ticket_status', create_type=False), nullable=False, server_default='open'),
        sa.Column('category', postgresql.ENUM('technical', 'billing', 'feature_request', 'bug_report', 'other', name='ticket_category', create_type=False), nullable=False, server_default='technical'),
        sa.Column('assigned_to', sa.String(length=100), nullable=True),
        sa.Column('ticket_metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['team_id'], ['team.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('ix_support_ticket_team_id', 'support_ticket', ['team_id'])
    op.create_index('ix_support_ticket_user_id', 'support_ticket', ['user_id'])
    op.create_index('ix_support_ticket_created_at', 'support_ticket', ['created_at'])
    
    # Create support_message table
    op.create_table('support_message',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('ticket_id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('author_type', postgresql.ENUM('user', 'support', 'system', name='message_author_type', create_type=False), nullable=False, server_default='user'),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('is_internal', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['support_ticket.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('ix_support_message_ticket_id', 'support_message', ['ticket_id'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop tables
    op.drop_index('ix_support_message_ticket_id', table_name='support_message')
    op.drop_table('support_message')
    
    op.drop_index('ix_support_ticket_created_at', table_name='support_ticket')
    op.drop_index('ix_support_ticket_user_id', table_name='support_ticket')
    op.drop_index('ix_support_ticket_team_id', table_name='support_ticket')
    op.drop_table('support_ticket')
    
    op.drop_index('ix_additional_resource_team_id', table_name='additional_resource')
    op.drop_table('additional_resource')
    
    # Drop enums
    op.execute("DROP TYPE IF EXISTS message_author_type")
    op.execute("DROP TYPE IF EXISTS ticket_category")
    op.execute("DROP TYPE IF EXISTS ticket_status")
    op.execute("DROP TYPE IF EXISTS ticket_priority")
    op.execute("DROP TYPE IF EXISTS resource_status")
    op.execute("DROP TYPE IF EXISTS resource_type")
