"""drop sales_order_items.description

Revision ID: 0561206ba8e1
Revises: d9bebfed48f3
Create Date: 2026-07-08 15:33:15.765717

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0561206ba8e1'
down_revision = 'd9bebfed48f3'
branch_labels = None
depends_on = None


def upgrade():
    # Sales Order lines are now product-based; the free-text line description is removed.
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.drop_column('description')


def downgrade():
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('description', sa.String(length=500),
                                      nullable=False, server_default=''))
    with op.batch_alter_table('sales_order_items', schema=None) as batch_op:
        batch_op.alter_column('description', server_default=None)
