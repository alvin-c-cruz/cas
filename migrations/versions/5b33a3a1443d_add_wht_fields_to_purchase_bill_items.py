"""add wht fields to purchase bill items

Revision ID: 5b33a3a1443d
Revises: c87539458f64
Create Date: 2026-06-09 21:59:21.802954

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5b33a3a1443d'
down_revision = 'c87539458f64'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('purchase_bill_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('wt_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('wt_rate', sa.Numeric(precision=5, scale=2), nullable=True))
        batch_op.add_column(sa.Column('wt_amount', sa.Numeric(precision=15, scale=2),
                                      server_default='0.00', nullable=False))
        batch_op.create_foreign_key(
            'fk_purchase_bill_items_wt_id',
            'withholding_tax', ['wt_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('purchase_bill_items', schema=None) as batch_op:
        batch_op.drop_constraint('fk_purchase_bill_items_wt_id', type_='foreignkey')
        batch_op.drop_column('wt_amount')
        batch_op.drop_column('wt_rate')
        batch_op.drop_column('wt_id')
