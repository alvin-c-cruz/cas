"""normalize payment terms COD and Advance in customers sales_invoices purchase_bills

Revision ID: 5ad857a1cba7
Revises: c4ae455329f9
Create Date: 2026-06-10 06:05:21.389316

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5ad857a1cba7'
down_revision = 'c4ae455329f9'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE customers SET payment_terms = 'Cash on Delivery' WHERE payment_terms = 'COD'")
    op.execute("UPDATE customers SET payment_terms = 'Advance Payment' WHERE payment_terms = 'Advance'")
    op.execute("UPDATE sales_invoices SET payment_terms = 'Cash on Delivery' WHERE payment_terms = 'COD'")
    op.execute("UPDATE sales_invoices SET payment_terms = 'Advance Payment' WHERE payment_terms = 'Advance'")
    op.execute("UPDATE purchase_bills SET payment_terms = 'Cash on Delivery' WHERE payment_terms = 'COD'")
    op.execute("UPDATE purchase_bills SET payment_terms = 'Advance Payment' WHERE payment_terms = 'Advance'")


def downgrade():
    op.execute("UPDATE customers SET payment_terms = 'COD' WHERE payment_terms = 'Cash on Delivery'")
    op.execute("UPDATE customers SET payment_terms = 'Advance' WHERE payment_terms = 'Advance Payment'")
    op.execute("UPDATE sales_invoices SET payment_terms = 'COD' WHERE payment_terms = 'Cash on Delivery'")
    op.execute("UPDATE sales_invoices SET payment_terms = 'Advance' WHERE payment_terms = 'Advance Payment'")
    op.execute("UPDATE purchase_bills SET payment_terms = 'COD' WHERE payment_terms = 'Cash on Delivery'")
    op.execute("UPDATE purchase_bills SET payment_terms = 'Advance' WHERE payment_terms = 'Advance Payment'")
