"""add carrier, checked_by, approved_by to delivery_receipts

Revision ID: drdata_0001
Revises: prodcc_0001
Create Date: 2026-07-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'drdata_0001'
down_revision = 'prodcc_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('delivery_receipts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('carrier', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('checked_by', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('approved_by', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('delivery_receipts', schema=None) as batch_op:
        batch_op.drop_column('approved_by')
        batch_op.drop_column('checked_by')
        batch_op.drop_column('carrier')
