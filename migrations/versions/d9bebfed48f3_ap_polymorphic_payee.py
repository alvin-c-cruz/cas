"""ap polymorphic payee

Revision ID: d9bebfed48f3
Revises: 88f67c2cc4fb
Create Date: 2026-07-08 09:00:18.937268

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd9bebfed48f3'
down_revision = '88f67c2cc4fb'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('accounts_payable', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payee_type', sa.String(length=20),
                                      nullable=False, server_default='vendor'))
        batch_op.add_column(sa.Column('payee_id', sa.Integer(), nullable=False, server_default='0'))
        batch_op.alter_column('vendor_id', existing_type=sa.Integer(), nullable=True)
        batch_op.create_index('ix_accounts_payable_payee_type', ['payee_type'], unique=False)
    # Backfill: existing rows are all vendor payees.
    op.execute("UPDATE accounts_payable SET payee_type='vendor', payee_id=vendor_id "
               "WHERE payee_id=0 OR payee_id IS NULL")


def downgrade():
    with op.batch_alter_table('accounts_payable', schema=None) as batch_op:
        batch_op.drop_index('ix_accounts_payable_payee_type')
        batch_op.alter_column('vendor_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('payee_id')
        batch_op.drop_column('payee_type')
