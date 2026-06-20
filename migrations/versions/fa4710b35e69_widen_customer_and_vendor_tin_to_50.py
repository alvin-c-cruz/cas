"""widen customer and vendor tin to 50

Revision ID: fa4710b35e69
Revises: dbd1ccadf758
Create Date: 2026-06-21 00:22:03.018643

Scoped to ONLY the customers.tin / vendors.tin width change. Alembic autogenerate
also surfaced pre-existing model/DB drift (purchase_bills->accounts_payable index
renames, a stale `receipts` table) — deliberately excluded here so this migration
does exactly one thing.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fa4710b35e69'
down_revision = 'dbd1ccadf758'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.alter_column('tin',
               existing_type=sa.VARCHAR(length=20),
               type_=sa.String(length=50),
               existing_nullable=True)

    with op.batch_alter_table('vendors', schema=None) as batch_op:
        batch_op.alter_column('tin',
               existing_type=sa.VARCHAR(length=20),
               type_=sa.String(length=50),
               existing_nullable=True)


def downgrade():
    with op.batch_alter_table('vendors', schema=None) as batch_op:
        batch_op.alter_column('tin',
               existing_type=sa.String(length=50),
               type_=sa.VARCHAR(length=20),
               existing_nullable=True)

    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.alter_column('tin',
               existing_type=sa.String(length=50),
               type_=sa.VARCHAR(length=20),
               existing_nullable=True)
