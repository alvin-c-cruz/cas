"""backfill customer WHT m2m from default_wt_code

Revision ID: dbd1ccadf758
Revises: e5281ea855e9
Create Date: 2026-06-20 21:14:59.165595

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dbd1ccadf758'
down_revision = 'e5281ea855e9'
branch_labels = None
depends_on = None


# Seed each customer's new WHT many-to-many list from its legacy single
# default_wt_code, so existing customers keep a working line-WT scope after the
# SI/CRV change. Idempotent (NOT EXISTS guard); only maps to ACTIVE codes.
_BACKFILL_SQL = """
    INSERT INTO customer_withholding_taxes (customer_id, withholding_tax_id)
    SELECT c.id, w.id
    FROM customers c
    JOIN withholding_tax w
      ON w.code = c.default_wt_code AND w.is_active = 1
    WHERE c.default_wt_code IS NOT NULL AND c.default_wt_code != ''
      AND NOT EXISTS (
        SELECT 1 FROM customer_withholding_taxes x
        WHERE x.customer_id = c.id AND x.withholding_tax_id = w.id
      )
"""


def upgrade():
    op.get_bind().execute(sa.text(_BACKFILL_SQL))


def downgrade():
    # Data backfill — not reversed (cannot distinguish backfilled rows from
    # ones a user later added).
    pass
