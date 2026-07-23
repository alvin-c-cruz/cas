"""Physical Count: physical_counts + physical_count_lines

Revision ID: physcount_0001
Revises: stklot_0001
Create Date: 2026-07-23
"""
import sqlalchemy as sa
from alembic import op

revision = 'physcount_0001'
down_revision = 'stklot_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'physical_counts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('pc_number', sa.String(length=50), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('count_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('stock_adjustment_id', sa.Integer(), sa.ForeignKey('stock_adjustments.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
    )
    with op.batch_alter_table('physical_counts', schema=None) as batch_op:
        batch_op.create_index('ix_physical_counts_branch_id', ['branch_id'], unique=False)
        batch_op.create_index('ix_physical_counts_pc_number', ['pc_number'], unique=True)

    op.create_table(
        'physical_count_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('count_id', sa.Integer(), sa.ForeignKey('physical_counts.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('book_qty_snapshot', sa.Numeric(15, 4), nullable=False),
        sa.Column('counted_qty', sa.Numeric(15, 4), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
    )
    with op.batch_alter_table('physical_count_lines', schema=None) as batch_op:
        batch_op.create_index('ix_physical_count_lines_count_id', ['count_id'], unique=False)


def downgrade():
    op.drop_table('physical_count_lines')
    op.drop_table('physical_counts')
