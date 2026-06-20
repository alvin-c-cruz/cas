"""add wht payable/receivable account mapping

Revision ID: 06354ca0c60d
Revises: fa4710b35e69
Create Date: 2026-06-21 01:07:16.122833

Scoped to ONLY the two new withholding_tax FK columns. Alembic autogenerate
again surfaced unrelated pre-existing drift (stale receipts table,
purchase_bills->accounts_payable index renames) — deliberately excluded.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '06354ca0c60d'
down_revision = 'fa4710b35e69'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('withholding_tax', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payable_account_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('receivable_account_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_wht_payable_account', 'accounts', ['payable_account_id'], ['id'])
        batch_op.create_foreign_key('fk_wht_receivable_account', 'accounts', ['receivable_account_id'], ['id'])


def downgrade():
    with op.batch_alter_table('withholding_tax', schema=None) as batch_op:
        batch_op.drop_constraint('fk_wht_receivable_account', type_='foreignkey')
        batch_op.drop_constraint('fk_wht_payable_account', type_='foreignkey')
        batch_op.drop_column('receivable_account_id')
        batch_op.drop_column('payable_account_id')
