"""Add usage tracking and payments

Revision ID: 20250125_usage_tracking_payments
Revises: 20250122_project_inactivity
Create Date: 2025-01-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20250125_usage_tracking_payments'
down_revision: Union[str, Sequence[str], None] = '20250122_project_inactivity'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add traffic and storage limits to subscription_plan
    op.add_column('subscription_plan', sa.Column('max_traffic_gb_per_month', sa.Integer(), nullable=False, server_default='5'))
    op.add_column('subscription_plan', sa.Column('max_storage_mb', sa.Integer(), nullable=False, server_default='100'))
    
    # Create project_usage table
    op.create_table('project_usage',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('project_id', sa.String(length=32), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('traffic_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('storage_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'year', 'month', name='uq_project_usage_period')
    )
    
    op.create_index('ix_project_usage_project_id', 'project_usage', ['project_id'])
    op.create_index('ix_project_usage_month', 'project_usage', ['month'])
    op.create_index('ix_project_usage_year', 'project_usage', ['year'])
    
    # Create payment enums
    op.execute("CREATE TYPE payment_method AS ENUM ('mobile_money', 'credit_card')")
    op.execute("CREATE TYPE payment_status AS ENUM ('pending', 'processing', 'completed', 'failed', 'cancelled')")
    
    # Create payment table
    op.create_table('payment',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('team_id', sa.String(length=32), nullable=False),
        sa.Column('external_payment_id', sa.String(length=255), nullable=True),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='EUR'),
        sa.Column('payment_method', postgresql.ENUM('mobile_money', 'credit_card', name='payment_method'), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'processing', 'completed', 'failed', 'cancelled', name='payment_status'), nullable=False, server_default='pending'),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['team_id'], ['team.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('external_payment_id')
    )
    
    op.create_index('ix_payment_team_id', 'payment', ['team_id'])
    op.create_index('ix_payment_external_payment_id', 'payment', ['external_payment_id'])
    op.create_index('ix_payment_created_at', 'payment', ['created_at'])
    
    # Update existing plans with traffic and storage limits
    op.execute("""
        UPDATE subscription_plan 
        SET max_traffic_gb_per_month = 5, max_storage_mb = 100
        WHERE name = 'free'
    """)
    
    op.execute("""
        UPDATE subscription_plan 
        SET max_traffic_gb_per_month = 10, max_storage_mb = 10240
        WHERE name = 'pay_as_you_go'
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop payment table and enums
    op.drop_index('ix_payment_created_at', table_name='payment')
    op.drop_index('ix_payment_external_payment_id', table_name='payment')
    op.drop_index('ix_payment_team_id', table_name='payment')
    op.drop_table('payment')
    op.execute("DROP TYPE IF EXISTS payment_status")
    op.execute("DROP TYPE IF EXISTS payment_method")
    
    # Drop project_usage table
    op.drop_index('ix_project_usage_year', table_name='project_usage')
    op.drop_index('ix_project_usage_month', table_name='project_usage')
    op.drop_index('ix_project_usage_project_id', table_name='project_usage')
    op.drop_table('project_usage')
    
    # Remove traffic and storage columns from subscription_plan
    op.drop_column('subscription_plan', 'max_storage_mb')
    op.drop_column('subscription_plan', 'max_traffic_gb_per_month')
