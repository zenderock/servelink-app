"""Add project inactivity tracking

Revision ID: 20250122_project_inactivity
Revises: 20250121_add_subscription_plans
Create Date: 2025-01-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250122_project_inactivity'
down_revision: Union[str, Sequence[str], None] = '20250121_add_subscription_plans'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new status values to project_status enum
    op.execute("ALTER TYPE project_status ADD VALUE 'inactive'")
    op.execute("ALTER TYPE project_status ADD VALUE 'permanently_disabled'")
    
    # Add new columns to project table
    op.add_column('project', sa.Column('last_traffic_at', sa.DateTime(), nullable=True))
    op.add_column('project', sa.Column('deactivated_at', sa.DateTime(), nullable=True))
    op.add_column('project', sa.Column('reactivation_count', sa.Integer(), nullable=False, server_default='0'))
    
    # Create index on last_traffic_at for performance
    op.create_index('ix_project_last_traffic_at', 'project', ['last_traffic_at'])
    
    # Initialize last_traffic_at for existing projects with their updated_at
    op.execute("UPDATE project SET last_traffic_at = updated_at WHERE last_traffic_at IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    # Drop the index
    op.drop_index('ix_project_last_traffic_at', table_name='project')
    
    # Drop the new columns
    op.drop_column('project', 'reactivation_count')
    op.drop_column('project', 'deactivated_at')
    op.drop_column('project', 'last_traffic_at')
    
    # Note: We cannot easily remove enum values in PostgreSQL
    # The enum values 'inactive' and 'permanently_disabled' will remain
    # but won't be used by the application
