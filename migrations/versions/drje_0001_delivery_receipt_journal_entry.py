"""delivery_receipts.journal_entry_id (R-03 slice 2a-iii)

Revision ID: drje_0001
Revises: rritemsm_0001
"""
import sqlalchemy as sa
from alembic import op

revision = 'drje_0001'
down_revision = 'rritemsm_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('delivery_receipts') as batch_op:
        batch_op.add_column(sa.Column('journal_entry_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('delivery_receipts') as batch_op:
        batch_op.drop_column('journal_entry_id')
