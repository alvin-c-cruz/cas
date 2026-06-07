"""drop login_history table

Revision ID: 93433089aa65
Revises: 4a8ce30aab16
Create Date: 2026-06-07 17:23:14.547876

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '93433089aa65'
down_revision = '4a8ce30aab16'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the login_history table (data was migrated to audit_logs in 4a8ce30aab16)
    op.drop_table('login_history')


def downgrade():
    # Recreate the login_history table structure (without data)
    op.create_table(
        'login_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=80), nullable=False),
        sa.Column('full_name', sa.String(length=200), nullable=False),
        sa.Column('login_time', sa.DateTime(), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('failure_reason', sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
