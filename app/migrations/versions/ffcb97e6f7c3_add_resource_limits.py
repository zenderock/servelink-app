"""add_resource_limits

Revision ID: ffcb97e6f7c3
Revises: 20250122_project_inactivity
Create Date: 2025-10-23 12:01:32.035368

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ffcb97e6f7c3'
down_revision: Union[str, Sequence[str], None] = '20250122_project_inactivity'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add resource columns to subscription_plan table
    op.add_column('subscription_plan', sa.Column('default_cpu_cores', sa.Float(), nullable=False, server_default='0.3'))
    op.add_column('subscription_plan', sa.Column('default_memory_mb', sa.Integer(), nullable=False, server_default='300'))
    op.add_column('subscription_plan', sa.Column('max_cpu_cores', sa.Float(), nullable=False, server_default='0.5'))
    op.add_column('subscription_plan', sa.Column('max_memory_mb', sa.Integer(), nullable=False, server_default='500'))
    
    # Add resource columns to project table
    op.add_column('project', sa.Column('allocated_cpu_cores', sa.Float(), nullable=True))
    op.add_column('project', sa.Column('allocated_memory_mb', sa.Integer(), nullable=True))
    
    # Update existing plans with specific values
    op.execute("""
        UPDATE subscription_plan 
        SET 
            default_cpu_cores = 0.3,
            default_memory_mb = 300,
            max_cpu_cores = 0.5,
            max_memory_mb = 500
        WHERE name = 'free'
    """)
    
    op.execute("""
        UPDATE subscription_plan 
        SET 
            default_cpu_cores = 0.5,
            default_memory_mb = 512,
            max_cpu_cores = 4.0,
            max_memory_mb = 6144
        WHERE name = 'pay_as_you_go'
    """)
    
    # Sync project.config values to new columns
    op.execute("""
        UPDATE project 
        SET 
            allocated_cpu_cores = CAST(config->>'cpus' AS FLOAT)
        WHERE config ? 'cpus' AND config->>'cpus' IS NOT NULL
    """)
    
    op.execute("""
        UPDATE project 
        SET 
            allocated_memory_mb = CAST(config->>'memory' AS INTEGER)
        WHERE config ? 'memory' AND config->>'memory' IS NOT NULL
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove resource columns from project table
    op.drop_column('project', 'allocated_memory_mb')
    op.drop_column('project', 'allocated_cpu_cores')
    
    # Remove resource columns from subscription_plan table
    op.drop_column('subscription_plan', 'max_memory_mb')
    op.drop_column('subscription_plan', 'max_cpu_cores')
    op.drop_column('subscription_plan', 'default_memory_mb')
    op.drop_column('subscription_plan', 'default_cpu_cores')
