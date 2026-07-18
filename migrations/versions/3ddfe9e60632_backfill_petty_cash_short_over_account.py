"""backfill petty cash short/over account

Revision ID: 3ddfe9e60632
Revises: caef66b747dd
Create Date: 2026-07-18 21:32:55.085366

R-04 slice 4. Idempotent: only assigns the setting if it's currently unassigned
AND a matching-code account exists on that instance's chart. Unlike slice 2's
Due-from/Due-to pair, no single code is free across every seed chart (food_demo's
"Other Expenses" section uses a 70xxx scheme, not 50xxx) -- so this tries a
per-chart candidate code list in order and stops at the first match:
  seed_data.py / firm_coa.py / demo_seed.py -> 50303
  construction_coa.py                       -> 50304
  manufacturing_coa.py                      -> 50305
  food_demo.py (+ philgen_demo.py reuse)    -> 70103
Existing/live instances matching none of these get NO auto-assignment
(fail-closed persists until an accountant assigns manually in Company Settings ->
Control Accounts). Mirrors the raw-SQL style of
ca5f99361716_backfill_control_account_settings.py / 35704cb242d1 (same
app_settings columns: id/key/value/updated_at/updated_by).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3ddfe9e60632'
down_revision = 'caef66b747dd'
branch_labels = None
depends_on = None

_SETTING_KEY = 'petty_cash_short_over_account_code'
_CANDIDATE_CODES = ['50303', '50304', '50305', '70103']


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
