"""stock movement ledger: stock_movements + stock_balances

Revision ID: stkmv_0001
Revises: 2bc39f698ae5
Create Date: 2026-07-21
"""
import sqlalchemy as sa
from alembic import op

revision = 'stkmv_0001'
down_revision = '2bc39f698ae5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'stock_movements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('movement_type', sa.String(length=30), nullable=False),
        sa.Column('quantity', sa.Numeric(15, 4), nullable=False),
        sa.Column('unit_cost', sa.Numeric(15, 2), nullable=False),
        sa.Column('balance_qty_after', sa.Numeric(15, 4), nullable=False),
        sa.Column('balance_avg_cost_after', sa.Numeric(15, 2), nullable=False),
        sa.Column('balance_value_after', sa.Numeric(15, 2), nullable=False),
        sa.Column('source_document_type', sa.String(length=40), nullable=True),
        sa.Column('source_document_id', sa.Integer(), nullable=True),
        sa.Column('journal_entry_id', sa.Integer(), sa.ForeignKey('journal_entries.id'), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index('ix_stock_movements_product_id', 'stock_movements', ['product_id'])
    op.create_index('ix_stock_movements_branch_id', 'stock_movements', ['branch_id'])

    op.create_table(
        'stock_balances',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('quantity_on_hand', sa.Numeric(15, 4), nullable=False, server_default='0'),
        sa.Column('average_unit_cost', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('total_value', sa.Numeric(15, 2), nullable=False, server_default='0'),
        # RowVersioned column: MUST carry server_default='1' (rowversioned-new-header-table-migration)
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('product_id', 'branch_id', name='uq_stock_balance_product_branch'),
    )
    op.create_index('ix_stock_balances_product_id', 'stock_balances', ['product_id'])
    op.create_index('ix_stock_balances_branch_id', 'stock_balances', ['branch_id'])


def downgrade():
    op.drop_table('stock_balances')
    op.drop_table('stock_movements')
