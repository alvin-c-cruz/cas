"""CDV check-serial uniqueness per cash/bank account (partial unique index)

A non-null check_number is unique per cash_account_id among NON-voided CDVs
(a voided serial is freed for reuse). Cash-method CDVs (null check_number) are
excluded; different bank accounts may reuse a serial. Adds a partial unique index
only — no column change, so no batch_alter_table needed.

DEPLOY NOTE: if a target DB already holds duplicate (cash_account_id, check_number)
non-null rows on non-voided CDVs, this upgrade FAILS. Check first:
    SELECT cash_account_id, check_number, COUNT(*) c
    FROM cash_disbursement_vouchers
    WHERE check_number IS NOT NULL AND status NOT IN ('voided','cancelled')
    GROUP BY cash_account_id, check_number HAVING c > 1;

Revision ID: c9e1f2a3b4d5
Revises: ad8a4fdb9f89
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa

revision = 'c9e1f2a3b4d5'
down_revision = 'ad8a4fdb9f89'
branch_labels = None
depends_on = None

_INDEX = 'uq_cdv_cash_account_check_number'
_TABLE = 'cash_disbursement_vouchers'
_WHERE = "check_number IS NOT NULL AND status NOT IN ('voided', 'cancelled')"


def upgrade():
    op.create_index(_INDEX, _TABLE, ['cash_account_id', 'check_number'],
                    unique=True, sqlite_where=sa.text(_WHERE))


def downgrade():
    op.drop_index(_INDEX, table_name=_TABLE)
