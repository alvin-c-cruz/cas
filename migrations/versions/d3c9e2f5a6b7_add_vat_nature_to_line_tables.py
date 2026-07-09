"""add vat_nature to the four VAT-bearing line tables

Revision ID: d3c9e2f5a6b7
Revises: c2b8d1e4f5a6
Create Date: 2026-07-09

Backfill joins the line's stored category CODE (not name -- lines store 'V12',
'V12SV') to the category table and copies transaction_nature. SI and CRV lines
join sales_vat_categories; AP and CDV lines join vat_categories. An empty or
unmatched code leaves NULL, which the reports surface as 'Unclassified'.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd3c9e2f5a6b7'
down_revision = 'c2b8d1e4f5a6'
branch_labels = None
depends_on = None

# (line table, category table)
BACKFILL = [
    ('sales_invoice_items', 'sales_vat_categories'),
    ('crv_revenue_lines', 'sales_vat_categories'),
    ('accounts_payable_items', 'vat_categories'),
    ('cdv_expense_lines', 'vat_categories'),
]


def upgrade():
    for line_table, _ in BACKFILL:
        with op.batch_alter_table(line_table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('vat_nature', sa.String(length=24),
                                          nullable=True))
            batch_op.create_index(f'ix_{line_table}_vat_nature', ['vat_nature'],
                                  unique=False)

    conn = op.get_bind()
    for line_table, cat_table in BACKFILL:
        conn.execute(sa.text(f"""
            UPDATE {line_table}
               SET vat_nature = (
                   SELECT c.transaction_nature
                     FROM {cat_table} c
                    WHERE c.code = {line_table}.vat_category
               )
             WHERE vat_category IS NOT NULL AND vat_category <> ''
        """))


def downgrade():
    for line_table, _ in BACKFILL:
        with op.batch_alter_table(line_table, schema=None) as batch_op:
            batch_op.drop_index(f'ix_{line_table}_vat_nature')
            batch_op.drop_column('vat_nature')
