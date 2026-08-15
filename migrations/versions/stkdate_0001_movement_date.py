"""Stock movement: add movement_date (business-effective date)

Revision ID: stkdate_0001
Revises: pralloc_0001
Create Date: 2026-08-15

StockMovement previously carried only created_at (default=ph_now), so both the
FIFO and LIFO engines ordered by the moment Approve was clicked rather than the
date on the document. movement_date is the business-effective date; created_at
survives as an audit value and an ordering tiebreak.

Added nullable, backfilled from DATE(created_at), then made NOT NULL -- the
three-step dance SQLite requires for a NOT NULL column on an existing table.

stock_cost_layers.received_at is also normalised to midnight so pre-existing
layers sort consistently with new ones (which are written as
datetime.combine(movement_date, time.min)). A pre-existing opening-balance
layer (source_movement_id IS NULL, original_qty > 0) is additionally re-dated
to the datetime.min sentinel, matching bootstrap_opening_layer_if_needed's
current behaviour for newly-bootstrapped layers.
"""
import sqlalchemy as sa
from alembic import op

revision = 'stkdate_0001'
down_revision = 'pralloc_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('stock_movements', schema=None) as batch_op:
        batch_op.add_column(sa.Column('movement_date', sa.Date(), nullable=True))

    op.execute('UPDATE stock_movements SET movement_date = DATE(created_at)')

    with op.batch_alter_table('stock_movements', schema=None) as batch_op:
        batch_op.alter_column('movement_date', existing_type=sa.Date(), nullable=False)
        batch_op.create_index('ix_stock_movements_movement_date',
                              ['movement_date'], unique=False)

    # Normalise existing layers/lots to midnight of their date so old rows sort
    # consistently against new ones.
    op.execute("UPDATE stock_cost_layers SET received_at = DATE(received_at)")
    op.execute("UPDATE stock_lots SET received_at = DATE(received_at)")

    # Re-date pre-existing opening-balance layers to the sentinel. Before this
    # change the bootstrap wrote ph_now(), which normalises above to midnight of
    # whatever date happened to trigger it -- leaving a later-posted but
    # earlier-dated receipt sorting ahead of the opening stock. original_qty > 0
    # is load-bearing: virgin zero-cost DEFICIT layers also carry
    # source_movement_id IS NULL and must NOT be moved.
    op.execute("UPDATE stock_cost_layers SET received_at = '0001-01-01 00:00:00.000000' "
               "WHERE source_movement_id IS NULL AND original_qty > 0")


def downgrade():
    with op.batch_alter_table('stock_movements', schema=None) as batch_op:
        batch_op.drop_index('ix_stock_movements_movement_date')
        batch_op.drop_column('movement_date')
    # received_at normalisation is not reversed: the original time-of-day is not
    # recoverable, and midnight is a valid value for the column either way.
