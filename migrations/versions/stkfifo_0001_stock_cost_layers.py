"""FIFO cost layers: stock_cost_layers + stock_layer_consumptions

Revision ID: stkfifo_0001
Revises: drje_0001
Create Date: 2026-07-22
"""
import sqlalchemy as sa
from alembic import op

revision = 'stkfifo_0001'
down_revision = 'drje_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'stock_cost_layers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('original_qty', sa.Numeric(15, 4), nullable=False),
        sa.Column('remaining_qty', sa.Numeric(15, 4), nullable=False),
        sa.Column('unit_cost', sa.Numeric(15, 2), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.Column('source_movement_id', sa.Integer(), sa.ForeignKey('stock_movements.id'), nullable=True),
    )
    op.create_index('ix_stock_cost_layers_product_id', 'stock_cost_layers', ['product_id'])
    op.create_index('ix_stock_cost_layers_branch_id', 'stock_cost_layers', ['branch_id'])
    op.create_index('ix_stock_cost_layers_product_branch_received',
                    'stock_cost_layers', ['product_id', 'branch_id', 'received_at'])
    # Guards against a genuine concurrent double-bootstrap creating two opening
    # layers for the same product/branch (source_movement_id IS NULL identifies
    # the one-time cutover layer) -- same corruption-prevention role as
    # uq_stock_balance_product_branch plays for StockBalance's own bootstrap
    # race in _get_or_create_balance; a lost race raises IntegrityError rather
    # than silently duplicating, matching that existing precedent's accepted
    # risk posture (not caught/retried there either).
    op.create_index(
        'uq_stock_cost_layers_opening_layer', 'stock_cost_layers',
        ['product_id', 'branch_id'], unique=True,
        sqlite_where=sa.text('source_movement_id IS NULL'))

    op.create_table(
        'stock_layer_consumptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('movement_id', sa.Integer(), sa.ForeignKey('stock_movements.id'), nullable=False),
        sa.Column('layer_id', sa.Integer(), sa.ForeignKey('stock_cost_layers.id'), nullable=False),
        sa.Column('qty_consumed', sa.Numeric(15, 4), nullable=False),
        sa.Column('unit_cost_at_consumption', sa.Numeric(15, 2), nullable=False),
    )
    op.create_index('ix_stock_layer_consumptions_movement_id', 'stock_layer_consumptions', ['movement_id'])
    op.create_index('ix_stock_layer_consumptions_layer_id', 'stock_layer_consumptions', ['layer_id'])


def downgrade():
    op.drop_table('stock_layer_consumptions')
    op.drop_table('stock_cost_layers')
