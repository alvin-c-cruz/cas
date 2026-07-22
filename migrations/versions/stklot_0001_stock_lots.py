"""Specific-identification lots: stock_lots + stock_lot_consumptions;
stock_adjustment_lines.lot_id/lot_reference

Revision ID: stklot_0001
Revises: stkfifo_0001
Create Date: 2026-07-23
"""
import sqlalchemy as sa
from alembic import op

revision = 'stklot_0001'
down_revision = 'stkfifo_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'stock_lots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('original_qty', sa.Numeric(15, 4), nullable=False),
        sa.Column('remaining_qty', sa.Numeric(15, 4), nullable=False),
        sa.Column('unit_cost', sa.Numeric(15, 2), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.Column('lot_reference', sa.String(length=200), nullable=True),
        sa.Column('source_movement_id', sa.Integer(), sa.ForeignKey('stock_movements.id'), nullable=True),
    )
    op.create_index('ix_stock_lots_product_id', 'stock_lots', ['product_id'])
    op.create_index('ix_stock_lots_branch_id', 'stock_lots', ['branch_id'])
    op.create_index('ix_stock_lots_product_branch_received',
                    'stock_lots', ['product_id', 'branch_id', 'received_at'])

    op.create_table(
        'stock_lot_consumptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('movement_id', sa.Integer(), sa.ForeignKey('stock_movements.id'), nullable=False),
        sa.Column('lot_id', sa.Integer(), sa.ForeignKey('stock_lots.id'), nullable=False),
        sa.Column('qty_consumed', sa.Numeric(15, 4), nullable=False),
        sa.Column('unit_cost_at_consumption', sa.Numeric(15, 2), nullable=False),
    )
    op.create_index('ix_stock_lot_consumptions_movement_id', 'stock_lot_consumptions', ['movement_id'])
    op.create_index('ix_stock_lot_consumptions_lot_id', 'stock_lot_consumptions', ['lot_id'])

    # Plain Integer/String columns, NOT an inline sa.ForeignKey -- SQLite batch
    # mode raises "Constraint must have a name" for an unnamed FK inside a
    # table rebuild. FK enforcement is off app-wide anyway; the ORM model
    # side still declares db.ForeignKey for joins (SalesOrder.quotation_id
    # precedent).
    with op.batch_alter_table('stock_adjustment_lines') as batch_op:
        batch_op.add_column(sa.Column('lot_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('lot_reference', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('stock_adjustment_lines') as batch_op:
        batch_op.drop_column('lot_reference')
        batch_op.drop_column('lot_id')
    op.drop_table('stock_lot_consumptions')
    op.drop_table('stock_lots')
