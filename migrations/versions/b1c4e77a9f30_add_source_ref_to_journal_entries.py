"""add source_ref to journal_entries (legacy-import provenance)

Additive and nullable: every existing row keeps source_ref = NULL, so this is a
no-op for entries created inside CAS. The unique index makes a re-run of the
legacy importer idempotent instead of doubling the books.

Hand-written with batch ops -- Migrate() is configured without render_as_batch,
and SQLite cannot ALTER a table to add an index in place.

Revision ID: b1c4e77a9f30
Revises: a7c3f1e9b2d4
Create Date: 2026-07-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1c4e77a9f30'
down_revision = 'a7c3f1e9b2d4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('journal_entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_ref', sa.String(length=100), nullable=True))
        batch_op.create_index(
            'ix_journal_entries_source_ref', ['source_ref'], unique=True
        )


def downgrade():
    with op.batch_alter_table('journal_entries', schema=None) as batch_op:
        batch_op.drop_index('ix_journal_entries_source_ref')
        batch_op.drop_column('source_ref')
