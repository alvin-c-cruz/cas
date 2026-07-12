"""backfill module_enabled:bir_reports=1 for already-deployed (pre-existing) installs

Revision ID: bir_bkoff1
Revises: prodcat_0002
Create Date: 2026-07-12

Context: MODULE_REGISTRY's 'bir_reports' entry flips 'default_enabled' from True to False
in this same change (app/users/module_access.py), so every optional module now uniformly
defaults OFF for a brand-new install -- consistent with quotations/sales_orders/products/
employees/etc, which were already default-off.

Why a backfill is needed: CAS is deployed to multiple LIVE client instances (RIC,
alvinccruz, zhiyuan, philgen) that have been running with BIR Reports enabled (it was
default-on) and have NEVER had a reason to write an explicit
'module_enabled:bir_reports' override row -- nobody ever had to toggle a switch that was
already in the position they wanted. If this migration did nothing, `flask db upgrade`
against any of those real DBs would silently make BIR Reports (VAT return, alphalist,
2307, withholding certs, VAT settlement) disappear from the sidebar -- a functional
regression for paying clients who never asked for this.

Heuristic: any live/pre-existing database being migrated forward already has real usage
by the time it reaches this migration -- at minimum, one or more rows in `users` (an
admin was already bootstrapped and has been using the app). A genuinely fresh install
running the full migration chain from base to head for the first time has ZERO rows in
`users` at the point this migration executes -- user creation only happens via the app's
first-run bootstrap (`/register` or a `flask seed-*` command) AFTER migrations complete.
So:
  - users count > 0  -> existing/already-used install -> insert an explicit
    'module_enabled:bir_reports' = '1' override (idempotent: only if no such row exists
    yet, and defensive even though today no client should already have one), so the
    upgrade is a no-op for their visible behavior.
  - users count == 0 -> genuinely fresh install applying the whole chain today -> do
    nothing; the new default_enabled=False applies naturally once the app boots.

Downgrade is intentionally a no-op: removing the backfilled override on downgrade isn't
meaningful (there is no prior state to restore to -- the row didn't exist before this
migration ran) or safe (a client may have since re-saved that exact override through the
Settings UI for reasons unrelated to this migration, and deleting it out from under them
would be an unrelated regression).
"""
from alembic import op
import sqlalchemy as sa

revision = 'bir_bkoff1'
down_revision = 'prodcat_0002'
branch_labels = None
depends_on = None

_SETTING_KEY = 'module_enabled:bir_reports'


def upgrade():
    conn = op.get_bind()
    user_count = conn.execute(sa.text("SELECT COUNT(*) FROM users")).scalar()
    if not user_count:
        return  # fresh install (0 users at migration time) -- let the new default apply

    exists = conn.execute(
        sa.text("SELECT 1 FROM app_settings WHERE key = :k"),
        {'k': _SETTING_KEY}).first()
    if exists:
        return  # already has an explicit override (of any value) -- don't clobber it

    conn.execute(
        sa.text("INSERT INTO app_settings (key, value, updated_by) "
                "VALUES (:k, :v, 'system_migration')"),
        {'k': _SETTING_KEY, 'v': '1'})


def downgrade():
    # No-op by design -- see module docstring.
    pass
