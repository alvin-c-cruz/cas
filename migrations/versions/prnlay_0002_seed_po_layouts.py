"""Seed named_print_layouts from the existing po_preprinted_layout* app_settings.

One is_default PrintLayout row per existing `po_preprinted_layout` /
`po_preprinted_layout:<branch_id>` key, payload copied RAW (see
app/print_layouts/migrate.py::seed_from_app_settings -- the migration is a thin
wrapper around that importable/testable helper). `flask db upgrade` already runs
this inside a Flask app context (migrations/env.py resolves `current_app` at
module scope), matching the existing data-migration convention -- see
36517765f386_backfill_accountant_viewer_book_.py -- so no app_context() wrapper
is needed here.

The legacy `app_settings` keys are NOT touched in either direction -- this is a
copy, not a move. Downgrade deletes only from `named_print_layouts`, and only
the rows this revision could have created (doc_type='purchase_orders'). It never
touches the separate, unrelated legacy `print_layouts` table (an abandoned 2026
attempt at this same problem) -- that table is out of scope for this feature
entirely.

Revision ID: prnlay_0002
Revises: prnlay_0001
"""
from alembic import op

revision = 'prnlay_0002'
down_revision = 'prnlay_0001'
branch_labels = None
depends_on = None


def upgrade():
    from app.print_layouts.migrate import seed_from_app_settings
    seed_from_app_settings(doc_type='purchase_orders', key_prefix='po_preprinted_layout')


def downgrade():
    # Raw SQL, not the ORM, and against named_print_layouts ONLY -- never the
    # separate legacy print_layouts table. See module docstring.
    op.execute("DELETE FROM named_print_layouts WHERE doc_type = 'purchase_orders'")
