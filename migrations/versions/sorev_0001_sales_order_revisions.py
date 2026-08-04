"""add sales_order_revisions table

Revision ID: sorev_0001
Revises: bomloss_0001
Create Date: 2026-08-04

R-01 post-confirm amendment. Append-only revision log for Sales Orders: one row
per revision holding a full JSON snapshot of the order as of that revision, plus
a cached change summary against the previous one.

New table only -- no ALTER on an existing table, so no batch_alter_table needed.
"""
from alembic import op
import sqlalchemy as sa


revision = 'sorev_0001'
down_revision = 'bomloss_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'sales_order_revisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sales_order_id', sa.Integer(), nullable=False),
        sa.Column('revision_number', sa.Integer(), nullable=False),
        sa.Column('snapshot_json', sa.Text(), nullable=False),
        sa.Column('change_summary', sa.Text(), nullable=True),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('authorizing_po_number', sa.String(length=100), nullable=True),
        sa.Column('amended_by_id', sa.Integer(), nullable=True),
        sa.Column('amended_at', sa.DateTime(), nullable=False),
        sa.Column('branch_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id']),
        sa.ForeignKeyConstraint(['amended_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sales_order_id', 'revision_number',
                            name='uq_so_revision_number'),
    )
    op.create_index('ix_sales_order_revisions_sales_order_id',
                    'sales_order_revisions', ['sales_order_id'])
    op.create_index('ix_sales_order_revisions_branch_id',
                    'sales_order_revisions', ['branch_id'])


def downgrade():
    op.drop_index('ix_sales_order_revisions_branch_id', 'sales_order_revisions')
    op.drop_index('ix_sales_order_revisions_sales_order_id', 'sales_order_revisions')
    op.drop_table('sales_order_revisions')
