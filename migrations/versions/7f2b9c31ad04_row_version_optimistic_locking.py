"""add row_version to transaction document headers (lost-update guard)

Optimistic-locking counter for the seven documents that have an edit route.
Every edit is a replace-all (lines discarded and rebuilt; APV/CDV/CRV also
delete and recreate the linked JE), so two encoders on one draft meant the
second save silently destroyed the first one's work.

server_default='1' backfills existing rows; the column is NOT NULL.

Journal entries are excluded on purpose: they have no edit route.

Revision ID: 7f2b9c31ad04
Revises: 29500ade76f8
Create Date: 2026-07-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7f2b9c31ad04'
down_revision = '29500ade76f8'
branch_labels = None
depends_on = None


VERSIONED_TABLES = (
    'accounts_payable',
    'cash_disbursement_vouchers',
    'cash_receipt_vouchers',
    'sales_invoices',
    'sales_orders',
    'quotations',
    'delivery_receipts',
)


def upgrade():
    for table in VERSIONED_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column('row_version', sa.Integer(), nullable=False, server_default='1')
            )


def downgrade():
    for table in VERSIONED_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column('row_version')
