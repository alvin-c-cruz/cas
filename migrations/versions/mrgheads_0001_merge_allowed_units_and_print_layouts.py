"""Merge the two heads created by landing allowed-units and print-layouts together.

`prodau_0001` (per-product allowed units) and `prnlay_0001` (named print layouts)
were written on separate branches and both declare `apamd_0001` as their parent.
Each was a single head while its branch stood alone; merging both branches into
main left alembic with TWO heads, and `flask db upgrade` refuses to run at all in
that state ("Multiple head revisions are present").

This revision does nothing but rejoin them. It creates, alters and drops nothing,
so it is safe in both directions and needs no batch wrapper -- there is no table
to rebuild. Its only job is to give the graph one head again.

Revision ID: mrgheads_0001
Revises: prodau_0001, prnlay_0002
Create Date: 2026-09-21
"""
from alembic import op  # noqa: F401  -- imported for convention; nothing is emitted
import sqlalchemy as sa  # noqa: F401

revision = 'mrgheads_0001'
down_revision = ('prodau_0001', 'prnlay_0002')
branch_labels = None
depends_on = None


def upgrade():
    """No schema change -- see the module docstring."""
    pass


def downgrade():
    """No schema change -- see the module docstring."""
    pass
