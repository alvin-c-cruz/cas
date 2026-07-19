"""fix petty cash control accounts to match by name, not code

Revision ID: 97ec45ed7eb1
Revises: 0b9ae80e3222
Create Date: 2026-07-19 11:00:00.000000

R-04 slice 4 follow-up. The two original backfill migrations (3ddfe9e60632 Cash
Short/Over, 914f97cdfb0e Due to Petty Cash Custodian) auto-assign a control-account
setting by matching a hardcoded candidate account CODE against `accounts.code`, with
no check that the matched account's NAME is actually right. On construction_coa.py's
own chart, code 20503 is "Current Portion of Long-Term Debt" and code 50303 is "Loss
on Disposal of Assets" -- both sit ahead of the chart's real 20105/50304 "Due to
Petty Cash Custodian"/"Cash Short/Over" codes in the candidate lists, so the buggy
migrations always matched the WRONG account first. Confirmed live on Zhiyuan's real
backup (docs/bug-reports/2026-07-19-pettycash-backfill-wrong-control-account.md).

This migration re-derives both settings by account NAME instead, and only ever
touches a row the two ORIGINAL migrations themselves inserted (updated_by='migration')
-- never a value an accountant deliberately assigned via Company Settings ->
Control Accounts. Idempotent and safe to run on a DB where the buggy migrations
already ran (corrects the row) or never ran at all (no-op, nothing to correct).

Note: does NOT edit 3ddfe9e60632/914f97cdfb0e in place -- both are already merged to
main and may already be applied on some database, and Alembic never re-runs an
already-stamped revision, so editing their bodies would silently diverge behavior
between old and new databases. A corrective migration layered on top fixes both
never-yet-migrated AND already-migrated databases uniformly.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '97ec45ed7eb1'
down_revision = '0b9ae80e3222'
branch_labels = None
depends_on = None

_FIXES = [
    ('petty_cash_due_to_custodian_account_code', 'Due to Petty Cash Custodian'),
    ('petty_cash_short_over_account_code', 'Cash Short/Over'),
]


def upgrade():
    conn = op.get_bind()
    for setting_key, correct_name in _FIXES:
        existing = conn.execute(
            sa.text("SELECT value, updated_by FROM app_settings WHERE key = :k"),
            {'k': setting_key}).first()

        correct_account = conn.execute(
            sa.text("SELECT code FROM accounts WHERE name = :n"),
            {'n': correct_name}).first()
        correct_code = correct_account[0] if correct_account else None

        if existing is None:
            # Never assigned -- nothing to correct, fail-closed stays fail-closed.
            continue
        value, updated_by = existing
        if updated_by != 'migration':
            # An accountant (or anything other than the original backfill) already
            # owns this value -- never overwrite a deliberate human choice.
            continue
        if value == correct_code:
            # Already correct (e.g. seed_data.py's chart has no code collision).
            continue

        if correct_code is None:
            # The chart has no account actually named for this purpose -- the
            # original migration's match was coincidental/wrong; revert to
            # fail-closed so post_replenishment's ControlAccountError forces an
            # accountant to assign the right account explicitly.
            conn.execute(
                sa.text("DELETE FROM app_settings WHERE key = :k AND updated_by = 'migration'"),
                {'k': setting_key})
        else:
            conn.execute(
                sa.text("UPDATE app_settings SET value = :v, updated_by = 'migration' "
                        "WHERE key = :k AND updated_by = 'migration'"),
                {'v': correct_code, 'k': setting_key})


def downgrade():
    # Not reversible to the prior (buggy) code-matched value -- that value is not
    # recoverable once corrected/cleared. No-op downgrade.
    pass
