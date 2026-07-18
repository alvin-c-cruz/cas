"""add ap item variance snapshot columns

Revision ID: 8242857b00da
Revises: c4f8e1a9d5b7
Create Date: 2026-07-18 09:39:40.804580

Four new nullable columns for R-02 Phase 6 (3-way price/quantity variance matching).
FK-shaped columns added as plain Integer (no inline sa.ForeignKey) -- batch mode cannot
name the constraint on an ADD COLUMN, and SQLite FK enforcement is off app-wide. Mirrors
the sales_orders.quotation_id migration (29500ade76f8).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8242857b00da'
down_revision = 'c4f8e1a9d5b7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('accounts_payable_items', schema=None) as b:
        b.add_column(sa.Column('source_po_item_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('source_rr_item_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('matched_unit_price', sa.Numeric(precision=15, scale=2), nullable=True))
        b.add_column(sa.Column('matched_quantity', sa.Numeric(precision=15, scale=4), nullable=True))


def downgrade():
    with op.batch_alter_table('accounts_payable_items', schema=None) as b:
        b.drop_column('matched_quantity')
        b.drop_column('matched_unit_price')
        b.drop_column('source_rr_item_id')
        b.drop_column('source_po_item_id')
