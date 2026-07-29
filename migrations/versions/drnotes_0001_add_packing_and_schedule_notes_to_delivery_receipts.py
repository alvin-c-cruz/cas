"""add packing_notes and schedule_notes to delivery_receipts

Revision ID: drnotes_0001
Revises: solc_0001
Create Date: 2026-07-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'drnotes_0001'
down_revision = 'solc_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('delivery_receipts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('packing_notes', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('schedule_notes', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('delivery_receipts', schema=None) as batch_op:
        batch_op.drop_column('schedule_notes')
        batch_op.drop_column('packing_notes')
