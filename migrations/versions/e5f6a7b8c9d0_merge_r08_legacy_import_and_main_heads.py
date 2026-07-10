"""merge the three alembic heads (main, R-08 phase 1, legacy GL import)

Pure merge point -- no schema change. Three feature lines each branched from a
different ancestor and each carried a single head of their own:

  b8d4c1f2a9e3  main            (debit-note collectible)
  d3c9e2f5a6b7  R-08 phase 1    (vat_nature on the four line tables)
  b1c4e77a9f30  legacy GL import (journal_entries.source_ref)

Merging them without this file leaves `flask db upgrade` refusing to run, which
blocks every client deploy. Same pattern as a84189785f23 (po_required +
vat_settlements).

Revision ID: e5f6a7b8c9d0
Revises: b8d4c1f2a9e3, d3c9e2f5a6b7, b1c4e77a9f30
Create Date: 2026-07-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = ('b8d4c1f2a9e3', 'd3c9e2f5a6b7', 'b1c4e77a9f30')
branch_labels = None
depends_on = None


def upgrade():
    """No-op: this revision exists only to reunite the three heads."""


def downgrade():
    """No-op."""
