"""products.code becomes optional

Owner, 2026-09-08: clients do not use the product code, and it is being retired
from every screen. This is the reversible half -- the column and its 555 values
stay, and the unique index stays with them; only the NOT NULL goes.

The unique index is deliberately RETAINED. SQLite permits multiple NULLs under a
unique index, so products created from here on simply have no code while every
existing code stays unique. Dropping the index would let duplicates in among the
recorded codes, and no later step could sort that out.

Revision ID: prodcode_0001
Revises: prreturn_0001
Create Date: 2026-09-08

"""
from alembic import op
import sqlalchemy as sa


revision = 'prodcode_0001'
down_revision = 'prreturn_0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.alter_column('code', existing_type=sa.String(length=50),
                              nullable=True)


def downgrade():
    """Refuses while any product has no code.

    Restoring NOT NULL with codeless rows present would fail mid-rebuild, or --
    worse, if someone 'helpfully' backfilled -- invent codes that were never
    assigned. Better to stop and let the operator decide what those products
    should be called.
    """
    conn = op.get_bind()
    codeless = conn.execute(sa.text(
        'SELECT COUNT(*) FROM products WHERE code IS NULL')).scalar()
    if codeless:
        raise RuntimeError(
            '%d product(s) have no code. Downgrading would restore NOT NULL with '
            'nowhere to put them. Assign codes deliberately, then retry.' % codeless)
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.alter_column('code', existing_type=sa.String(length=50),
                              nullable=False)
