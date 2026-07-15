"""permission_change_requests table

Revision ID: e26366f5addf
Revises: 54f6a297dfde
Create Date: 2026-07-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'e26366f5addf'
down_revision = '54f6a297dfde'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'permission_change_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('target_user_id', sa.Integer(), nullable=False),
        sa.Column('requested_by_id', sa.Integer(), nullable=False),
        sa.Column('requested_permissions', sa.Text(), nullable=True),
        sa.Column('request_reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['target_user_id'], ['users.id'], name='fk_pcr_target_user_id'),
        sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], name='fk_pcr_requested_by_id'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], name='fk_pcr_reviewed_by_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('permission_change_requests', schema=None) as batch_op:
        batch_op.create_index('ix_permission_change_requests_target_user_id',
                              ['target_user_id'], unique=False)
        batch_op.create_index('ix_permission_change_requests_status',
                              ['status'], unique=False)


def downgrade():
    with op.batch_alter_table('permission_change_requests', schema=None) as batch_op:
        batch_op.drop_index('ix_permission_change_requests_status')
        batch_op.drop_index('ix_permission_change_requests_target_user_id')
    op.drop_table('permission_change_requests')
