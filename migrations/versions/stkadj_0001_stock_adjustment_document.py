"""stock adjustment document: stock_adjustments + stock_adjustment_lines

Revision ID: stkadj_0001
Revises: stkmv_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'stkadj_0001'
down_revision = 'stkmv_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'stock_adjustments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sa_number', sa.String(length=50), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('adjustment_date', sa.Date(), nullable=False),
        sa.Column('reason_type', sa.String(length=20), nullable=False, server_default='correction'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('journal_entry_id', sa.Integer(), sa.ForeignKey('journal_entries.id'), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('posted_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('posted_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_stock_adjustments_branch_id', 'stock_adjustments', ['branch_id'])
    # Single unique index, matching the model's Column(unique=True, index=True) exactly --
    # a separate UniqueConstraint alongside this would be a redundant second enforcement
    # mechanism on the same column (review finding: model vs migration schema mismatch).
    op.create_index('ix_stock_adjustments_sa_number', 'stock_adjustments', ['sa_number'], unique=True)
    op.create_table(
        'stock_adjustment_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('adjustment_id', sa.Integer(), sa.ForeignKey('stock_adjustments.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('quantity_delta', sa.Numeric(15, 4), nullable=False),
        sa.Column('unit_cost', sa.Numeric(15, 2), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
    )
    op.create_index('ix_stock_adjustment_lines_adjustment_id', 'stock_adjustment_lines', ['adjustment_id'])


def downgrade():
    op.drop_table('stock_adjustment_lines')
    op.drop_table('stock_adjustments')
