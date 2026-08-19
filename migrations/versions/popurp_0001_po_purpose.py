"""Purchase Order: what the order is FOR

Revision ID: popurp_0001
Revises: rrsub_0001
Create Date: 2026-08-19

PhilGen's pre-printed PO shows a caption above the line items saying what the
order is for -- "FOR PRODUCTION USE", "FOR THE REPAIR OF INNOVA". Their legacy
system stored that string on EVERY purchase_order_detail row (`side_note`) and
its print grouped the lines by it.

This models it as a HEADER column instead, on measured evidence rather than on
the shape of the legacy schema: across the 168 POs in the legacy database --
118 of them multi-line -- every single one carries exactly ONE distinct
side_note. The grouping has never produced a second group, so the value is a
header attribute that was being stored redundantly per line.

Nullable with no backfill and no default: an existing order has no recorded
purpose, and inventing one ("General") would put words into historic documents
nobody wrote. The print omits the caption entirely when it is blank.

Nothing is dropped and no existing value is rewritten, so this is reversible
without loss.
"""
import sqlalchemy as sa
from alembic import op

revision = 'popurp_0001'
down_revision = 'rrsub_0001'
branch_labels = None
depends_on = None

TABLE = 'purchase_orders'
COLUMN = 'purpose'


def upgrade():
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}
    if COLUMN not in existing:
        with op.batch_alter_table(TABLE) as batch:
            batch.add_column(sa.Column(COLUMN, sa.String(length=200), nullable=True))


def downgrade():
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}
    if COLUMN in existing:
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_column(COLUMN)
