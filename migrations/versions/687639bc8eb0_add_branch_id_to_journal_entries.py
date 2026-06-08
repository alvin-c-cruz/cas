"""add branch_id to journal_entries

Revision ID: 687639bc8eb0
Revises: 93433089aa65
Create Date: 2026-06-07 18:01:20.573359

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '687639bc8eb0'
down_revision = '93433089aa65'
branch_labels = None
depends_on = None


def upgrade():
    # Determine a default branch ID to satisfy the NOT NULL column.
    connection = op.get_bind()
    first_branch = connection.execute(
        sa.text("SELECT id FROM branches ORDER BY id LIMIT 1")
    ).fetchone()

    if first_branch:
        default_branch_id = first_branch[0]
    else:
        # Fresh database (e.g. new dev setup or CI): no branches exist yet.
        # journal_entries is necessarily empty too, so the server_default is
        # only needed to satisfy NOT NULL during the ALTER -- no existing rows
        # are backfilled, and it is stripped again below. Fall back to a
        # placeholder so the migration chain runs end-to-end on an empty DB.
        default_branch_id = 1

    # Add branch_id column with default value (SQLite doesn't support ALTER COLUMN)
    # Use the WITH DEFAULT clause to set existing rows
    with op.batch_alter_table('journal_entries') as batch_op:
        batch_op.add_column(
            sa.Column('branch_id', sa.Integer(), nullable=False, server_default=str(default_branch_id))
        )
        batch_op.create_index('ix_journal_entries_branch_id', ['branch_id'], unique=False)
        batch_op.create_foreign_key('fk_journal_entries_branch', 'branches', ['branch_id'], ['id'])

    # Remove server_default after data is migrated
    with op.batch_alter_table('journal_entries') as batch_op:
        batch_op.alter_column('branch_id', server_default=None)


def downgrade():
    # Remove foreign key, index, and column
    with op.batch_alter_table('journal_entries') as batch_op:
        batch_op.drop_constraint('fk_journal_entries_branch', type_='foreignkey')
        batch_op.drop_index('ix_journal_entries_branch_id')
        batch_op.drop_column('branch_id')
