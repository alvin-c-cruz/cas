"""add tax_type to withholding_tax

Revision ID: c2b8d1e4f5a6
Revises: b1a7c0d3e4f5
Create Date: 2026-07-09

Every existing row is backfilled to 'expanded'. NOT code-keyed: ATC codes are not
stable across instances (WC160 is "Services" in the standard seed and "Rentals" in
philgen_demo.db), so a code carries no reliable regime signal. An accountant
reclassifies a final-tax code through the normal WT change-request flow.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c2b8d1e4f5a6'
down_revision = 'b1a7c0d3e4f5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('withholding_tax', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tax_type', sa.String(length=10),
                                      nullable=False, server_default='expanded'))


def downgrade():
    with op.batch_alter_table('withholding_tax', schema=None) as batch_op:
        batch_op.drop_column('tax_type')
