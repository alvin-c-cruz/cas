"""add customer_withholding_taxes association table

Revision ID: e5281ea855e9
Revises: de12c710cdee
Create Date: 2026-06-20 20:22:48.215246

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5281ea855e9'
down_revision = 'de12c710cdee'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('customer_withholding_taxes',
    sa.Column('customer_id', sa.Integer(), nullable=False),
    sa.Column('withholding_tax_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.ForeignKeyConstraint(['withholding_tax_id'], ['withholding_tax.id'], ),
    sa.PrimaryKeyConstraint('customer_id', 'withholding_tax_id')
    )


def downgrade():
    op.drop_table('customer_withholding_taxes')
