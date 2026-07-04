"""printlayout account_id

Revision ID: 307cc71c8779
Revises: f826f2cca271
Create Date: 2026-07-04 08:19:56.823698

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '307cc71c8779'
down_revision = 'f826f2cca271'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('print_layouts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('account_id', sa.Integer(), nullable=True))
        batch_op.alter_column('voucher_type', existing_type=sa.String(length=8),
                              type_=sa.String(length=16), existing_nullable=False)
        # DROP the old single-column UNIQUE INDEX (created unique=True in f826f2cca271).
        batch_op.drop_index('ix_print_layouts_voucher_type')
        batch_op.create_index(batch_op.f('ix_print_layouts_voucher_type'), ['voucher_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_print_layouts_account_id'), ['account_id'], unique=False)
        batch_op.create_foreign_key('fk_print_layouts_account_id_accounts',
                                    'accounts', ['account_id'], ['id'])
        batch_op.create_unique_constraint('uq_print_layouts_voucher_type_account_id',
                                          ['voucher_type', 'account_id'])
    # Partial unique index: one Default (account_id IS NULL) per voucher_type. SQLite treats NULLs
    # as distinct in the composite unique, so this closes the duplicate-Default hole + the race.
    op.create_index('uq_print_layouts_default_per_type', 'print_layouts', ['voucher_type'],
                    unique=True, sqlite_where=sa.text('account_id IS NULL'))


def downgrade():
    op.drop_index('uq_print_layouts_default_per_type', table_name='print_layouts')
    with op.batch_alter_table('print_layouts', schema=None) as batch_op:
        batch_op.drop_constraint('uq_print_layouts_voucher_type_account_id', type_='unique')
        batch_op.drop_constraint('fk_print_layouts_account_id_accounts', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_print_layouts_account_id'))
        batch_op.drop_index(batch_op.f('ix_print_layouts_voucher_type'))
        batch_op.create_index('ix_print_layouts_voucher_type', ['voucher_type'], unique=True)
        batch_op.alter_column('voucher_type', existing_type=sa.String(length=16),
                              type_=sa.String(length=8), existing_nullable=False)
        batch_op.drop_column('account_id')
