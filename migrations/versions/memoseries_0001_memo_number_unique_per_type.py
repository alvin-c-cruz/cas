"""Memo numbers are unique per memo_type, not table-wide.

Revision ID: memoseries_0001
Revises: custlock_0001
Create Date: 2026-08-31

`sales_memos.memo_number` and `purchase_memos.memo_number` each carried a
table-wide UNIQUE index (`ix_<table>_memo_number`), while their generators filter
by `memo_type` so Credit and Debit notes climb independent series -- both starting
at 00001. The two rules cannot both hold, and the constraint won: once one memo
type existed, the other could never be created. See
docs/bug-reports/2026-08-30-sales-memo-number-series-contradiction.md.

This swaps each table-wide unique index for a plain index plus a COMPOSITE unique
index on (memo_type, memo_number).

No batch_alter_table here on purpose: the uniqueness lives in an INDEX, not a
table constraint, so it is dropped and recreated directly and SQLite never has to
rebuild the table. That also sidesteps batch mode's habit of silently preserving
unnamed constraints across the rebuild.

Data safety: verified 2026-08-31 that sales_memos and purchase_memos are EMPTY in
every client instance (alvinccruz, bccruz, philgen, ric, zhiyuan latest backups,
plus the local philgen/ric working DBs), so there is nothing to migrate and no
possibility of a pre-existing row violating the new composite key. The downgrade
is only safe while that remains true -- it restores a table-wide unique index,
which would fail if rows by then share a number across types.
"""
from alembic import op

revision = 'memoseries_0001'
down_revision = 'custlock_0001'
branch_labels = None
depends_on = None

_TABLES = [
    ('sales_memos', 'ix_sales_memos_memo_number', 'uq_sales_memos_type_number'),
    ('purchase_memos', 'ix_purchase_memos_memo_number', 'uq_purchase_memos_type_number'),
]


def upgrade():
    for table, num_ix, comp_ix in _TABLES:
        op.drop_index(num_ix, table_name=table)
        op.create_index(num_ix, table, ['memo_number'], unique=False)
        op.create_index(comp_ix, table, ['memo_type', 'memo_number'], unique=True)


def downgrade():
    for table, num_ix, comp_ix in _TABLES:
        op.drop_index(comp_ix, table_name=table)
        op.drop_index(num_ix, table_name=table)
        op.create_index(num_ix, table, ['memo_number'], unique=True)
