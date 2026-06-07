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
    # Get the first branch ID to use as default
    connection = op.get_bind()
    result = connection.execute(sa.text("SELECT id FROM branches ORDER BY id LIMIT 1"))
    first_branch = result.fetchone()

    if not first_branch:
        raise Exception("No branches found in database. Cannot add branch_id to journal_entries.")

    default_branch_id = first_branch[0]

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
