"""fix payment terms data

Revision ID: c4ae455329f9
Revises: 5b33a3a1443d
Create Date: 2026-06-09 23:00:09.357824

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4ae455329f9'
down_revision = '5b33a3a1443d'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE vendors SET payment_terms = 'Cash on Delivery' WHERE payment_terms = 'COD'")
    op.execute("UPDATE vendors SET payment_terms = 'Advance Payment' WHERE payment_terms = 'Advance'")


def downgrade():
    op.execute("UPDATE vendors SET payment_terms = 'COD' WHERE payment_terms = 'Cash on Delivery'")
    op.execute("UPDATE vendors SET payment_terms = 'Advance' WHERE payment_terms = 'Advance Payment'")
