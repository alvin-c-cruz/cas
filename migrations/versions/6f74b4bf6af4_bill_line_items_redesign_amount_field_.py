"""bill line items redesign - amount field, override flags, je fk

Revision ID: 6f74b4bf6af4
Revises: 072ae8773591
Create Date: 2026-06-10 19:23:32.459175

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6f74b4bf6af4'
down_revision = '072ae8773591'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('purchase_bill_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('amount', sa.Numeric(precision=15, scale=2),
                                      nullable=False, server_default='0.00'))
        batch_op.drop_column('quantity')
        batch_op.drop_column('unit_cost')

    with op.batch_alter_table('purchase_bills', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vat_override', sa.Boolean(),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('wt_override', sa.Boolean(),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('journal_entry_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_purchase_bills_je', 'journal_entries',
                                    ['journal_entry_id'], ['id'])


def downgrade():
    with op.batch_alter_table('purchase_bills', schema=None) as batch_op:
        batch_op.drop_constraint('fk_purchase_bills_je', type_='foreignkey')
        batch_op.drop_column('journal_entry_id')
        batch_op.drop_column('wt_override')
        batch_op.drop_column('vat_override')

    with op.batch_alter_table('purchase_bill_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unit_cost', sa.Numeric(precision=15, scale=2),
                                      nullable=False, server_default='0.00'))
        batch_op.add_column(sa.Column('quantity', sa.Numeric(precision=15, scale=4),
                                      nullable=False, server_default='1.0000'))
        batch_op.drop_column('amount')
