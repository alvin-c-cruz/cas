"""add output_vat_account_id to vat_categories

Revision ID: e5f0b6c3d9a1
Revises: 77c2e66f3325
Create Date: 2026-06-14 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f0b6c3d9a1'
down_revision = '77c2e66f3325'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c['name'] for c in inspector.get_columns('vat_categories')]
    if 'output_vat_account_id' not in columns:
        with op.batch_alter_table('vat_categories', schema=None) as batch_op:
            batch_op.add_column(sa.Column('output_vat_account_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                'fk_vatcat_output_vat_account_id', 'accounts',
                ['output_vat_account_id'], ['id']
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c['name'] for c in inspector.get_columns('vat_categories')]
    if 'output_vat_account_id' in columns:
        with op.batch_alter_table('vat_categories', schema=None) as batch_op:
            batch_op.drop_constraint('fk_vatcat_output_vat_account_id', type_='foreignkey')
            batch_op.drop_column('output_vat_account_id')
