"""opening_balance_change_requests table

Revision ID: 54f6a297dfde
Revises: 318ee8bbb515
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa

revision = '54f6a297dfde'
down_revision = '318ee8bbb515'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'opening_balance_change_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=True),
        sa.Column('change_data', sa.Text(), nullable=False),
        sa.Column('requested_by', sa.String(length=100), nullable=False),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reviewed_by', sa.String(length=100), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('request_reason', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('opening_balance_change_requests', schema=None) as batch_op:
        batch_op.create_index('ix_opening_balance_change_requests_branch_id',
                              ['branch_id'], unique=False)


def downgrade():
    with op.batch_alter_table('opening_balance_change_requests', schema=None) as batch_op:
        batch_op.drop_index('ix_opening_balance_change_requests_branch_id')
    op.drop_table('opening_balance_change_requests')
