"""add work centers table

Revision ID: fa3ca2bc569d
Revises: 0b9ae80e3222
Create Date: 2026-07-19 10:04:59.085283

R-07 Discrete Track slice D1: WorkCenter master data. Brand-new table.
"""
from alembic import op
import sqlalchemy as sa


revision = 'fa3ca2bc569d'
down_revision = '0b9ae80e3222'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('work_centers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('hourly_rate', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('work_centers', schema=None) as b:
        b.create_index('ix_work_centers_branch_id', ['branch_id'])
        b.create_index('ix_work_centers_code', ['code'])


def downgrade():
    with op.batch_alter_table('work_centers', schema=None) as b:
        b.drop_index('ix_work_centers_code')
        b.drop_index('ix_work_centers_branch_id')
    op.drop_table('work_centers')
