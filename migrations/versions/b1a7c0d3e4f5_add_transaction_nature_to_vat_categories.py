"""add transaction_nature to vat_categories

Revision ID: b1a7c0d3e4f5
Revises: 29500ade76f8
Create Date: 2026-07-09

Backfills from the seeded code vocabularies (standard 7-code and legacy 4-code).
Client-created codes resolve to NULL = unclassified, surfaced in the reports.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b1a7c0d3e4f5'
down_revision = '29500ade76f8'
branch_labels = None
depends_on = None

NATURE_BY_CODE = {
    'V12CG': 'capital_goods',
    'V12DG': 'domestic_goods',
    'V12SV': 'domestic_services',
    'V12IM': 'importation',
    'VEX': 'exempt',
    'V0': 'zero_rated',
    'INV': 'not_qualified',
    'VATABLE': 'domestic_goods',
    'VAT-EXEMPT': 'exempt',
    'ZERO-RATED': 'zero_rated',
    'NON-VAT': 'not_qualified',
}


def upgrade():
    with op.batch_alter_table('vat_categories', schema=None) as batch_op:
        batch_op.add_column(sa.Column('transaction_nature', sa.String(length=30),
                                      nullable=True))

    conn = op.get_bind()
    for code, nature in NATURE_BY_CODE.items():
        conn.execute(
            sa.text('UPDATE vat_categories SET transaction_nature = :n WHERE code = :c'),
            {'n': nature, 'c': code},
        )


def downgrade():
    with op.batch_alter_table('vat_categories', schema=None) as batch_op:
        batch_op.drop_column('transaction_nature')
