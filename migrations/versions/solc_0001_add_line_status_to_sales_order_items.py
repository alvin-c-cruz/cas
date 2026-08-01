"""add line_status and closed_* columns to sales_order_items

Revision ID: solc_0001
Revises: sowt_0001
Create Date: 2026-07-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'solc_0001'
down_revision = 'sowt_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('line_status', sa.String(length=20), nullable=False,
                                       server_default='open'))
        batch_op.add_column(sa.Column('closed_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('closed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('closed_reason', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.drop_column('closed_reason')
        batch_op.drop_column('closed_at')
        batch_op.drop_column('closed_by_id')
        batch_op.drop_column('line_status')
