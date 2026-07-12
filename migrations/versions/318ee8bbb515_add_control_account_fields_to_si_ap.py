"""add per-transaction control-account fields to sales_invoices and accounts_payable

Revision ID: 318ee8bbb515
Revises: bir_bkoff1
Create Date: 2026-07-12

"""
from alembic import op
import sqlalchemy as sa

revision = '318ee8bbb515'
down_revision = 'bir_bkoff1'
branch_labels = None
depends_on = None

# (table, new_column, backfill AppSettings key)
_COLUMNS = [
    ('sales_invoices', 'ar_trade_account_id', 'ar_trade_account_code'),
    ('sales_invoices', 'creditable_wht_account_id', 'creditable_wht_account_code'),
    ('accounts_payable', 'ap_trade_account_id', 'ap_trade_account_code'),
    ('accounts_payable', 'wht_payable_account_id', 'wht_payable_account_code'),
]


def upgrade():
    for table, column, _ in _COLUMNS:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column(column, sa.Integer(), nullable=True))

    conn = op.get_bind()
    for table, column, setting_key in _COLUMNS:
        row = conn.execute(
            sa.text("SELECT value FROM app_settings WHERE key = :k"),
            {'k': setting_key}).first()
        if not row or not row[0]:
            continue  # setting unassigned -> leave existing rows NULL
        acct = conn.execute(
            sa.text("SELECT id FROM accounts WHERE code = :c"),
            {'c': row[0]}).first()
        if acct is None:
            continue  # setting points at a code with no matching account
        conn.execute(
            sa.text(f"UPDATE {table} SET {column} = :aid WHERE {column} IS NULL"),
            {'aid': acct[0]})


def downgrade():
    for table, column, _ in _COLUMNS:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column(column)
