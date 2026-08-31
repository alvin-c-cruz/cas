"""Purchase Orders carry a currency CODE, defaulting to PHP.

Revision ID: pocur_0001
Revises: memoseries_0001
Create Date: 2026-08-31

Owner directive 2026-08-31, from the client's own annotation on legacy pad PO 00984:
"PO can be of any currency. default is PHP". The legacy form prints the currency to
the left of the total and CAS printed nothing there.

Scope is deliberately a LABEL. The amount stays booked in pesos, the Receiving Report
still values stock in pesos, and the AP bill and GL still post in pesos -- no FX rate
exists anywhere in CAS and none is introduced here. Anything more is a separate arc.

`server_default='PHP'` as well as the ORM default on purpose: every Purchase Order
already on the five client instances is backfilled to 'PHP' by this ADD COLUMN rather
than left NULL, because a NULL would print an EMPTY label exactly where the pre-printed
pad prints a currency. That also makes the column safely NOT NULL in the same step.

batch_alter_table because the column is NOT NULL: SQLite cannot add a NOT NULL column
without a default, and batch mode is this project's standing convention for any
purchase_orders schema change.
"""
import sqlalchemy as sa
from alembic import op

revision = 'pocur_0001'
down_revision = 'memoseries_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('purchase_orders') as batch:
        batch.add_column(sa.Column('currency', sa.String(length=3),
                                   nullable=False, server_default='PHP'))


def downgrade():
    with op.batch_alter_table('purchase_orders') as batch:
        batch.drop_column('currency')
