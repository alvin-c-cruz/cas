"""debit note collectible: sales_memos amount_paid/balance + polymorphic crv_ar_lines

Revision ID: b8d4c1f2a9e3
Revises: 3182de046105
Create Date: 2026-07-10 12:00:00.000000

Phase 2b: a posted debit note becomes a collectible AR document. Adds amount_paid/balance
to sales_memos, and makes crv_ar_lines polymorphic (add sales_memo_id, relax invoice_id
NOT NULL so a line references either a Sales Invoice OR a debit note). sales_memo_id is a
plain Integer (no inline FK — batch add_column can't name the constraint; SQLite FK
enforcement is off app-wide; the ORM model declares the FK for joins).
"""
from alembic import op
import sqlalchemy as sa


revision = 'b8d4c1f2a9e3'
down_revision = '3182de046105'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sales_memos', schema=None) as b:
        b.add_column(sa.Column('amount_paid', sa.Numeric(precision=15, scale=2),
                               nullable=False, server_default='0.00'))
        b.add_column(sa.Column('balance', sa.Numeric(precision=15, scale=2),
                               nullable=False, server_default='0.00'))
    with op.batch_alter_table('crv_ar_lines', schema=None) as b:
        b.add_column(sa.Column('sales_memo_id', sa.Integer(), nullable=True))
        b.alter_column('invoice_id', existing_type=sa.Integer(), nullable=True)
        b.create_index('ix_crv_ar_lines_sales_memo_id', ['sales_memo_id'])


def downgrade():
    with op.batch_alter_table('crv_ar_lines', schema=None) as b:
        b.drop_index('ix_crv_ar_lines_sales_memo_id')
        b.alter_column('invoice_id', existing_type=sa.Integer(), nullable=False)
        b.drop_column('sales_memo_id')
    with op.batch_alter_table('sales_memos', schema=None) as b:
        b.drop_column('balance')
        b.drop_column('amount_paid')
