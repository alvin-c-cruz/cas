"""Purchase order item: add source_pr_item_id

Revision ID: pralloc_0001
Revises: prdate_0002
Create Date: 2026-08-15

Links a purchase-order line back to the requisition line it was pulled from.
This is the only storage the allocation feature adds -- how much of a
requisition line remains open is derived by summing these.

Bare Integer, not a ForeignKey: SQLite batch add_column raises
"Constraint must have a name" on an inline FK, and FK enforcement is off
app-wide. Same treatment as SalesOrder.quotation_id (29500ade76f8).

Nullable with no default and no data migration: every existing PO line gets
NULL, meaning "typed by hand, not pulled from a requisition", which is true.
"""
import sqlalchemy as sa
from alembic import op

revision = 'pralloc_0001'
down_revision = 'prdate_0002'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('purchase_order_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_pr_item_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_purchase_order_items_source_pr_item_id',
                              ['source_pr_item_id'], unique=False)


def downgrade():
    with op.batch_alter_table('purchase_order_items', schema=None) as batch_op:
        batch_op.drop_index('ix_purchase_order_items_source_pr_item_id')
        batch_op.drop_column('source_pr_item_id')
