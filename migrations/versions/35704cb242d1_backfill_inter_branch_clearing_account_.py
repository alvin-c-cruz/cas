"""backfill inter-branch clearing account settings

Revision ID: 35704cb242d1
Revises: 431260ceb58c
Create Date: 2026-07-18 18:07:01.009732

R-04 slice 2. Idempotent: only assigns a setting if it's currently unassigned AND
a matching-code account exists on that instance's chart. Existing/live instances
with neither get NO auto-assignment (fail-closed persists until an accountant
assigns manually in Company Settings -> Control Accounts) -- this migration is a
courtesy for freshly-seeded charts (all of which now seed 10213/20111 per
app/seeds/seed_data.py, firm_coa.py, construction_coa.py, manufacturing_coa.py,
demo_seed.py, food_demo.py), not a guarantee. Mirrors the raw-SQL style of
ca5f99361716_backfill_control_account_settings.py (same app_settings columns:
id/key/value/updated_at/updated_by -- confirmed against app/settings.py's
AppSettings model, not the illustrative table()/column() sketch in the task
brief, which named a non-existent "settings" table).
"""
from alembic import op
import sqlalchemy as sa

revision = '35704cb242d1'
down_revision = '431260ceb58c'
branch_labels = None
depends_on = None

# (AppSettings key, seeded account code) — self-contained, no app import.
_BACKFILL = [
    ('inter_branch_due_from_account_code', '10213'),
    ('inter_branch_due_to_account_code',   '20111'),
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
            continue  # chart lacking this code -> leave unassigned (fail-closed)
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
