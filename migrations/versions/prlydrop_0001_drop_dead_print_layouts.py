"""Drop the dead print_layouts table

An abandoned 2026-07-02 attempt at pre-printed layouts: created by f826f2cca271,
given account_id and its constraints by 307cc71c8779, then superseded by the
app_settings approach and later by the named-layouts feature -- which had to name
its tables `named_print_layouts` / `named_print_layout_device_prefs` because this
one squatted the obvious name. Empty on philgen and ric, mapped by no model, read
by no code. Owner, 2026-09-25: drop it.

UPGRADE REFUSES IF THE TABLE HAS ROWS. "Dead" was established by looking at two
databases; an instance nobody looked at could hold data. Losing it silently to a
housekeeping migration would be the wrong trade, so the upgrade stops instead.

DEPLOY NOTE: `flask integrity-check --compare-aggregates` treats a table that
vanished as hard drift at ANY row count (a deliberate rule -- see
app/integrity/checks.py). Across this migration it will therefore report
`[BAD] aggregate_row_counts: drift: print_layouts:0->None` and exit 1. That line,
and only that line, is expected; any other drift is not.

The downgrade rebuilds the table exactly as 307cc71c8779 left it: same columns,
the account_id FK, the (voucher_type, account_id) unique constraint, both plain
indexes and the partial unique index for one Default per voucher_type.

Revision ID: prlydrop_0001
Revises: cdvpay_0001
Create Date: 2026-09-25
"""
import sqlalchemy as sa
from alembic import op

revision = 'prlydrop_0001'
down_revision = 'cdvpay_0001'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    rows = conn.execute(sa.text('SELECT COUNT(*) FROM print_layouts')).scalar()
    if rows:
        raise RuntimeError(f'print_layouts is not empty ({rows} row(s)); refusing to drop it. '
                           f'Inspect the rows before removing this table.')
    op.drop_table('print_layouts')      # its indexes go with it


def downgrade():
    op.create_table(
        'print_layouts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('voucher_type', sa.String(length=16), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('background_image', sa.String(length=200), nullable=True),
        sa.Column('page_width_mm', sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column('page_height_mm', sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column('fields_json', sa.Text(), nullable=True),
        sa.Column('line_band_json', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by', sa.String(length=80), nullable=True),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'],
                                name='fk_print_layouts_account_id_accounts'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('voucher_type', 'account_id',
                            name='uq_print_layouts_voucher_type_account_id'),
    )
    op.create_index('ix_print_layouts_voucher_type', 'print_layouts', ['voucher_type'], unique=False)
    op.create_index('ix_print_layouts_account_id', 'print_layouts', ['account_id'], unique=False)
    op.create_index('uq_print_layouts_default_per_type', 'print_layouts', ['voucher_type'],
                    unique=True, sqlite_where=sa.text('account_id IS NULL'))
