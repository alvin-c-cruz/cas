"""drop vat_categories.output_vat_account_id

Revision ID: de12c710cdee
Revises: 020c914cad71
Create Date: 2026-06-20 09:56:59.954349

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'de12c710cdee'
down_revision = '020c914cad71'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # Copy any admin-set output accounts into the sales table (live DBs only;
    # seeded DBs have none). transaction_nature: rate>0 -> regular else zero_export.
    rows = conn.execute(sa.text(
        "SELECT code, name, rate, output_vat_account_id FROM vat_categories "
        "WHERE output_vat_account_id IS NOT NULL")).fetchall()
    for r in rows:
        exists = conn.execute(sa.text(
            "SELECT 1 FROM sales_vat_categories WHERE code = :c"), {"c": r.code}).fetchone()
        if exists:
            continue
        nature = 'regular' if (r.rate or 0) > 0 else 'zero_export'
        conn.execute(sa.text(
            "INSERT INTO sales_vat_categories (code, name, rate, transaction_nature, "
            "output_vat_account_id, is_active) VALUES (:c,:n,:r,:t,:o,1)"),
            {"c": r.code, "n": r.name, "r": r.rate, "t": nature, "o": r.output_vat_account_id})

    with op.batch_alter_table('vat_categories', schema=None) as batch_op:
        batch_op.drop_column('output_vat_account_id')


def downgrade():
    with op.batch_alter_table('vat_categories', schema=None) as batch_op:
        batch_op.add_column(sa.Column('output_vat_account_id', sa.INTEGER(), nullable=True))
