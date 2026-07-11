"""backfill control-account settings from legacy codes

Revision ID: ca5f99361716
Revises: be7db1227c52
Create Date: 2026-07-11

Re-parented from d1e2f3a4b5c6 to be7db1227c52 (2026-07-11) when merging
feat/control-accounts into main resolved a concurrent migration-head collision
with the R-02 Purchases migrations (purchase_orders/requests/receiving_reports),
which also chained off d1e2f3a4b5c6. This backfill is data-only and
order-independent of those, so running it after them is safe.
"""
from alembic import op
import sqlalchemy as sa

revision = 'ca5f99361716'
down_revision = 'be7db1227c52'
branch_labels = None
depends_on = None

# (AppSettings key, legacy account code) — self-contained, no app import.
_BACKFILL = [
    ('ar_trade_account_code',       '10201'),
    ('ap_trade_account_code',       '20101'),
    ('creditable_wht_account_code', '10212'),
    ('wht_payable_account_code',    '20301'),
]


def upgrade():
    conn = op.get_bind()
    for setting_key, code in _BACKFILL:
        exists = conn.execute(
            sa.text("SELECT 1 FROM app_settings WHERE key = :k"),
            {'k': setting_key}).first()
        if exists:
            continue
        acct = conn.execute(
            sa.text("SELECT 1 FROM accounts WHERE code = :c"),
            {'c': code}).first()
        if acct is None:
            continue  # self-built chart lacking the legacy code -> leave unassigned
        conn.execute(
            sa.text("INSERT INTO app_settings (key, value, updated_by) "
                    "VALUES (:k, :v, 'migration')"),
            {'k': setting_key, 'v': code})


def downgrade():
    conn = op.get_bind()
    for setting_key, _ in _BACKFILL:
        conn.execute(
            sa.text("DELETE FROM app_settings WHERE key = :k AND updated_by = 'migration'"),
            {'k': setting_key})
