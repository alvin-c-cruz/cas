"""backfill control-account settings from legacy codes

Revision ID: ca5f99361716
Revises: d1e2f3a4b5c6
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'ca5f99361716'
down_revision = 'd1e2f3a4b5c6'
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
