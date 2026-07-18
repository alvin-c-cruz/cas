"""backfill petty cash due to custodian account

Revision ID: 914f97cdfb0e
Revises: 3ddfe9e60632
Create Date: 2026-07-18 22:02:19.137568

R-04 slice 4. Idempotent: only assigns the setting if it's currently unassigned
AND a matching-code account exists on that instance's chart. Same per-chart
candidate-code approach as 3ddfe9e60632 (the Cash Short/Over backfill) -- no
single code is free across every chart's own liability numbering:
  seed_data.py         -> 20503 (under 20500 Accrued Expenses)
  firm_coa.py           -> 20105 (under 20100 Trade and Other Payables)
  construction_coa.py   -> 20105 (under 20100)
  manufacturing_coa.py  -> 20110 (under 20100)
  demo_seed.py           -> 20112 (under 20000, flat)
  food_demo.py           -> 20407 (under 20400 Accrued and Statutory Payables)
Existing/live instances matching none of these get NO auto-assignment
(fail-closed persists until an accountant assigns manually in Company Settings
-> Control Accounts). Mirrors the raw-SQL style of
ca5f99361716_backfill_control_account_settings.py.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '914f97cdfb0e'
down_revision = '3ddfe9e60632'
branch_labels = None
depends_on = None

_SETTING_KEY = 'petty_cash_due_to_custodian_account_code'
_CANDIDATE_CODES = ['20503', '20105', '20110', '20112', '20407']


def upgrade():
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM app_settings WHERE key = :k"),
        {'k': _SETTING_KEY}).first()
    if exists:
        return
    for code in _CANDIDATE_CODES:
        acct = conn.execute(
            sa.text("SELECT 1 FROM accounts WHERE code = :c"),
            {'c': code}).first()
        if acct is None:
            continue
        conn.execute(
            sa.text("INSERT INTO app_settings (key, value, updated_by) "
                    "VALUES (:k, :v, 'migration')"),
            {'k': _SETTING_KEY, 'v': code})
        return
    # chart matches none of the known candidate codes -> leave unassigned (fail-closed)


def downgrade():
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM app_settings WHERE key = :k AND updated_by = 'migration'"),
        {'k': _SETTING_KEY})
