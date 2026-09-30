"""sales order attachments: approved_incomplete_slots marker on sales_orders

Revision ID: soatt_0001
Revises: prlydrop_0001
Create Date: 2026-09-30

Sales Orders join the shared attachments (Customer PO, Signed SO, Signed JO, plus
Other). The files themselves go in the existing polymorphic `document_attachments`
table, so the only schema change is the same nullable marker reqatt_0001 gave the
other approvable documents: a JSON snapshot of the required slots still empty at
CONFIRM time, which drives the "confirmed with N required files missing" badge.

A plain nullable Text column with no FK -- batch mode only for SQLite's ALTER
limitation. Verify against a COPY of a real database (project migration rules).
"""
from alembic import op
import sqlalchemy as sa


revision = 'soatt_0001'
down_revision = 'prlydrop_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sales_orders') as batch_op:
        batch_op.add_column(sa.Column('approved_incomplete_slots', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('sales_orders') as batch_op:
        batch_op.drop_column('approved_incomplete_slots')
