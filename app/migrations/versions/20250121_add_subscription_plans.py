"""Add subscription plans and team subscriptions

Revision ID: 20250121_add_subscription_plans
Revises: 454328a03102
Create Date: 2025-01-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250121_add_subscription_plans'
down_revision: Union[str, Sequence[str], None] = '454328a03102'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create subscription_plan table
    op.create_table('subscription_plan',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=False),
        sa.Column('max_teams', sa.Integer(), nullable=False),
        sa.Column('max_team_members', sa.Integer(), nullable=False),
        sa.Column('max_projects', sa.Integer(), nullable=False),
        sa.Column('custom_domains_allowed', sa.Boolean(), nullable=False, default=False),
        sa.Column('price_per_month', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    
    # Create team_subscription table
    op.create_table('team_subscription',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('team_id', sa.String(length=32), nullable=False),
        sa.Column('plan_id', sa.String(length=32), nullable=False),
        sa.Column('status', sa.Enum('active', 'cancelled', 'expired', name='subscription_status'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['subscription_plan.id'], ),
        sa.ForeignKeyConstraint(['team_id'], ['team.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('team_id')
    )
    
    # Insert default plans
    op.execute("""
        INSERT INTO subscription_plan (id, name, display_name, max_teams, max_team_members, max_projects, custom_domains_allowed, price_per_month, is_active, created_at, updated_at)
        VALUES 
        ('free_plan_id', 'free', 'Free', 1, 1, 2, false, null, true, NOW(), NOW()),
        ('pay_as_you_go_plan_id', 'pay_as_you_go', 'Pay as You Go', -1, -1, -1, true, 0.0, true, NOW(), NOW())
    """)
    
    # Assign free plan to all existing teams
    op.execute("""
        INSERT INTO team_subscription (id, team_id, plan_id, status, created_at, updated_at)
        SELECT 
            'sub_' || substring(team.id::text, 1, 28),
            team.id,
            'free_plan_id',
            'active',
            NOW(),
            NOW()
        FROM team
        WHERE team.status = 'active'
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('team_subscription')
    op.drop_table('subscription_plan')
    op.execute("DROP TYPE IF EXISTS subscription_status")
